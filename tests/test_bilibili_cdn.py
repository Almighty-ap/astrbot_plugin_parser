from __future__ import annotations

import asyncio
import ssl
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from aiohttp import ClientConnectorCertificateError
from bilibili_api.video import (
    AudioStreamDownloadURL,
    MP4StreamDownloadURL,
    VideoStreamDownloadURL,
)

from core.exception import DownloadException
from core.parsers.bilibili import BilibiliParser


PRIMARY = "https://primary.bilivideo.com/video.m4s?token=secret"
BACKUP = "https://backup.bilivideo.com/video.m4s?token=secret"
AUDIO = "https://primary.bilivideo.com/audio.m4s"


def certificate_error():
    key = SimpleNamespace(host="primary.bilivideo.com", port=443, is_ssl=True)
    return ClientConnectorCertificateError(
        key, ssl.SSLCertVerificationError(1, "certificate has expired")
    )


class Response:
    def __init__(self, status=206, body=b"x"):
        self.status = status
        self.content = SimpleNamespace(read=AsyncMock(return_value=body))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class Session:
    closed = False

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return response


class BilibiliCDNTests(unittest.IsolatedAsyncioTestCase):
    def parser(self, responses, *, block_pcdn=False):
        parser = BilibiliParser.__new__(BilibiliParser)
        parser.cfg = SimpleNamespace(common_timeout=3, proxy=None)
        parser.mycfg = SimpleNamespace(block_pcdn=block_pcdn)
        parser.headers = {"Referer": "https://www.bilibili.com/"}
        parser._session = Session(responses)
        parser.video_quality = Mock()
        parser.video_codecs = []
        return parser

    def video_stream(self, url=PRIMARY, backups=None):
        return Mock(
            spec=VideoStreamDownloadURL,
            url=url,
            backup_url=backups or [],
            video_quality=SimpleNamespace(name="_360P"),
            video_codecs="avc1",
        )

    async def extract(self, parser, streams, data=None, **kwargs):
        video = SimpleNamespace(
            get_download_url=AsyncMock(return_value=data or {"dash": {"video": []}})
        )
        with patch("bilibili_api.video.VideoDownloadURLDataDetecter") as detector:
            detector.return_value.detect_best_streams.return_value = streams
            return await parser.extract_download_urls(video=video, **kwargs)

    async def test_dash_certificate_failure_uses_backup(self):
        response = Response()
        parser = self.parser({PRIMARY: certificate_error(), BACKUP: response})
        video_url, audio_url = await self.extract(
            parser, [self.video_stream(backups=[BACKUP]), None]
        )
        self.assertEqual((video_url, audio_url), (BACKUP, None))
        self.assertEqual([url for url, _ in parser.session.calls], [PRIMARY, BACKUP])
        for _, kwargs in parser.session.calls:
            self.assertEqual(kwargs["headers"]["Range"], "bytes=0-0")
            self.assertNotIn("ssl", kwargs)
        response.content.read.assert_awaited_once_with(1)

    async def test_working_primary_does_not_request_backup(self):
        response = Response(status=200)
        parser = self.parser({PRIMARY: response})
        result = await self.extract(parser, [self.video_stream(backups=[BACKUP]), None])
        self.assertEqual(result, (PRIMARY, None))
        self.assertEqual(len(parser.session.calls), 1)
        response.content.read.assert_awaited_once_with(1)

    async def test_dash_backups_are_read_from_raw_playurl(self):
        audio_backup = "https://backup.bilivideo.com/audio.m4s"
        parser = self.parser(
            {
                PRIMARY: certificate_error(),
                BACKUP: Response(),
                AUDIO: certificate_error(),
                audio_backup: Response(),
            }
        )
        video = self.video_stream()
        del video.backup_url
        audio = Mock(
            spec=AudioStreamDownloadURL,
            url=AUDIO,
            audio_quality=SimpleNamespace(name="_192K"),
        )
        data = {
            "dash": {
                "video": [{"base_url": PRIMARY, "backup_url": [BACKUP]}],
                "audio": [{"baseUrl": AUDIO, "backupUrl": [audio_backup]}],
            }
        }
        self.assertEqual(
            await self.extract(parser, [video, audio], data), (BACKUP, audio_backup)
        )

    async def test_audio_only_does_not_probe_unavailable_video(self):
        parser = self.parser({AUDIO: Response()})
        audio = Mock(
            spec=AudioStreamDownloadURL,
            url=AUDIO,
            backup_url=[],
            audio_quality=SimpleNamespace(name="_192K"),
        )
        self.assertEqual(
            await self.extract(parser, [self.video_stream(), audio], audio_only=True),
            (PRIMARY, AUDIO),
        )
        self.assertEqual([url for url, _ in parser.session.calls], [AUDIO])

    async def test_bm_route_requests_audio_only(self):
        parser = self.parser({})
        parser.extract_download_urls = AsyncMock(return_value=(PRIMARY, AUDIO))
        parser.create_audio_content = Mock(return_value=Mock())
        parser.result = Mock()
        searched = Mock()
        searched.group.side_effect = lambda key: "BV1ispv6pEfJ" if key == "bvid" else None
        await parser._parse_bv_bm(searched)
        parser.extract_download_urls.assert_awaited_once_with(
            bvid="BV1ispv6pEfJ", page_index=0, audio_only=True
        )

    async def test_audio_can_fall_back_independently(self):
        audio_backup = "https://backup.bilivideo.com/audio.m4s"
        parser = self.parser(
            {PRIMARY: Response(), AUDIO: certificate_error(), audio_backup: Response()}
        )
        audio = Mock(
            spec=AudioStreamDownloadURL,
            url=AUDIO,
            backup_url=[audio_backup],
            audio_quality=SimpleNamespace(name="_192K"),
        )
        result = await self.extract(parser, [self.video_stream(), audio])
        self.assertEqual(result, (PRIMARY, audio_backup))

    async def test_mp4_uses_backup_from_raw_durl(self):
        parser = self.parser({PRIMARY: certificate_error(), BACKUP: Response()})
        stream = MP4StreamDownloadURL(url=PRIMARY)
        data = {"durl": [{"url": PRIMARY, "backup_url": [BACKUP]}]}
        self.assertEqual(await self.extract(parser, [stream], data), (BACKUP, None))

    async def test_bad_status_empty_body_and_timeout_try_next_node(self):
        second = "https://second.bilivideo.com/video.m4s"
        third = "https://third.bilivideo.com/video.m4s"
        parser = self.parser(
            {
                PRIMARY: Response(status=403),
                second: Response(body=b""),
                third: asyncio.TimeoutError(),
                BACKUP: Response(),
            }
        )
        stream = self.video_stream(backups=[second, third, BACKUP])
        self.assertEqual(await self.extract(parser, [stream, None]), (BACKUP, None))

    async def test_no_valid_certificate_raises_without_disabling_tls(self):
        error = certificate_error()
        parser = self.parser({PRIMARY: error})
        with self.assertRaises(DownloadException) as raised:
            await self.extract(parser, [self.video_stream(backups=[PRIMARY]), None])
        self.assertIs(raised.exception.__cause__, error)
        self.assertEqual(len(parser.session.calls), 1)

    async def test_pcdn_filter_keeps_clean_backup_preference(self):
        pcdn = "https://node.mcdn.bilivideo.com/video.m4s"
        parser = self.parser({BACKUP: Response()}, block_pcdn=True)
        stream = self.video_stream(url=pcdn, backups=[PRIMARY, BACKUP])
        parser.session.responses[PRIMARY] = certificate_error()
        self.assertEqual(await self.extract(parser, [stream, None]), (BACKUP, None))
        self.assertNotIn(pcdn, [url for url, _ in parser.session.calls])

    async def test_all_pcdn_candidates_keep_existing_fallback(self):
        pcdn = "https://node.mcdn.bilivideo.com/video.m4s"
        parser = self.parser({pcdn: Response()}, block_pcdn=True)
        self.assertEqual(
            await self.extract(parser, [self.video_stream(url=pcdn), None]),
            (pcdn, None),
        )

    async def test_http_backup_is_upgraded_and_deduplicated(self):
        parser = self.parser({PRIMARY: certificate_error(), BACKUP: Response()})
        stream = self.video_stream(backups=[BACKUP.replace("https:", "http:"), BACKUP])
        self.assertEqual(await self.extract(parser, [stream, None]), (BACKUP, None))
        self.assertEqual([url for url, _ in parser.session.calls], [PRIMARY, BACKUP])

    async def test_upos_mirrorcosov_deprioritized_and_fallback_to_mirrorali(self):
        cosov_url = "https://upos-sz-mirrorcosov.bilivideo.com/video.m4s"
        ali_url = "https://upos-sz-mirrorali.bilivideo.com/video.m4s"
        parser = self.parser({ali_url: Response(status=206)})
        stream = self.video_stream(url=cosov_url)
        self.assertEqual(await self.extract(parser, [stream, None]), (ali_url, None))
        self.assertIn(ali_url, [url for url, _ in parser.session.calls])


if __name__ == "__main__":
    unittest.main()
