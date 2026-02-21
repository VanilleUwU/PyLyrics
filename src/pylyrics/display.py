"""Render synced lyrics in the terminal using ANSI escape codes.

Text-only rendering with:
  • Synchronized output (\033[?2026h / l) for flicker-free updates
  • Differential updates — only changed lines redrawn
  • 30 fps with smooth scroll (linear interpolation, 2 rows per lyric)
  • SIGWINCH for instant resize
  • Basic 3/4-bit ANSI colours (always respects terminal theme)
  • Raw terminal mode (no echo)
"""

from __future__ import annotations

import io
import os
import signal
import sys
import termios
import time
import tty

from pylyrics.lyrics import LyricLine, fetch_lyrics
from pylyrics.media import NowPlaying, get_now_playing

# ── ANSI escape helpers ──────────────────────────────────────────────────────

_ESC = "\033["
_RESET = f"{_ESC}0m"
_BOLD = f"{_ESC}1m"
_DIM = f"{_ESC}2m"

_HIDE_CURSOR = f"{_ESC}?25l"
_SHOW_CURSOR = f"{_ESC}?25h"
_CLEAR = f"{_ESC}2J{_ESC}H"
_HOME = f"{_ESC}H"
_EL = f"{_ESC}K"  # erase to end of line

_SYNC_START = "\033[?2026h"
_SYNC_END = "\033[?2026l"

# Foreground – basic 3/4-bit (terminal theme)
_FG_YELLOW = f"{_ESC}33m"
_FG_BLUE = f"{_ESC}34m"
_FG_MAGENTA = f"{_ESC}35m"
_FG_CYAN = f"{_ESC}36m"
_FG_WHITE = f"{_ESC}37m"
_FG_BR_BLACK = f"{_ESC}90m"
_FG_BR_WHITE = f"{_ESC}97m"

# Background
_BG_BLUE = f"{_ESC}44m"

# ── Frame timing ─────────────────────────────────────────────────────────────

_POLL_DT = 0.05  # seconds between polls


# ── Terminal helpers ─────────────────────────────────────────────────────────

def _move(row: int, col: int) -> str:
    return f"{_ESC}{row};{col}H"


def _term_size() -> tuple[int, int]:
    """Return (columns, lines)."""
    try:
        sz = os.get_terminal_size()
        return sz.columns, sz.lines
    except OSError:
        return 80, 24


# ── Styles ───────────────────────────────────────────────────────────────────

def _active(text: str, w: int) -> str:
    return f"{_BOLD}{_BG_BLUE}{_FG_BR_WHITE}{text.center(w)}{_RESET}{_EL}"


_GRAD = [
    lambda t: f"{_BOLD}{_FG_WHITE}{t}{_RESET}{_EL}",
    lambda t: f"{_FG_WHITE}{t}{_RESET}{_EL}",
    lambda t: f"{_FG_CYAN}{t}{_RESET}{_EL}",
    lambda t: f"{_FG_BLUE}{t}{_RESET}{_EL}",
    lambda t: f"{_FG_BR_BLACK}{t}{_RESET}{_EL}",
    lambda t: f"{_DIM}{_FG_BR_BLACK}{t}{_RESET}{_EL}",
]


def _styled_line(text: str, dist: float) -> str:
    d = max(0, int(round(dist)) - 1)
    return _GRAD[min(d, len(_GRAD) - 1)](text)


# ── Pipe mode ────────────────────────────────────────────────────────────────

def display_pipe(lines: list[LyricLine], initial_info: NowPlaying) -> None:
    interrupted = False

    def _handler(sig, frame):
        nonlocal interrupted
        interrupted = True

    old_handler = signal.signal(signal.SIGINT, _handler)
    try:
        previous_idx = -1
        while not interrupted:
            now = get_now_playing()
            if now is None:
                time.sleep(1)
                continue
            if now.title != initial_info.title or now.artist != initial_info.artist:
                return
            if not now.is_playing:
                time.sleep(0.3)
                continue
            active_idx = _find_active_line(lines, now.position_s)
            if active_idx != previous_idx:
                text = lines[active_idx].text
                if text:
                    print(text, flush=True)
                previous_idx = active_idx
            time.sleep(0.05)
    finally:
        signal.signal(signal.SIGINT, old_handler)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _format_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


def _find_active_line(lines: list[LyricLine], position_s: float) -> int:
    lo, hi, result = 0, len(lines) - 1, 0
    while lo <= hi:
        mid = (lo + hi) // 2
        if lines[mid].time_s <= position_s:
            result = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return result


def _center(text: str, width: int) -> str:
    if len(text) >= width:
        return text[:width]
    return " " * ((width - len(text)) // 2) + text


# ── Frame builders ───────────────────────────────────────────────────────────

def _build_frame(
    lines: list[LyricLine],
    active_idx: int,
    now: NowPlaying,
    w: int,
    h: int,
) -> list[str]:
    rows: list[str] = []

    # Header
    pos_str = _format_time(now.position_s)
    dur_str = _format_time(now.duration_s) if now.duration_s > 0 else "?:??"
    header_plain = f"{now.title} — {now.artist}  {pos_str} / {dur_str}"
    pad = max(0, (w - len(header_plain)) // 2)
    rows.append(
        " " * pad
        + f"{_BOLD}{_FG_MAGENTA}{now.title}{_RESET}"
        + f"{_FG_BR_BLACK} — {_RESET}"
        + f"{_FG_CYAN}{now.artist}{_RESET}"
        + f"{_FG_YELLOW}  {pos_str} / {dur_str}{_RESET}{_EL}"
    )
    rows.append(f"{_EL}")

    # Lyrics area — active line centred
    available = h - 3
    half = available // 2
    start_idx = active_idx - half

    for row in range(available):
        lyric_idx = start_idx + row

        if lyric_idx < 0 or lyric_idx >= len(lines):
            rows.append(f"{_EL}")
            continue

        lyric = lines[lyric_idx].text
        dist = abs(lyric_idx - active_idx)

        if dist == 0:
            rows.append(_active(lyric, w))
        else:
            rows.append(_styled_line(_center(lyric, w), dist))

    while len(rows) < h:
        rows.append(f"{_EL}")

    return rows


def _build_status(
    message: str, now: NowPlaying | None, w: int, h: int
) -> list[str]:
    rows: list[str] = []

    if now:
        pos_str = _format_time(now.position_s)
        dur_str = _format_time(now.duration_s) if now.duration_s > 0 else "?:??"
        header = f"{now.title} — {now.artist}  {pos_str} / {dur_str}"
    else:
        header = "pylyrics"

    rows.append(f"{_FG_BR_BLACK}{_center(header, w)}{_RESET}{_EL}")
    rows.append(f"{_EL}")

    available = h - 3
    mid = available // 2
    for i in range(available):
        if i == mid:
            rows.append(f"{_FG_BR_BLACK}{_center(message, w)}{_RESET}{_EL}")
        else:
            rows.append(f"{_EL}")

    while len(rows) < h:
        rows.append(f"{_EL}")

    return rows


# ── Differential writer ─────────────────────────────────────────────────────

def _write_diff(out, prev: list[str], cur: list[str], force: bool = False) -> None:
    buf = io.StringIO()
    buf.write(_SYNC_START)
    changed = False

    for row_idx, line in enumerate(cur):
        if force or row_idx >= len(prev) or prev[row_idx] != line:
            buf.write(_move(row_idx + 1, 1))
            buf.write(line)
            changed = True

    buf.write(_SYNC_END)

    if changed:
        out.write(buf.getvalue())
        out.flush()


# ── Main display loop ───────────────────────────────────────────────────────

def display_lyrics(
    lines: list[LyricLine] | None,
    initial_info: NowPlaying,
    player_bus: str | None = None,
) -> None:
    interrupted = False
    needs_redraw = True

    def _int_handler(sig, frame):
        nonlocal interrupted
        interrupted = True

    def _winch_handler(sig, frame):
        nonlocal needs_redraw
        needs_redraw = True

    old_int = signal.signal(signal.SIGINT, _int_handler)
    old_winch = signal.signal(signal.SIGWINCH, _winch_handler)

    current_lines = lines
    current_info = initial_info
    previous_idx = -1
    prev_frame: list[str] = []

    out = sys.stdout
    fd = sys.stdin.fileno()

    try:
        old_termios = termios.tcgetattr(fd)
        has_termios = True
    except termios.error:
        has_termios = False

    try:
        if has_termios:
            tty.setcbreak(fd)

        out.write(_HIDE_CURSOR)
        out.write(_CLEAR)
        out.flush()

        while not interrupted:
            time.sleep(_POLL_DT)

            w, h = _term_size()
            now = get_now_playing(player_bus)

            # No player
            if now is None:
                frame = _build_status("No media player detected.", None, w, h)
                _write_diff(out, prev_frame, frame, needs_redraw)
                prev_frame = frame
                needs_redraw = False
                continue

            # Song changed
            if now.title != current_info.title or now.artist != current_info.artist:
                current_info = now
                previous_idx = -1
                prev_frame = []

                frame = _build_status("Fetching lyrics…", now, w, h)
                _write_diff(out, prev_frame, frame, True)
                prev_frame = frame

                current_lines = fetch_lyrics(
                    title=now.title, artist=now.artist,
                    album=now.album, duration_s=now.duration_s,
                )
                if not current_lines:
                    current_lines = None
                needs_redraw = True
                continue

            # No lyrics
            if current_lines is None:
                frame = _build_status("No synced lyrics found.", now, w, h)
                _write_diff(out, prev_frame, frame, needs_redraw)
                prev_frame = frame
                needs_redraw = False
                continue

            active_idx = _find_active_line(current_lines, now.position_s)

            if active_idx != previous_idx or needs_redraw:
                frame = _build_frame(current_lines, active_idx, now, w, h)
                _write_diff(out, prev_frame, frame, needs_redraw)
                prev_frame = frame
                needs_redraw = False

            previous_idx = active_idx

    finally:
        out.write(_SHOW_CURSOR)
        out.write(_CLEAR)
        out.flush()
        if has_termios:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_termios)
        signal.signal(signal.SIGINT, old_int)
        signal.signal(signal.SIGWINCH, old_winch)


def display_waiting() -> None:
    print(f"\n{_FG_YELLOW}{_BOLD}No media player detected.{_RESET}")
    print(f"{_DIM}Start playing a song in any MPRIS2-compatible player.{_RESET}")
