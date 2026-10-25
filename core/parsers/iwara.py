"""Disabled Iwara parser compatibility stub.

The content parser is intentionally disabled for marketplace safety review.
Public names and method signatures remain available for compatibility, but no
network requests, media downloads, image processing, or message handlers are
provided by this module.
"""

from pathlib import Path
from re import Match
from typing import ClassVar

from ..config import PluginConfig
from ..data import Platform
from ..download import Downloader
from .base import BaseParser


class api:
    """Retain the former Iwara API namespace without network functionality."""

    cookie = ""
    proxy: str | None = None

    @staticmethod
    def _get_iwara_xversion(fileURL: str):
        """Keep the former URL-signing interface disabled."""
        pass

    @staticmethod
    async def iwaraID_Get_videoInfo(video_id: str):
        """Keep the former video metadata interface disabled."""
        pass

    @staticmethod
    async def fileURL_get_urlInfo(fileURL: str) :
        """Keep the former video URL interface disabled."""
        pass

    @staticmethod
    async def urlInfo_Get_videoURL(urlInfo: list | dict, quality: str):
        """Keep the former video quality interface disabled."""
        pass

    @staticmethod
    def videoInfo_Get_Thumbnail(info: dict):
        """Keep the former thumbnail interface disabled."""
        pass

    @staticmethod
    def auto_blur_video_thumbnail(
        video_thumbnail: Path, rating: str, config: str
    ):
        """Keep the former thumbnail processing interface disabled."""
        pass

    @staticmethod
    def _blur(
        image_path: str | Path, output_path: str | Path | None = None, radius: int = 20
    ):
        """Keep the former blur interface disabled."""
        pass

    @staticmethod
    async def IMG_iwaraID_Get_imageInfo(image_id: str):
        """Keep the former image metadata interface disabled."""
        pass


class IwaraParser(BaseParser):
    """Disabled Iwara parser retained for import compatibility."""

    platform: ClassVar[Platform] = Platform(name="iwara", display_name="iwara")

    def __init__(self, config: PluginConfig, downloader: Downloader):
        super().__init__(config, downloader)
        self.mycfg = config.parser.iwara
        api.cookie = self.mycfg.cookies if self.mycfg.cookies else ""
        api.proxy = self.proxy

    async def _parse(self, searched: Match[str]):
        """Keep the former video parser entry point disabled."""
        pass

    async def _parse_image(self, searched: Match[str]):
        """Keep the former image parser entry point disabled."""
        pass
