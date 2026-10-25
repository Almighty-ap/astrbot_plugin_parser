"""Disabled nhentai parser compatibility stub.

The content parser is intentionally disabled for marketplace safety review.
Public names and method signatures remain available for compatibility, but no
network requests, media downloads, PDF generation, or message handlers are
provided by this module.
"""

from pathlib import Path
from re import Match
from typing import Any, ClassVar

from ..config import PluginConfig
from ..data import Platform
from ..download import Downloader
from .base import BaseParser


def imgs_to_pdf(img_paths: list[Path], save_path: Path):
    """Keep the former PDF helper interface without performing any work."""
    pass


def blur_image(image_path: Path, radius: int = 25):
    """Keep the former image helper interface without performing any work."""
    pass


def group_tags(tags: list[dict[str, Any]]):
    """Keep the former tag helper interface without performing any work."""
    pass


def pick_title(data: dict[str, Any]):
    """Keep the former title helper interface without performing any work."""
    pass


def build_text(data: dict[str, Any], grouped: dict[str, list[str]]):
    """Keep the former text helper interface without performing any work."""
    pass


class NhentaiParser(BaseParser):
    """Disabled nhentai parser retained for import compatibility."""

    platform: ClassVar[Platform] = Platform(name="nhentai", display_name="nhentai")

    def __init__(self, config: PluginConfig, downloader: Downloader):
        super().__init__(config, downloader)
        self.mycfg = config.parser.nhentai

    async def _get_json(
        self, url: str, *, not_found: str = "nhentai endpoint unavailable"
    ) -> Any:
        """Keep the former request interface disabled."""
        pass

    async def _get_servers(self):
        """Keep the former image-server interface disabled."""
        pass

    async def _get_gallery(self, gid: str):
        """Keep the former gallery interface disabled."""
        pass

    async def _page_urls(self, data: dict[str, Any]):
        """Keep the former page URL interface disabled."""
        pass

    async def _build_cover(
        self, data: dict[str, Any], blur: bool
    ):
        """Keep the former cover interface disabled."""
        pass

    async def _build_pdf(self, gid: str, img_urls: list[str]) :
        """Keep the former PDF interface disabled."""
        pass

    async def _parse_gallery(self, searched: Match[str]):
        """Keep the former parser entry point disabled."""
        pass
