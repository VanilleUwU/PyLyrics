"""Fetch synced (LRC) lyrics from LRCLIB."""

from __future__ import annotations

import re
from dataclasses import dataclass

import requests


LRCLIB_API = "https://lrclib.net/api"
USER_AGENT = "pylyrics/1.0.0 (https://github.com/pylyrics)"


@dataclass
class LyricLine:
    """A single timed lyric line."""

    time_s: float  # seconds from start
    text: str

    def __repr__(self) -> str:
        mins, secs = divmod(self.time_s, 60)
        return f"[{int(mins):02d}:{secs:05.2f}] {self.text}"


def parse_lrc(lrc_text: str) -> list[LyricLine]:
    """
    Parse an LRC string into a sorted list of LyricLine objects.

    Supports the format ``[mm:ss.xx] text`` with optional hundredths.
    """
    pattern = re.compile(r"\[(\d{1,2}):(\d{2})(?:[.:](\d{1,3}))?\]\s*(.*)")
    lines: list[LyricLine] = []

    for raw_line in lrc_text.splitlines():
        m = pattern.match(raw_line.strip())
        if not m:
            continue
        minutes = int(m.group(1))
        seconds = int(m.group(2))
        frac_str = m.group(3) or "0"
        # Normalise fraction to milliseconds
        frac_str = frac_str.ljust(3, "0")[:3]
        frac = int(frac_str) / 1000
        time_s = minutes * 60 + seconds + frac
        text = m.group(4).strip()
        lines.append(LyricLine(time_s=time_s, text=text))

    lines.sort(key=lambda l: l.time_s)
    return lines


def fetch_lyrics(
    title: str,
    artist: str,
    album: str = "",
    duration_s: float | None = None,
) -> list[LyricLine] | None:
    """
    Fetch synced lyrics from LRCLIB.

    Returns a sorted list of ``LyricLine`` or ``None`` if not found.
    """
    headers = {"User-Agent": USER_AGENT}

    # Try the exact-match endpoint first
    params: dict[str, str | int] = {
        "track_name": title,
        "artist_name": artist,
    }
    if album:
        params["album_name"] = album
    if duration_s and duration_s > 0:
        params["duration"] = int(duration_s)

    try:
        resp = requests.get(f"{LRCLIB_API}/get", params=params, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            synced = data.get("syncedLyrics")
            if synced:
                return parse_lrc(synced)
            # Fall through to search if no synced lyrics on exact match
    except requests.RequestException:
        pass

    # Fall back to search endpoint
    search_params: dict[str, str] = {
        "track_name": title,
        "artist_name": artist,
    }
    try:
        resp = requests.get(
            f"{LRCLIB_API}/search", params=search_params, headers=headers, timeout=10
        )
        if resp.status_code == 200:
            results = resp.json()
            for result in results:
                synced = result.get("syncedLyrics")
                if synced:
                    return parse_lrc(synced)
    except requests.RequestException:
        pass

    return None
