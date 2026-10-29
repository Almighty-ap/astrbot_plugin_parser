import asyncio
from re import Match
from typing import ClassVar
from urllib.parse import urlparse

from aiohttp import ClientError, ClientTimeout
from bilibili_api import request_settings, select_client
from bilibili_api.opus import Opus
from bilibili_api.video import Video, VideoCodecs, VideoQuality
from msgspec import convert

from astrbot.api import logger

from ...config import PluginConfig
from ...data import ImageContent, MediaContent, Platform, SendGroup
from ...exception import DownloadException, DurationLimitException
from ..base import (
    BaseParser,
    Downloader,
    ParseException,
    handle,
)
from .login import BilibiliLogin

try:
    select_client("curl_cffi")
    request_settings.set("impersonate", "chrome131")
except Exception as e:
    raise ModuleNotFoundError(
        f"curl_cffi is required by bilibili parser but not installed: {e}"
    ) from e


BLOCKED_PCDN_DOMAINS = (
    "mcdn.bilivideo.com",
    "mcdn.bilivideo.cn",
    "szbdyd.com",
    "mountaintoys.cn",
    "nexusedgeio.com",
    "ahdohpiechei.com",
)

# 常见的稳定高可用 B 站 UPOS 镜像节点
DEFAULT_UPOS_MIRRORS: tuple[str, ...] = (
    "upos-sz-mirrorali.bilivideo.com",     # 阿里云国内
    "upos-sz-mirrorcos.bilivideo.com",     # 腾讯云国内
    "upos-sz-mirrorhw.bilivideo.com",      # 华为云国内
    "upos-sz-mirroraliov.bilivideo.com",   # 阿里云海外
)

# 针对机房数据中心 IP 极易触发 HTTP 567 WAF 拦截或严重限速断流的已知问题节点
BLOCKED_OR_PROBLEMATIC_UPOS: tuple[str, ...] = (
    "upos-sz-mirrorcosov.bilivideo.com",   # 腾讯云海外，高频报 567
)


def _is_pcdn_url(url: str) -> bool:
    if not url:
        return False
    try:
        host = (urlparse(url).hostname or "").lower()
        return any(host == d or host.endswith("." + d) for d in BLOCKED_PCDN_DOMAINS)
    except Exception:
        return False


def _get_stream_urls(
    stream, filter_pcdn: bool, backup_urls: list[str] | None = None
) -> list[str]:
    all_urls = [stream.url, *(getattr(stream, "backup_url", None) or [])]
    all_urls.extend(backup_urls or [])
    if filter_pcdn:
        clean_urls = [url for url in all_urls if not _is_pcdn_url(url)]
        if clean_urls:
            all_urls = clean_urls

    # 若为 UPOS 节点，生成可靠的镜像降级节点以抵御海外 567 拦截或断流
    upos_fallback_urls: list[str] = []
    for raw_url in all_urls:
        if not raw_url:
            continue
        parts = urlparse(raw_url)
        host = (parts.hostname or "").lower()
        if host.startswith("upos-") or host in BLOCKED_OR_PROBLEMATIC_UPOS:
            for mirror in DEFAULT_UPOS_MIRRORS:
                if mirror != host:
                    fallback_url = parts._replace(netloc=mirror, scheme="https").geturl()
                    if fallback_url not in upos_fallback_urls:
                        upos_fallback_urls.append(fallback_url)

    raw_candidates = all_urls + upos_fallback_urls
    normal_candidates: list[str] = []
    deprioritized_candidates: list[str] = []

    for url in raw_candidates:
        if not url:
            continue
        parts = urlparse(url)
        host = (parts.hostname or "").lower()
        if parts.scheme == "http" and (
            host == "bilivideo.com" or host.endswith(".bilivideo.com")
        ):
            url = parts._replace(scheme="https").geturl()

        if any(bad in host for bad in BLOCKED_OR_PROBLEMATIC_UPOS):
            if url not in deprioritized_candidates:
                deprioritized_candidates.append(url)
        else:
            if url not in normal_candidates:
                normal_candidates.append(url)

    return normal_candidates + deprioritized_candidates


def _get_backup_urls(stream, entries: list[dict]) -> list[str]:
    return [
        url
        for entry in entries
        if stream.url in (entry.get("base_url"), entry.get("baseUrl"), entry.get("url"))
        for url in entry.get("backup_url") or entry.get("backupUrl") or []
    ]


class BilibiliParser(BaseParser):
    # 平台信息
    platform: ClassVar[Platform] = Platform(name="bilibili", display_name="B站")

    def __init__(self, config: PluginConfig, downloader: Downloader):
        super().__init__(config, downloader)
        self.mycfg = config.parser.bilibili
        self.headers.update(
            {
                "Referer": "https://www.bilibili.com/",
                "Origin": "https://www.bilibili.com",
            }
        )

        self.video_quality = getattr(
            VideoQuality, str(self.mycfg.video_quality).upper(), VideoQuality._720P
        )
        self.video_codecs = [
            getattr(VideoCodecs, str(c).upper(), VideoCodecs.AVC)
            for c in (self.mycfg.video_codec_list or ["AVC"])
        ]
        self.login = BilibiliLogin(config)

    @handle("b23.tv", r"b23\.tv/[A-Za-z\d\._?%&+\-=/#]+")
    @handle("bili2233", r"bili2233\.cn/[A-Za-z\d\._?%&+\-=/#]+")
    async def _parse_short_link(self, searched: Match[str]):
        """解析短链"""
        url = f"https://{searched.group(0)}"
        return await self.parse_with_redirect(url)

    @handle("BV", r"^(?P<bvid>BV[0-9a-zA-Z]{10})(?:\s)?(?P<page_num>\d{1,3})?$")
    @handle(
        "/BV",
        r"bilibili\.com(?:/video)?/(?P<bvid>BV[0-9a-zA-Z]{10})(?:\?p=(?P<page_num>\d{1,3}))?",
    )
    async def _parse_bv(self, searched: Match[str]):
        """解析视频信息"""
        bvid = str(searched.group("bvid"))
        page_num = int(searched.group("page_num") or 1)

        return await self.parse_video(bvid=bvid, page_num=page_num)

    @handle("bm", r"^bm(?P<bvid>BV[0-9a-zA-Z]{10})(?:\s(?P<page_num>\d{1,3}))?$")
    async def _parse_bv_bm(self, searched: Match[str]):
        bvid = searched.group("bvid")
        page = int(searched.group("page_num") or 1)
        _, a_url = await self.extract_download_urls(
            bvid=bvid, page_index=page - 1, audio_only=True
        )
        if not a_url:
            raise ParseException("未找到音频链接")
        audio = self.create_audio_content(a_url)
        return self.result(
            title=f"BiliBili_audio_{bvid}",
            contents=[audio],
            url=a_url,
        )

    @handle("av", r"^av(?P<avid>\d{6,})(?:\s)?(?P<page_num>\d{1,3})?$")
    @handle(
        "/av",
        r"bilibili\.com(?:/video)?/av(?P<avid>\d{6,})(?:\?p=(?P<page_num>\d{1,3}))?",
    )
    async def _parse_av(self, searched: Match[str]):
        """解析视频信息"""
        avid = int(searched.group("avid"))
        page_num = int(searched.group("page_num") or 1)

        return await self.parse_video(avid=avid, page_num=page_num)

    @handle("/dynamic/", r"bilibili\.com/dynamic/(?P<dynamic_id>\d+)")
    @handle("t.bili", r"t\.bilibili\.com/(?P<dynamic_id>\d+)")
    async def _parse_dynamic(self, searched: Match[str]):
        """解析动态信息"""
        dynamic_id = int(searched.group("dynamic_id"))
        return await self.parse_dynamic(dynamic_id)

    @handle("live.bili", r"live\.bilibili\.com/(?P<room_id>\d+)")
    async def _parse_live(self, searched: Match[str]):
        """解析直播信息"""
        room_id = int(searched.group("room_id"))
        return await self.parse_live(room_id)

    @handle("/favlist", r"favlist\?fid=(?P<fav_id>\d+)")
    async def _parse_favlist(self, searched: Match[str]):
        """解析收藏夹信息"""
        fav_id = int(searched.group("fav_id"))
        return await self.parse_favlist(fav_id)

    @handle("/read/", r"bilibili\.com/read/cv(?P<read_id>\d+)")
    async def _parse_read(self, searched: Match[str]):
        """解析专栏信息"""
        read_id = int(searched.group("read_id"))
        return await self.parse_read_with_opus(read_id)

    @handle("/opus/", r"bilibili\.com/opus/(?P<opus_id>\d+)")
    async def _parse_opus(self, searched: Match[str]):
        """解析图文动态信息"""
        opus_id = int(searched.group("opus_id"))
        return await self.parse_opus(opus_id)

    async def parse_video(
        self,
        *,
        bvid: str | None = None,
        avid: int | None = None,
        page_num: int = 1,
    ):
        """解析视频信息

        Args:
            bvid (str | None): bvid
            avid (int | None): avid
            page_num (int): 页码
        """

        from .video import AIConclusion, VideoInfo

        video = await self._get_video(bvid=bvid, avid=avid)
        # 转换为 msgspec struct
        video_info = convert(await video.get_info(), VideoInfo)
        # 获取简介
        text = f"简介: {video_info.desc}" if video_info.desc else None
        # up
        author = self.create_author(video_info.owner.name, video_info.owner.face)
        # 处理分 p
        page_info = video_info.extract_info_with_page(page_num)

        # 获取 AI 总结（默认提示）
        ai_summary = ""
        if self.login._credential:
            try:
                cid = await video.get_cid(page_info.index)
                ai_conclusion = await video.get_ai_conclusion(cid)
                ai_conclusion = convert(ai_conclusion, AIConclusion)
                ai_summary = ai_conclusion.summary
            except Exception:
                ai_summary = "哔哩哔哩 cookie 未配置或失效, 无法使用 AI 总结"

        url = f"https://bilibili.com/{video_info.bvid}"
        url += f"?p={page_info.index + 1}" if page_info.index > 0 else ""

        # 视频下载 task
        async def download_video():
            output_path = self.cfg.cache_dir / f"{video_info.bvid}-{page_num}.mp4"
            if output_path.exists():
                return output_path
            v_url, a_url = await self.extract_download_urls(
                video=video, page_index=page_info.index
            )
            if page_info.duration > self.cfg.max_duration:
                raise DurationLimitException
            if a_url is not None:
                return await self.downloader.download_av_and_merge(
                    v_url,
                    a_url,
                    output_path=output_path,
                    headers=self.headers,
                    proxy=self.proxy,
                )
            else:
                return await self.downloader.streamd(
                    v_url,
                    file_name=output_path.name,
                    headers=self.headers,
                    proxy=self.proxy,
                )

        video_task = asyncio.create_task(download_video())
        video_content = self.create_video_content(
            video_task,
            page_info.cover,
            page_info.duration,
        )

        return self.result(
            url=url,
            title=page_info.title,
            timestamp=page_info.timestamp,
            text=text,
            author=author,
            contents=[video_content],
            extra={"info": ai_summary},
        )

    async def parse_dynamic(self, dynamic_id: int):
        """解析动态信息

        Args:
            url (str): 动态链接
        """
        from bilibili_api.dynamic import Dynamic

        from .dynamic import DynamicData

        dynamic_ = Dynamic(dynamic_id, await self.login.credential)

        dynamic_info = convert(await dynamic_.get_info(), DynamicData).item
        author = self.create_author(dynamic_info.name, dynamic_info.avatar)

        # 下载图片
        contents: list[MediaContent] = []
        for image_url in dynamic_info.image_urls:
            img_task = self.downloader.download_img(
                image_url, headers=self.headers, proxy=self.proxy
            )
            contents.append(ImageContent(img_task))

        return self.result(
            title=dynamic_info.title,
            text=dynamic_info.text,
            timestamp=dynamic_info.timestamp,
            author=author,
            contents=contents,
        )

    async def parse_opus(self, opus_id: int):
        """解析图文动态信息

        Args:
            opus_id (int): 图文动态 id
        """
        opus = Opus(opus_id, await self.login.credential)
        return await self._parse_opus_obj(opus)

    async def parse_read_with_opus(self, read_id: int):
        """解析专栏信息, 使用 Opus 接口
        Args:
            read_id (int): 专栏 id
        """
        from bilibili_api.article import Article

        article = Article(read_id)
        return await self._parse_opus_obj(await article.turn_to_opus())

    async def _parse_opus_obj(self, bili_opus: Opus):
        """解析图文动态信息
        Args:
            opus_id (int): 图文动态 id
        Returns:
            ParseResult: 解析结果
        """
        from .opus import ImageNode, OpusItem, TextNode

        opus_info = await bili_opus.get_info()
        if not isinstance(opus_info, dict):
            raise ParseException("获取图文动态信息失败")
        # 转换为结构体
        opus_data = convert(opus_info, OpusItem)
        logger.debug(f"opus_data: {opus_data}")
        author = self.create_author(*opus_data.name_avatar)
        # 按顺序处理图文内容（参考 parse_read 的逻辑）
        contents: list[MediaContent] = []
        current_text = ""
        for node in opus_data.gen_text_img():
            if isinstance(node, ImageNode):
                contents.append(
                    self.create_graphics_content(
                        node.url, current_text.strip(), node.alt
                    )
                )
                current_text = ""
            elif isinstance(node, TextNode):
                current_text += node.text
        return self.result(
            title=opus_data.title,
            author=author,
            timestamp=opus_data.timestamp,
            contents=contents,
            text=current_text.strip(),
            # 图文动态全是轻媒体，默认发送计划不会渲染卡片，
            # 显式要求先发一张"文字+图片"合一的媒体卡片
            send_groups=(
                [SendGroup(contents=contents, render_card=True, force_merge=False)]
                if contents
                else []
            ),
        )

    async def parse_live(self, room_id: int):
        """解析直播信息

        Args:
            room_id (int): 直播 id

        Returns:
            ParseResult: 解析结果
        """
        from bilibili_api.live import LiveRoom

        from .live import RoomData

        room = LiveRoom(room_display_id=room_id, credential=await self.login.credential)
        info_dict = await room.get_room_info()

        room_data = convert(info_dict, RoomData)
        contents: list[MediaContent] = []
        # 下载封面
        if cover := room_data.cover:
            cover_task = self.downloader.download_img(
                cover, headers=self.headers, proxy=self.proxy
            )
            contents.append(ImageContent(cover_task))

        # 下载关键帧
        if keyframe := room_data.keyframe:
            keyframe_task = self.downloader.download_img(
                keyframe, headers=self.headers, proxy=self.proxy
            )
            contents.append(ImageContent(keyframe_task))

        author = self.create_author(room_data.name, room_data.avatar)

        url = f"https://www.bilibili.com/blackboard/live/live-activity-player.html?enterTheRoom=0&cid={room_id}"
        return self.result(
            url=url,
            title=room_data.title,
            text=room_data.detail,
            contents=contents,
            author=author,
        )

    async def parse_favlist(self, fav_id: int):
        """解析收藏夹信息

        Args:
            fav_id (int): 收藏夹 id

        Returns:
            list[GraphicsContent]: 图文内容列表
        """
        from bilibili_api.favorite_list import get_video_favorite_list_content

        from .favlist import FavData

        # 只会取一页，20 个
        fav_dict = await get_video_favorite_list_content(fav_id)

        if fav_dict["medias"] is None:
            raise ParseException("收藏夹内容为空, 或被风控")

        favdata = convert(fav_dict, FavData)

        return self.result(
            title=favdata.title,
            timestamp=favdata.timestamp,
            author=self.create_author(favdata.info.upper.name, favdata.info.upper.face),
            contents=[
                self.create_graphics_content(fav.cover, fav.desc)
                for fav in favdata.medias
            ],
        )

    async def _get_video(
        self, *, bvid: str | None = None, avid: int | None = None
    ) -> Video:
        """解析视频信息

        Args:
            bvid (str | None): bvid
            avid (int | None): avid
        """
        if avid:
            return Video(aid=avid, credential=await self.login.credential)
        elif bvid:
            return Video(bvid=bvid, credential=await self.login.credential)
        else:
            raise ParseException("avid 和 bvid 至少指定一项")

    async def _select_download_url(
        self, stream, filter_pcdn: bool, backup_urls: list[str] | None = None
    ) -> str:
        """校验下载节点，失败时尝试 B 站返回的备用地址。"""
        last_error: Exception | None = None
        for url in _get_stream_urls(stream, filter_pcdn, backup_urls):
            try:
                async with self.session.get(
                    url,
                    headers={**self.headers, "Range": "bytes=0-0"},
                    proxy=self.proxy,
                    timeout=ClientTimeout(total=self.cfg.common_timeout),
                ) as response:
                    if response.status not in (200, 206):
                        raise ClientError(f"HTTP {response.status}")
                    if not await response.content.read(1):
                        raise ClientError("Empty media response")
                if url != stream.url:
                    logger.info(
                        f"B站下载切换备用节点 | host: {urlparse(url).hostname}"
                    )
                return url
            except (ClientError, asyncio.TimeoutError) as exc:
                last_error = exc
                logger.warning(
                    f"B站下载节点不可用 | host: {urlparse(url).hostname}, "
                    f"error: {type(exc).__name__}"
                )

        raise DownloadException("B站媒体下载节点均不可用") from last_error

    async def extract_download_urls(
        self,
        video: Video | None = None,
        *,
        bvid: str | None = None,
        avid: int | None = None,
        page_index: int = 0,
        audio_only: bool = False,
    ) -> tuple[str, str | None]:
        """解析视频下载链接

        Args:
            bvid (str | None): bvid
            avid (int | None): avid
            page_index (int): 页索引 = 页码 - 1
            audio_only (bool): 仅校验音频节点，供 bm 命令使用
        """

        from bilibili_api.video import (
            AudioStreamDownloadURL,
            MP4StreamDownloadURL,
            VideoDownloadURLDataDetecter,
            VideoStreamDownloadURL,
        )

        if video is None:
            video = await self._get_video(bvid=bvid, avid=avid)

        # 获取下载数据
        download_url_data = await video.get_download_url(page_index=page_index)
        # Normalize hvc1 streams so bilibili-api can recognize them as HEV.
        for video_data in download_url_data.get("dash", {}).get("video", []):
            codecs = video_data.get("codecs", "")
            if isinstance(codecs, str) and codecs.startswith("hvc1"):
                video_data["codecs"] = f"hev,{codecs}"
        detecter = VideoDownloadURLDataDetecter(download_url_data)
        streams = detecter.detect_best_streams(
            video_max_quality=self.video_quality,
            codecs=self.video_codecs,
            no_dolby_video=True,
            no_hdr=True,
        )
        source = download_url_data.get("video_info") or download_url_data
        dash_data = source.get("dash") or {}
        if not streams:
            raise DownloadException("未找到可下载的视频流（可能是所选编码无对应流）")
        video_stream = streams[0]
        filter_pcdn = bool(getattr(self.mycfg, "block_pcdn", False))
        audio_stream = streams[1] if len(streams) > 1 else None
        audio_entries = list(dash_data.get("audio") or [])
        flac_audio = (dash_data.get("flac") or {}).get("audio")
        if flac_audio:
            audio_entries.append(flac_audio)
        audio_entries.extend((dash_data.get("dolby") or {}).get("audio") or [])
        audio_backups = (
            _get_backup_urls(audio_stream, audio_entries)
            if isinstance(audio_stream, AudioStreamDownloadURL)
            else []
        )
        if audio_only:
            video_url = getattr(video_stream, "url", "")
            if not isinstance(audio_stream, AudioStreamDownloadURL):
                return video_url, None
            return video_url, await self._select_download_url(
                audio_stream, filter_pcdn, audio_backups
            )
        if isinstance(video_stream, MP4StreamDownloadURL):
            return await self._select_download_url(
                video_stream,
                filter_pcdn,
                _get_backup_urls(video_stream, source.get("durl") or []),
            ), None
        if not isinstance(video_stream, VideoStreamDownloadURL):
            raise DownloadException("未找到可下载的视频流")
        logger.debug(
            f"视频流质量: {video_stream.video_quality.name}, 编码: {video_stream.video_codecs}"
        )

        video_backups = _get_backup_urls(video_stream, dash_data.get("video") or [])
        if not isinstance(audio_stream, AudioStreamDownloadURL):
            return await self._select_download_url(
                video_stream, filter_pcdn, video_backups
            ), None
        logger.debug(f"音频流质量: {audio_stream.audio_quality.name}")
        v_url, a_url = await asyncio.gather(
            self._select_download_url(video_stream, filter_pcdn, video_backups),
            self._select_download_url(audio_stream, filter_pcdn, audio_backups),
        )
        return v_url, a_url
