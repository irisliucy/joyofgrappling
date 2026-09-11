"""fetch_captions(): YouTube caption fetch, no API key needed.

Returns None on any failure (disabled, none found, etc.) per the tool's
fallback contract -- the caller falls back to title+description extraction
with low_confidence.

YouTube blocks/rate-limits this unofficial endpoint from datacenter IPs
(observed: every caption fetch failing on Render while the same videos
succeeded from a residential/local IP). If proxy settings are present
(Webshare-specific or a generic HTTP/HTTPS proxy URL, see config.py),
route through that instead.
"""
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.proxies import GenericProxyConfig, WebshareProxyConfig

from . import config
from .schemas import Caption, CaptionSegment


def _build_api() -> YouTubeTranscriptApi:
    if config.WEBSHARE_PROXY_USERNAME and config.WEBSHARE_PROXY_PASSWORD:
        proxy_config = WebshareProxyConfig(
            proxy_username=config.WEBSHARE_PROXY_USERNAME,
            proxy_password=config.WEBSHARE_PROXY_PASSWORD,
        )
        return YouTubeTranscriptApi(proxy_config=proxy_config)
    if config.PROXY_HTTP_URL or config.PROXY_HTTPS_URL:
        proxy_config = GenericProxyConfig(
            http_url=config.PROXY_HTTP_URL or None,
            https_url=config.PROXY_HTTPS_URL or None,
        )
        return YouTubeTranscriptApi(proxy_config=proxy_config)
    return YouTubeTranscriptApi()


def fetch_captions(video_id: str, source: str = "youtube") -> Caption | None:
    if source != "youtube":
        return None
    try:
        fetched = _build_api().fetch(video_id)
    except Exception:
        return None

    segments = [
        CaptionSegment(
            start_seconds=snippet.start,
            end_seconds=snippet.start + snippet.duration,
            text=snippet.text,
        )
        for snippet in fetched
    ]
    if not segments:
        return None
    return Caption(video_id=video_id, language=fetched.language_code or "unknown", segments=segments)
