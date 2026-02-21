"""Detect currently playing media via MPRIS2 D-Bus interface."""

from __future__ import annotations

import re
from dataclasses import dataclass

import dbus


MPRIS_PREFIX = "org.mpris.MediaPlayer2."
MPRIS_PATH = "/org/mpris/MediaPlayer2"
PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"
PROPS_IFACE = "org.freedesktop.DBus.Properties"


@dataclass
class NowPlaying:
    """Information about the currently playing track."""

    title: str
    artist: str
    album: str
    duration_us: int  # microseconds
    position_us: int  # microseconds
    player_name: str
    is_playing: bool

    @property
    def duration_s(self) -> float:
        return self.duration_us / 1_000_000

    @property
    def position_s(self) -> float:
        return self.position_us / 1_000_000


def _get_bus() -> dbus.SessionBus:
    return dbus.SessionBus()


def list_players() -> list[str]:
    """Return a list of running MPRIS2 player bus names."""
    bus = _get_bus()
    names: list[str] = bus.list_names()
    return [n for n in names if n.startswith(MPRIS_PREFIX)]


def _friendly_name(bus_name: str) -> str:
    """Extract the human-friendly player name from the bus name."""
    name = bus_name.removeprefix(MPRIS_PREFIX)
    # Remove instance suffix like '.instance12345'
    name = re.sub(r"\.instance\d+$", "", name)
    return name.capitalize()


def get_now_playing(player_bus: str | None = None) -> NowPlaying | None:
    """
    Get the currently playing track from an MPRIS2 player.

    If *player_bus* is ``None``, the first active player found is used.
    Returns ``None`` when nothing is playing.
    """
    bus = _get_bus()

    if player_bus is None:
        players = list_players()
        if not players:
            return None
        # Prefer a player that is actually playing
        for p in players:
            info = _query_player(bus, p)
            if info and info.is_playing:
                return info
        # Fall back to first player even if paused
        return _query_player(bus, players[0])

    return _query_player(bus, player_bus)


def _query_player(bus: dbus.SessionBus, bus_name: str) -> NowPlaying | None:
    try:
        proxy = bus.get_object(bus_name, MPRIS_PATH)
        props = dbus.Interface(proxy, PROPS_IFACE)

        metadata = props.Get(PLAYER_IFACE, "Metadata")
        status = str(props.Get(PLAYER_IFACE, "PlaybackStatus"))
        position = int(props.Get(PLAYER_IFACE, "Position"))  # microseconds

        title = str(metadata.get("xesam:title", ""))
        artists = metadata.get("xesam:artist", [])
        artist = str(artists[0]) if artists else ""
        album = str(metadata.get("xesam:album", ""))
        duration = int(metadata.get("mpris:length", 0))

        if not title:
            return None

        return NowPlaying(
            title=title,
            artist=artist,
            album=album,
            duration_us=duration,
            position_us=position,
            player_name=_friendly_name(bus_name),
            is_playing=(status == "Playing"),
        )
    except dbus.DBusException:
        return None
