"""Pull captions / description / audio from YouTube, TikTok, Instagram, Facebook via yt-dlp."""
from __future__ import annotations

import glob
import html
import os
import re
import tempfile
from typing import Optional
from urllib.parse import urlparse

import httpx

from ..config import get_settings

VIDEO_HOSTS = ("youtube.com", "youtu.be", "tiktok.com", "instagram.com", "facebook.com", "fb.watch",
               "vimeo.com", "pinterest.com", "pin.it", "x.com", "twitter.com", "threads.net")
SOCIAL_HOSTS = VIDEO_HOSTS + ("linktr.ee", "amzn.to", "amazon.com", "bit.ly", "patreon.com", "spotify.com",
                              "apple.com", "ltk.app", "liketoknow.it", "shopmy.us")


def is_video_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in VIDEO_HOSTS)


def is_social(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in SOCIAL_HOSTS)


def _ydl_opts(extra: dict | None = None) -> dict:
    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True,
            "socket_timeout": 20}
    cookies = get_settings().ytdlp_cookies_file
    if cookies and os.path.exists(cookies):
        opts["cookiefile"] = cookies
    if extra:
        opts.update(extra)
    return opts


def _pick_track(tracks: dict, lang: Optional[str]) -> Optional[dict]:
    if not tracks:
        return None
    keys = list(tracks.keys())
    preferred = [k for k in keys if lang and k.split("-")[0] == lang] + \
                [k for k in keys if k.startswith("en")] + keys
    for k in preferred:
        formats = tracks.get(k) or []
        for ext in ("json3", "vtt", "srv1", "ttml"):
            for f in formats:
                if f.get("ext") == ext and f.get("url"):
                    return f
    return None


def _caption_text(fmt: dict) -> str:
    r = httpx.get(fmt["url"], timeout=20)
    r.raise_for_status()
    if fmt.get("ext") == "json3":
        data = r.json()
        words = []
        for ev in data.get("events", []):
            for seg in ev.get("segs") or []:
                words.append(seg.get("utf8", ""))
        text = "".join(words)
    else:
        lines, last = [], None
        for line in r.text.splitlines():
            line = line.strip()
            if not line or "-->" in line or line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")) or line.isdigit():
                continue
            line = html.unescape(re.sub(r"<[^>]+>", "", line))
            if line != last:
                lines.append(line)
            last = line
        text = " ".join(lines)
    return re.sub(r"\s+", " ", text).strip()


def video_info(url: str) -> dict:
    """Return title, description, thumbnail, captions text, duration, uploader."""
    import yt_dlp  # imported lazily: heavy

    with yt_dlp.YoutubeDL(_ydl_opts()) as ydl:
        info = ydl.extract_info(url, download=False)
    if info.get("_type") == "playlist" and info.get("entries"):
        info = next((e for e in info["entries"] if e), info)
    lang = info.get("language")
    captions = ""
    fmt = _pick_track(info.get("subtitles") or {}, lang) or _pick_track(info.get("automatic_captions") or {}, lang)
    if fmt:
        try:
            captions = _caption_text(fmt)
        except Exception:
            captions = ""
    return {
        "title": info.get("title") or info.get("fulltitle"),
        "description": info.get("description") or "",
        "thumbnail": info.get("thumbnail"),
        "duration": info.get("duration"),
        "uploader": info.get("uploader") or info.get("channel"),
        "captions": captions,
        "webpage_url": info.get("webpage_url") or url,
    }


def download_audio(url: str, max_minutes: int = 30) -> Optional[str]:
    """Download the audio track to a temp file for transcription. Caller deletes the dir."""
    import yt_dlp

    tmp = tempfile.mkdtemp(prefix="mise-audio-")
    opts = _ydl_opts({
        "skip_download": False,
        "format": "bestaudio[filesize<24M]/bestaudio/worst[filesize<24M]/worst",
        "outtmpl": os.path.join(tmp, "audio.%(ext)s"),
        "match_filter": lambda i, *a, **k: "too long" if (i.get("duration") or 0) > max_minutes * 60 else None,
    })
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])
    files = glob.glob(os.path.join(tmp, "audio.*"))
    return files[0] if files else None
