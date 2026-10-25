"""JMComic 解析器"""

import asyncio
from pathlib import Path
from re import Match
from typing import ClassVar

from ..config import PluginConfig
from ..data import (
    Platform,
)
from ..download import Downloader
from .base import BaseParser


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

    def _get_option(self):
        """创建默认 option，并显式覆盖系统代理配置。"""
        pass

    @staticmethod
    def _normalize_comic_id(raw_id: str) -> str:
        return raw_id.lstrip("0")

    @staticmethod
    def _decode_image(
        img_url: str,
        scramble_id: str,
        image_path: Path,
    ):
        pass

    async def _download_page(self, photo):
        pass

    async def _download_all_pages(self, photo_detail):
        """并发下载章节全部图片，并按页码保持返回顺序。"""
        pass

    async def _build_pdf(self, img_paths_task: asyncio.Task[list[Path]], comic_id: str):
        pass

    async def _build_cover(self, cover_url: str, nsfw: str):
        pass

    async def _parse(self, searched: Match[str]):
        pass
