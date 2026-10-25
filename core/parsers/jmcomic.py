"""JMComic 解析器

识别 ``18comic.vip`` 漫画/章节链接与 ``jm<数字>`` 车号，获取章节详情后
并发下载并解密图片，最终按配置发送 PDF 或合并转发。
"""

import asyncio
from pathlib import Path
from re import Match
from typing import ClassVar

from PIL import Image

from astrbot.api import logger

try:
    from jmcomic import (
        JmcomicException,
        JmcomicText,
        JmImageTool,
        JmOption,
        JmPhotoDetail,
        MissingAlbumPhotoException,
    )
except ImportError:
    JmOption = None  # type: ignore[assignment,misc]
    MissingAlbumPhotoException = Exception  # type: ignore[misc,assignment]
    JmcomicException = Exception  # type: ignore[misc,assignment]
    JmcomicText = None  # type: ignore[assignment]
    JmImageTool = None  # type: ignore[assignment]
    JmPhotoDetail = object  # type: ignore[misc,assignment]

from ..config import PluginConfig
from ..data import (
    FileContent,
    ImageContent,
    MediaContent,
    ParseResult,
    Platform,
    SendGroup,
)
from ..download import Downloader
from ..exception import ParseException
from .base import BaseParser, handle

JM_BASE = "https://18comic.vip"
JM_IMAGE_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": f"{JM_BASE}/",
}


def imgs_to_pdf(img_paths: list[Path], save_path: Path) -> Path:
    """将按章节顺序排好的图片合成为 PDF。"""
    if not img_paths:
        raise ParseException("漫画图片列表为空")

    images: list[Image.Image] = []
    try:
        for img_path in img_paths:
            with Image.open(img_path) as img:
                images.append(img.convert("RGB"))
        images[0].save(
            save_path,
            "PDF",
            save_all=True,
            append_images=images[1:],
        )
    finally:
        for img in images:
            img.close()
    return save_path


def blur_image(image_path: Path, radius: int = 5) -> Path:
    """对图片施加高斯模糊，返回模糊后的新文件。"""
    from PIL import ImageFilter

    output_path = image_path.parent / f"{image_path.stem}_blur{image_path.suffix}"
    with Image.open(image_path) as img:
        img.filter(ImageFilter.GaussianBlur(radius=radius)).save(output_path)
    return output_path


class JMComicParser(BaseParser):

    platform: ClassVar[Platform] = Platform(name="jmcomic", display_name="JMComic")

    def __init__(self, config: PluginConfig, downloader: Downloader):
        super().__init__(config, downloader)
        self.mycfg = config.parser.jmcomic

    @property
    def proxy(self) -> str | None:
        raw_proxy = super().proxy
        if isinstance(raw_proxy, str):
            return raw_proxy.strip() or None
        return None

    def _get_option(self) -> "JmOption":
        """创建默认 option，并显式覆盖系统代理配置。"""
        option = JmOption.default()
        meta_data = option.client.postman.meta_data
        meta_data["proxies"] = self.proxy
        return option

    @staticmethod
    def _normalize_comic_id(raw_id: str) -> str:
        return raw_id.lstrip("0")

    @staticmethod
    def _decode_image(
        img_url: str,
        scramble_id: str,
        image_path: Path,
    ) -> Path:
        """解密禁漫下载下来的纵向错位图片。"""
        split_num = JmImageTool.get_num_by_url(scramble_id, img_url)
        save_path = image_path.parent / f"{image_path.stem}_decode{image_path.suffix}"
        if save_path.exists() and save_path.stat().st_size > 0:
            return save_path
        with Image.open(image_path) as img_src:
            JmImageTool.decode_and_save(split_num, img_src, str(save_path))
        return save_path

    async def _download_page(self, photo) -> Path | None:
        try:
            raw_path = await self.downloader.download_img(
                photo.download_url,
                headers=JM_IMAGE_HEADERS,
                proxy=self.proxy,
            )
            return await asyncio.to_thread(
                self._decode_image,
                photo.img_url,
                photo.scramble_id,
                Path(raw_path),
            )
        except Exception as exc:
            logger.warning(f"[JMComic] 图片下载或解密失败 ({photo.img_url}): {exc}")
            return None

    async def _download_all_pages(self, photo_detail) -> list[Path]:
        """并发下载章节全部图片，并按页码保持返回顺序。"""
        semaphore = asyncio.Semaphore(16)

        async def worker(photo) -> Path | None:
            async with semaphore:
                return await self._download_page(photo)

        results = await asyncio.gather(
            *(worker(photo) for photo in photo_detail)
        )
        return [path for path in results if path is not None]

    async def _build_pdf(
        self,
        img_paths_task: asyncio.Task[list[Path]],
        comic_id: str,
    ) -> Path:
        paths = await img_paths_task
        if not paths:
            raise ParseException("漫画图片下载失败，未能获取到任何有效图片")
        pdf_path = self.cfg.cache_dir / f"jmcomic_{comic_id}.pdf"
        await asyncio.to_thread(imgs_to_pdf, paths, pdf_path)
        logger.info(
            f"[JMComic] 已合成 PDF: {pdf_path.name}（{len(paths)} 页）"
        )
        return pdf_path

    async def _build_cover(
        self,
        cover_url: str,
        nsfw: str,
    ) -> list[MediaContent]:
        if nsfw == "ignore":
            return []
        try:
            cover_path = await self.downloader.download_img(
                cover_url,
                headers=JM_IMAGE_HEADERS,
                proxy=self.proxy,
            )
        except Exception as exc:
            logger.warning(f"[JMComic] 封面下载失败: {exc}")
            return []
        if nsfw == "blur":
            cover_path = await asyncio.to_thread(blur_image, Path(cover_path))
        return [ImageContent(Path(cover_path))]

    @handle(
        "18comic.vip/photo",
        r"18comic\.vip/(?:photo|album)/(?P<comic_id>\d{5,})",
    )
    @handle("18comic.vip/album", r"18comic\.vip/(?:photo|album)/(?P<comic_id>\d{5,})")
    @handle("jm", r"(?<![a-zA-Z])jm(?P<comic_id>\d+)")
    @handle("JM", r"(?<![a-zA-Z])JM(?P<comic_id>\d+)")
    @handle("Jm", r"(?<![a-zA-Z])Jm(?P<comic_id>\d+)")
    async def _parse(self, searched: Match[str]) -> ParseResult:
        comic_id = self._normalize_comic_id(searched.group("comic_id"))
        if not comic_id:
            return self.result(extra={"info": "JM 号不能为空"})
        if JmOption is None:
            raise ParseException(
                "[JMComic] 未安装 jmcomic 依赖库，请先运行: pip install jmcomic"
            )

        option = self._get_option()
        async with option.new_jm_async_client(proxies=self.proxy) as client:
            try:
                album_detail = await client.get_album_detail(comic_id)
            except MissingAlbumPhotoException:
                return self.result(extra={"info": "当前 JM 号不存在"})
            except JmcomicException as exc:
                raise ParseException(f"获取 JM 详情失败: {exc}") from exc

            try:
                photo_detail = await client.get_photo_detail(comic_id)
            except MissingAlbumPhotoException:
                return self.result(extra={"info": "当前 JM 章节不存在"})
            except JmcomicException as exc:
                raise ParseException(f"获取 JM 章节失败: {exc}") from exc

        album_url = JmcomicText.format_album_url(comic_id)
        cover_url = JmcomicText.get_album_cover_url(comic_id)
        cover_contents = await self._build_cover(
            cover_url,
            self.mycfg.nsfw or "blur",
        )

        tags = ", ".join(f"#{tag}" for tag in album_detail.tags)
        text = (
            f"标题: {album_detail.name}\n"
            f"TAGS: {tags}\n"
            f"浏览: {album_detail.views}\n"
            f"点赞: {album_detail.likes}\n"
            f"描述: {album_detail.description}"
        )

        episode_count = len(album_detail.episode_list)
        extra_info = (
            f"共 {episode_count} 话，当前下载第 {photo_detail.sort} 话\n"
            f"漫画原链: {album_url}"
        )
        if episode_count > 1:
            extra_info += "\n若需解析其他章节请发送对应章节的 JM 号。"

        send_groups: list[SendGroup] = [
            SendGroup(contents=[], render_card=True, force_merge=False)
        ]

        page_count = len(photo_detail)
        send_mode = self.mycfg.image_send_mode or "pdf"
        max_page = self.mycfg.max_page or 0
        if send_mode != "ignore":
            if max_page > 0 and page_count > max_page:
                extra_info += f"\n当前章节 {page_count} 页，超过最大页数 {max_page}，已跳过下载。"
            else:
                img_paths_task = asyncio.create_task(
                    self._download_all_pages(photo_detail)
                )
                if send_mode == "pdf":
                    pdf_task = asyncio.create_task(
                        self._build_pdf(img_paths_task, comic_id)
                    )
                    send_groups.append(
                        SendGroup(
                            contents=[
                                FileContent(pdf_task, name=f"jmcomic_{comic_id}.pdf")
                            ],
                            render_card=False,
                            force_merge=False,
                        )
                    )
                elif send_mode == "merge":
                    img_paths = await img_paths_task
                    if not img_paths:
                        raise ParseException(
                            "漫画图片下载失败，未能获取到任何有效图片"
                        )
                    send_groups.append(
                        SendGroup(
                            contents=[ImageContent(path) for path in img_paths],
                            render_card=False,
                            force_merge=True,
                        )
                    )
                else:
                    img_paths_task.cancel()

        return self.result(
            title=album_detail.name,
            author=self.create_author(", ".join(album_detail.authors)),
            text=text,
            url=album_url,
            contents=cover_contents,
            send_groups=send_groups,
            extra={"info": extra_info},
        )
