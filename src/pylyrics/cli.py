"""CLI entry point for pylyrics."""

from __future__ import annotations

import argparse
import sys
import time

from pylyrics.display import display_lyrics, display_pipe, display_waiting
from pylyrics.lyrics import fetch_lyrics
from pylyrics.media import get_now_playing, list_players

_DIM = "\033[2m"
_BOLD = "\033[1m"
_RESET = "\033[0m"


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="pylyrics",
        description="Display synced lyrics in the terminal for the currently playing song.",
    )
    parser.add_argument(
        "--player",
        type=str,
        default=None,
        help="MPRIS2 bus name of the player to use (e.g. org.mpris.MediaPlayer2.spotify)",
    )
    parser.add_argument(
        "--list-players",
        action="store_true",
        help="List available MPRIS2 players and exit.",
    )
    parser.add_argument(
        "--pipe",
        action="store_true",
        help="Plain text mode: output only the current lyric line to stdout (pipeable).",
    )
    args = parser.parse_args()

    if args.list_players:
        players = list_players()
        if not players:
            print("No MPRIS2 players found.")
        else:
            print(f"{_BOLD}Available players:{_RESET}")
            for p in players:
                print(f"  • {p}")
        return

    if args.pipe:
        try:
            while True:
                info = get_now_playing(args.player)
                if info is None:
                    time.sleep(2)
                    continue

                lyrics = fetch_lyrics(
                    title=info.title,
                    artist=info.artist,
                    album=info.album,
                    duration_s=info.duration_s,
                )
                if lyrics:
                    display_pipe(lyrics, info)
                else:
                    current = (info.title, info.artist)
                    while True:
                        time.sleep(2)
                        new = get_now_playing(args.player)
                        if new is None or (new.title, new.artist) != current:
                            break
        except KeyboardInterrupt:
            sys.exit(0)
        return

    # Default mode: wait for a player, then enter the live display
    info = get_now_playing(args.player)
    while info is None:
        display_waiting()
        time.sleep(2)
        info = get_now_playing(args.player)

    print(f"{_DIM}Fetching lyrics…{_RESET}")
    lyrics = fetch_lyrics(
        title=info.title,
        artist=info.artist,
        album=info.album,
        duration_s=info.duration_s,
    )

    try:
        display_lyrics(lyrics if lyrics else None, info, args.player)
    except KeyboardInterrupt:
        print(f"\n{_DIM}Bye!{_RESET}")
        sys.exit(0)


if __name__ == "__main__":
    main()
