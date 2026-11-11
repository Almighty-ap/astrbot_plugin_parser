from asyncio import Task, TimeoutError, create_task, gather, sleep, to_thread
from collections.abc import Callable, Coroutine
from functools import wraps
from pathlib import Path
from typing import Any, ParamSpec, TypeVar
from urllib.parse import urlsplit

import aiofiles
import yarl
import yt_dlp
from aiohttp import ClientError, ClientSession, ClientTimeout
from msgspec import Struct, convert
from tqdm.asyncio import tqdm

from astrbot.api import logger

from .config import PluginConfig
from .constants import CDN_REFERER, COMMON_HEADER
from .exception import (
    DownloadException,
    DurationLimitException,
    ParseException,
    SizeLimitException,
    ZeroSizeException,
)
from .utils import LimitedSizeDict, generate_file_name, merge_av, safe_unlink

P = ParamSpec("P")
T = TypeVar("T")

# 断点续传参数
_MAX_ATTEMPTS = 40  # 单次 streamd 的最大请求次数(含续传), 防止无限重试
_SOCK_CONNECT_TIMEOUT = 30  # 建连超时(秒)
_SOCK_READ_TIMEOUT = 120  # 无数据空闲超时(秒); 慢链路只要还在出字节就不会触发


def auto_task(func: Callable[P, Coroutine[Any, Any, T]]) -> Callable[P, Task[T]]:
    """装饰器：自动将异步函数调用转换为 Task, 完整保留类型提示"""

    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> Task[T]:
        coro = func(*args, **kwargs)
        name = " | ".join(str(arg) for arg in args if isinstance(arg, str))
        return create_task(coro, name=func.__name__ + " | " + name)

    return wrapper


class VideoInfo(Struct):
    title: str
    """标题"""
    channel: str
    """频道名称"""
    uploader: str
    """上传者 id"""
    duration: int
    """时长"""
    timestamp: int
    """发布时间戳"""
    thumbnail: str
    """封面图片"""
    description: str
    """简介"""
    channel_id: str
    """频道 id"""

    @property
    def author_name(self) -> str:
        return f"{self.channel}@{self.uploader}"


def is_referer_block(exc: BaseException) -> bool:
    """判断异常是否为防盗链拦截(401/403)"""
    text = str(exc)
    return "HTTP 401" in text or "HTTP 403" in text


def range_rejected(exc: BaseException) -> bool:
    """判断异常是否为 CDN 明确拒绝 Range 请求(400/416)"""
    text = str(exc)
    return "HTTP 400" in text or "HTTP 416" in text


def cdn_referer(url: str) -> str | None:
    """按目标 CDN 域名匹配兜底 Referer, 未命中返回 None"""
    host = (urlsplit(url).hostname or "").lower()
    for suffix, referer in CDN_REFERER.items():
        if host == suffix or host.endswith(f".{suffix}"):
            return referer
    return None


class Downloader:
    """下载器，支持youtube-dlp 和 流式下载"""

    def __init__(self, config: PluginConfig):
        self.cfg = config
        self.max_size = self.cfg.source_max_size
        self.default_headers: dict[str, str] = COMMON_HEADER.copy()
        # 视频信息缓存
        self.info_cache: LimitedSizeDict[str, VideoInfo] = LimitedSizeDict()
        # 用于流式下载的客户端
        # requote_redirect_url=False: 跳转目标保持原始百分号编码, 避免 CDN 签名被重编码破坏
        self.client = ClientSession(
            timeout=ClientTimeout(
                total=self.cfg.download_timeout,
                sock_connect=_SOCK_CONNECT_TIMEOUT,
                sock_read=_SOCK_READ_TIMEOUT,
            ),
            requote_redirect_url=False,
        )

    async def close(self):
        """关闭网络客户端"""
        await self.client.close()

    @auto_task
    async def streamd(
        self,
        url: str,
        *,
        file_name: str | None = None,
        headers: dict[str, str] | None = None,
        proxy: str | None | object = ...,
    ) -> Path:
        """流式下载（支持 HTTP Range 断点续传）"""
        # 默认值 ... 是「未指定」哨兵, 直接透传给 aiohttp 会 TypeError, 归一成 None
        if proxy is ...:
            proxy = None
        if not file_name:
            file_name = generate_file_name(url)
        file_path = self.cfg.cache_dir / file_name
        # 如果文件存在，则直接返回
        if file_path.exists():
            return file_path
        headers = headers or self.default_headers
        retries = self.cfg.download_retry_times
        # 必须按原始编码请求: aiohttp 默认用 yarl 解析 URL, 会把查询串里的 %2F/%3D
        # 等转义解开后重编码, 导致 CDN 签名失效(抖音图集等表现为 403)
        request_url = yarl.URL(url, encoded=True)
        max_bytes = self.max_size * 1024 * 1024
        # 先写 .part, 全部收完再原子改名: 半截文件不会被当成缓存命中
        part_path = file_path.with_name(f"{file_path.name}.part")
        await safe_unlink(part_path)

        downloaded = 0  # 已落盘字节数, 跨重试累加
        total: int | None = None  # 服务端声明的完整长度
        validator: str | None = None  # ETag / Last-Modified, 供 If-Range 校验
        range_ok = True  # CDN 是否接受 Range 请求
        stall = 0  # 连续「零进展」次数
        attempt = 0

        while stall <= retries and attempt < _MAX_ATTEMPTS:
            attempt += 1
            req_headers = dict(headers)
            if downloaded and range_ok:
                req_headers["Range"] = f"bytes={downloaded}-"
                if validator:
                    req_headers["If-Range"] = validator
            before = downloaded
            try:
                async with self.client.get(
                    request_url, headers=req_headers, allow_redirects=True, proxy=proxy
                ) as response:
                    if response.status >= 400:
                        raise ClientError(f"HTTP {response.status} {response.reason}")

                    resp_headers = getattr(response, "headers", None) or {}

                    if downloaded and response.status != 206:
                        # 服务端忽略 Range 或资源已变, 只能从头来
                        logger.debug(f"服务端未接受 Range, 从头重下 | url: {url}")
                        downloaded = 0
                        await safe_unlink(part_path)

                    if response.status == 206:
                        # Content-Range: bytes 100-999/1000
                        crange = resp_headers.get("Content-Range", "")
                        tail = crange.rsplit("/", 1)[-1].strip()
                        total = int(tail) if tail.isdigit() else None
                        if total is None and response.content_length is not None:
                            total = downloaded + response.content_length
                    else:
                        total = response.content_length
                        validator = resp_headers.get("ETag") or resp_headers.get(
                            "Last-Modified"
                        )

                    if total == 0:
                        logger.warning(f"媒体 url: {url}, 大小为 0, 取消下载")
                        raise ZeroSizeException
                    if total and total > max_bytes:
                        logger.warning(
                            f"媒体 url: {url} 大小 {total / 1024 / 1024:.2f} MB 超过 {self.max_size} MB, 取消下载"
                        )
                        raise SizeLimitException

                    with self.get_progress_bar(
                        file_name, total, initial=downloaded
                    ) as bar:
                        async with aiofiles.open(
                            part_path, "ab" if downloaded else "wb"
                        ) as file:
                            async for chunk in response.content.iter_chunked(
                                1024 * 1024
                            ):
                                downloaded += len(chunk)
                                if downloaded > max_bytes:
                                    raise SizeLimitException
                                await file.write(chunk)
                                bar.update(len(chunk))

                if downloaded == 0:
                    logger.warning(f"媒体 url: {url}, 实际大小为 0, 取消下载")
                    raise ZeroSizeException
                if total is not None and downloaded < total:
                    # 被超时/断流掐断: 抛出后由外层带 Range 续传
                    raise ClientError(f"HTTP payload incomplete {downloaded}/{total}")

                part_path.replace(file_path)
                return file_path

            except (ZeroSizeException, SizeLimitException):
                await safe_unlink(part_path)
                raise
            except (ClientError, TimeoutError) as exc:
                if downloaded > before:
                    stall = 0  # 本次有进展, 不算卡死
                else:
                    stall += 1

                # 1) 防盗链兜底: 未带 Referer 被拦时, 按域名补一个 Referer 再试一次
                if (
                    "Referer" not in headers
                    and is_referer_block(exc)
                    and (referer := cdn_referer(url))
                ):
                    headers = {**headers, "Referer": referer}
                    logger.debug(f"补 Referer 重试 | url: {url} -> {referer}")
                    continue

                # 2) CDN 明确拒绝 Range(400/416), 或补过 Referer 后仍 403: 关掉续传整段重下
                if range_ok and "Range" in req_headers and (
                    range_rejected(exc) or is_referer_block(exc)
                ):
                    logger.debug(f"CDN 拒绝 Range, 改为整段重下 | url: {url}")
                    range_ok = False
                    downloaded = 0
                    await safe_unlink(part_path)
                    continue

                if stall <= retries and attempt < _MAX_ATTEMPTS:
                    await sleep(min(1 + stall, 5))
                    continue

                logger.exception(
                    f"下载失败 | url: {url}, file_path: {file_path}, "
                    f"已下载 {downloaded} B, 请求 {attempt} 次"
                )
                await safe_unlink(part_path)
                raise DownloadException("媒体下载失败") from exc

        await safe_unlink(part_path)
        raise DownloadException("媒体下载失败")

    @staticmethod
    def get_progress_bar(
        desc: str, total: int | None = None, initial: int = 0
    ) -> tqdm:
        """获取进度条 bar

        Args:
            desc (str): 描述
            total (int | None): 总大小. Defaults to None.
            initial (int): 续传时已下载的字节数. Defaults to 0.

        Returns:
            tqdm: 进度条
        """
        return tqdm(
            total=total,
            initial=initial,
            unit="B",
            unit_scale=True,
            unit_divisor=1024,
            dynamic_ncols=True,
            colour="green",
            desc=desc,
        )

    @auto_task
    async def download_video(
        self,
        url: str,
        *,
        video_name: str | None = None,
        headers: dict[str, str] | None = None,
        proxy: str | None = None,
    ) -> Path:
        if video_name is None:
            video_name = generate_file_name(url, ".mp4")
        return await self.streamd(
            url, file_name=video_name, headers=headers, proxy=proxy
        )

    @auto_task
    async def download_audio(
        self,
        url: str,
        *,
        audio_name: str | None = None,
        headers: dict[str, str] | None = None,
        proxy: str | None = None,
    ) -> Path:
        if audio_name is None:
            audio_name = generate_file_name(url, ".mp3")
        return await self.streamd(
            url, file_name=audio_name, headers=headers, proxy=proxy
        )

    @auto_task
    async def download_file(
        self,
        url: str,
        *,
        file_name: str | None = None,
        headers: dict[str, str] | None = None,
        proxy: str | None | object = ...,
    ) -> Path:
        if file_name is None:
            file_name = generate_file_name(url, ".zip")
        return await self.streamd(
            url, file_name=file_name, headers=headers, proxy=proxy
        )

    @auto_task
    async def download_img(
        self,
        url: str,
        *,
        img_name: str | None = None,
        headers: dict[str, str] | None = None,
        proxy: str | None | object = ...,
    ) -> Path:
        if img_name is None:
            img_name = generate_file_name(url, ".jpg")
        return await self.streamd(url, file_name=img_name, headers=headers, proxy=proxy)

    async def download_imgs_without_raise(
        self,
        urls: list[str],
        *,
        headers: dict[str, str] | None = None,
        proxy: str | None | object = ...,
    ) -> list[Path]:
        paths_or_errs = await gather(
            *[self.download_img(url, headers=headers, proxy=proxy) for url in urls],
            return_exceptions=True,
        )
        return [p for p in paths_or_errs if isinstance(p, Path)]

    @auto_task
    async def download_av_and_merge(
        self,
        v_url: str,
        a_url: str,
        *,
        output_path: Path,
        headers: dict[str, str] | None = None,
        proxy: str | None = None,
    ) -> Path:
        """
        download video and audio file by url with stream and merge
        """
        v_path, a_path = await gather(
            self.download_video(v_url, headers=headers, proxy=proxy),
            self.download_audio(a_url, headers=headers, proxy=proxy),
        )
        await merge_av(v_path=v_path, a_path=a_path, output_path=output_path)
        return output_path

    async def ytdlp_extract_info(
        self,
        url: str,
        *,
        cookiefile: Path | None = None,
        headers: dict[str, str] | None = None,
        proxy: str | None = None,
        format: str | None = None,
    ) -> VideoInfo:
        if (info := self.info_cache.get(url)) is not None:
            return info
        opts = {
            "quiet": True,
            "skip_download": True,
            "http_headers": headers or self.default_headers,
        }
        if proxy:
            opts["proxy"] = proxy
        if cookiefile and cookiefile.is_file():
            opts["cookiefile"] = str(cookiefile)
        if format:
            opts["format"] = format
        # yt-dlp 默认仅启用 deno；容器内只有 node，缺失 JS 运行时会导致油管 n-sig 挑战求解失败
        opts["js_runtimes"] = {"node": {}}
        with yt_dlp.YoutubeDL(opts) as ydl:  # type: ignore
            raw = await to_thread(ydl.extract_info, url, download=False)
            if not raw:
                raise ParseException("获取视频信息失败")
        info = convert(raw, VideoInfo)
        self.info_cache[url] = info
        return info

    async def ytdlp_extract_raw(
        self,
        url: str,
        *,
        cookiefile: Path | None = None,
        headers: dict[str, str] | None = None,
        proxy: str | None = None,
        format: str | None = None,
    ) -> dict[str, Any]:
        opts = {
            "quiet": True,
            "skip_download": True,
            "http_headers": headers or self.default_headers,
        }
        if proxy:
            opts["proxy"] = proxy
        if cookiefile and cookiefile.is_file():
            opts["cookiefile"] = str(cookiefile)
        if format:
            opts["format"] = format
        # yt-dlp 默认仅启用 deno；容器内只有 node，缺失 JS 运行时会导致油管 n-sig 挑战求解失败
        opts["js_runtimes"] = {"node": {}}

        with yt_dlp.YoutubeDL(opts) as ydl:  # type: ignore
            raw = await to_thread(ydl.extract_info, url, download=False)
            if not isinstance(raw, dict):
                raise ParseException("yt-dlp 返回数据异常")
            return raw  # type: ignore

    @auto_task
    async def ytdlp_download_video(
        self,
        url: str,
        *,
        cookiefile: Path | None = None,
        headers: dict[str, str] | None = None,
        proxy: str | None = None,
        format: str | None = None,
        node: bool = False,
    ) -> Path:
        info = await self.ytdlp_extract_info(
            url, cookiefile=cookiefile, headers=headers, proxy=proxy
        )
        if info.duration > self.cfg.max_duration:
            raise DurationLimitException

        video_path = self.cfg.cache_dir / generate_file_name(url, ".mp4")
        if video_path.exists():
            return video_path

        opts = {
            "outtmpl": str(video_path),
            "merge_output_format": "mp4",
            # "format": f"bv[filesize<={info.duration // 10 + 10}M]+ba/b[filesize<={info.duration // 8 + 10}M]",
            # "format": "bv*[height<=720]+ba/b[height<=720]",
            "format": format or "best",
            "postprocessors": [
                {"key": "FFmpegVideoConvertor", "preferedformat": "mp4"}
            ],
            "http_headers": headers or self.default_headers,
        }
        if proxy:
            opts["proxy"] = proxy
        if cookiefile and cookiefile.is_file():
            opts["cookiefile"] = str(cookiefile)
        if node:
            opts["js_runtimes"] = {"node": {}}

        with yt_dlp.YoutubeDL(opts) as ydl:  # type: ignore
            await to_thread(ydl.download, [url])
        return video_path

    @auto_task
    async def ytdlp_download_video_relaxed(
        self,
        url: str,
        *,
        cookiefile: Path | None = None,
        headers: dict[str, str] | None = None,
        proxy: str | None = None,
        format: str | None = None,
        node: bool = False,
    ) -> Path:
        file_stem = generate_file_name(url)
        video_path = self.cfg.cache_dir / f"{file_stem}.mp4"
        if video_path.exists():
            return video_path

        opts = {
            "outtmpl": str(self.cfg.cache_dir / file_stem) + ".%(ext)s",
            "merge_output_format": "mp4",
            "format": format or None,
            "postprocessors": [
                {"key": "FFmpegVideoConvertor", "preferedformat": "mp4"}
            ],
            "http_headers": headers or self.default_headers,
            "quiet": True,
            "no_warnings": True,
        }
        if not opts["format"]:
            opts.pop("format")
        if proxy:
            opts["proxy"] = proxy
        if cookiefile and cookiefile.is_file():
            opts["cookiefile"] = str(cookiefile)
        if node:
            opts["js_runtimes"] = {"node": {}}

        with yt_dlp.YoutubeDL(opts) as ydl:  # type: ignore
            await to_thread(ydl.download, [url])
        if video_path.exists():
            return video_path

        candidates = sorted(self.cfg.cache_dir.glob(f"{file_stem}*.mp4"))
        if candidates:
            return candidates[0]
        raise DownloadException("yt-dlp 视频下载失败")

    @auto_task
    async def ytdlp_download_audio(
        self,
        url: str,
        *,
        cookiefile: Path | None,
        headers: dict[str, str] | None = None,
        proxy: str | None = None,
        format: str | None = None,
    ) -> Path:
        file_name = generate_file_name(url)
        audio_path = self.cfg.cache_dir / f"{file_name}.flac"
        if audio_path.exists():
            return audio_path

        opts = {
            "outtmpl": str(self.cfg.cache_dir / file_name) + ".%(ext)s",
            "format": format or "bestaudio/best",
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "flac",
                    "preferredquality": "0",
                }
            ],
            "cookiefile": None,
            "http_headers": headers or self.default_headers,
        }
        if proxy:
            opts["proxy"] = proxy
        if cookiefile and cookiefile.is_file():
            opts["cookiefile"] = str(cookiefile)

        with yt_dlp.YoutubeDL(opts) as ydl:  # type: ignore
            await to_thread(ydl.download, [url])
        return audio_path
