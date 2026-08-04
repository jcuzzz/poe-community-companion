"""Parse video-clip URLs into embeddable players for proof.

Players clip on Twitch/YouTube/Streamable; this maps a pasted watch URL to an
embed URL we can drop into an <iframe>. Unsupported hosts return None so the
form can reject them with a clear message. See docs/design/ladder-tracking.md
sibling — proofs doc lives inline here.
"""

from __future__ import annotations

import re
import urllib.parse

from django.conf import settings

_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
_TWITCH_CLIP_HOSTS = {"clips.twitch.tv", "www.twitch.tv", "twitch.tv", "m.twitch.tv"}
_STREAMABLE_HOSTS = {"streamable.com", "www.streamable.com"}

_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _site_host() -> str:
    """Bare host of the deployment, needed as Twitch's embed `parent`."""
    netloc = urllib.parse.urlparse(getattr(settings, "SITE_BASE_URL", "")).netloc
    return (netloc.split("@")[-1].split(":")[0] or "localhost").strip()


def _youtube_id(u: urllib.parse.ParseResult) -> str | None:
    host = u.netloc.lower()
    if host == "youtu.be":
        vid = u.path.lstrip("/").split("/")[0]
    elif u.path.startswith(("/shorts/", "/embed/")):
        vid = u.path.split("/")[2]
    else:
        vid = urllib.parse.parse_qs(u.query).get("v", [""])[0]
    return vid if vid and _ID_RE.match(vid) else None


def _twitch_slug(u: urllib.parse.ParseResult) -> str | None:
    host = u.netloc.lower()
    parts = [p for p in u.path.split("/") if p]
    if host == "clips.twitch.tv" and parts:
        slug = parts[0]
    elif "clip" in parts:  # twitch.tv/<channel>/clip/<slug>
        slug = parts[parts.index("clip") + 1] if parts.index("clip") + 1 < len(parts) else ""
    else:
        return None
    return slug if slug and _ID_RE.match(slug) else None


def _streamable_id(u: urllib.parse.ParseResult) -> str | None:
    parts = [p for p in u.path.split("/") if p]
    # streamable.com/<id> or streamable.com/e/<id>
    sid = parts[1] if len(parts) >= 2 and parts[0] == "e" else (parts[0] if parts else "")
    return sid if sid and _ID_RE.match(sid) else None


def video_embed(url: str) -> dict | None:
    """Return {provider, embed_url, watch_url} for a supported clip URL, else None."""
    if not url:
        return None
    u = urllib.parse.urlparse(url.strip())
    if u.scheme not in ("http", "https") or not u.netloc:
        return None
    host = u.netloc.lower()

    if host in _YOUTUBE_HOSTS:
        vid = _youtube_id(u)
        if vid:
            return {
                "provider": "youtube",
                "embed_url": f"https://www.youtube.com/embed/{vid}",
                "watch_url": f"https://www.youtube.com/watch?v={vid}",
            }
    elif host in _TWITCH_CLIP_HOSTS:
        slug = _twitch_slug(u)
        if slug:
            return {
                "provider": "twitch",
                "embed_url": f"https://clips.twitch.tv/embed?clip={slug}&parent={_site_host()}",
                "watch_url": f"https://clips.twitch.tv/{slug}",
            }
    elif host in _STREAMABLE_HOSTS:
        sid = _streamable_id(u)
        if sid:
            return {
                "provider": "streamable",
                "embed_url": f"https://streamable.com/e/{sid}",
                "watch_url": f"https://streamable.com/{sid}",
            }
    return None


def is_supported(url: str) -> bool:
    return video_embed(url) is not None


SUPPORTED_LABEL = "YouTube, Twitch clips, or Streamable"
