"""`uv run voldemar-check`: can the bot actually play each source right now? No Discord needed.

Starts a private Lavalink on a spare port (a running bot is left alone), sends every test link
through the bot's own loading code (including the Spotify lookup), asks Lavalink to play it and
reports whether the audio stream opened. When songs stop playing, this tells you whether a source
such as YouTube is refusing, independent of Discord.

usage: voldemar-check [link or search ...]
"""

from __future__ import annotations

import asyncio
import dataclasses
import io
import logging
import secrets
import socket
import sys
from types import SimpleNamespace

import aiohttp
import wavelink

from voldemar.config import ConfigError, Settings, load_settings
from voldemar.lavalink_server import LOG_PATH, LavalinkError, LavalinkProcess
from voldemar.music import resolver
from voldemar.ui.formatting import short_error, truncate

log = logging.getLogger(__name__)

DEFAULT_CHECKS = [
    ("YouTube video", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
    ("YouTube Music", "https://music.youtube.com/watch?v=lYBUbBu4W08"),
    (
        "YouTube playlist",
        "https://www.youtube.com/playlist?list=PL0RwveZt5W5Nv9Ux0c36BWutcJHVfzrzY",
    ),
    ("Search", "Rick Astley Never Gonna Give You Up"),
    ("Spotify", "https://open.spotify.com/track/4PTG3Z6ehGkBFwjybzWkR8"),
    (
        "Apple Music",
        "https://music.apple.com/us/album/never-gonna-give-you-up/1773292758?i=1773293184",
    ),
    ("SoundCloud", "https://soundcloud.com/rick-astley-official/never-gonna-give-you-up"),
]
# YouTube tries each client in turn; when all refuse, the error arrives within a few seconds.
FAILURE_WINDOW = 15.0


@dataclasses.dataclass(slots=True)
class CheckResult:
    label: str
    ok: bool
    detail: str


class _Events:
    """Stands in for the Discord client: wavelink only needs `user.id` and `dispatch`."""

    def __init__(self) -> None:
        self.user = SimpleNamespace(id=1)  # any non-zero ID; Lavalink rejects 0 as missing
        self.queue: asyncio.Queue[tuple[str, object]] = asyncio.Queue()

    def dispatch(self, event: str, *args: object, **kwargs: object) -> None:
        if event in ("wavelink_track_exception", "wavelink_track_end") and args:
            self.queue.put_nowait((event, args[0]))


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def _check_one(
    node: wavelink.Node,
    events: _Events,
    session: aiohttp.ClientSession,
    guild_id: int,
    label: str,
    query: str,
) -> CheckResult:
    try:
        loaded = await resolver.load(query, 0, session)
    except resolver.LoadError as e:
        return CheckResult(label, False, f"couldn't load: {e}")
    entry = loaded.entries[0]
    playable = entry.playable or await resolver.resolve(entry)
    if playable is None:
        return CheckResult(label, False, "no matching song found on YouTube")

    while not events.queue.empty():
        events.queue.get_nowait()
    path = f"v4/sessions/{node.session_id}/players/{guild_id}"
    await node.send("PATCH", path=path, data={"track": {"encoded": playable.encoded}})
    result = CheckResult(label, True, truncate(playable.title, 60))
    loop = asyncio.get_running_loop()
    deadline = loop.time() + FAILURE_WINDOW
    while (remaining := deadline - loop.time()) > 0:
        try:
            name, payload = await asyncio.wait_for(events.queue.get(), timeout=remaining)
        except TimeoutError:
            break
        if name == "wavelink_track_exception":
            message = payload.exception.get("message")  # type: ignore[attr-defined]
            result = CheckResult(label, False, short_error(message))
            break
        if payload.reason == "loadFailed":  # type: ignore[attr-defined]
            result = CheckResult(label, False, "failed to load")
            break
    await node.send("DELETE", path=path)
    return result


async def _run_checks(settings: Settings, checks: list[tuple[str, str]]) -> list[CheckResult]:
    events = _Events()
    node = wavelink.Node(
        uri=settings.lavalink_uri,
        password=settings.lavalink_password,
        retries=3,  # the bot retries forever; a check should fail instead of hanging
        inactive_player_timeout=None,
        inactive_channel_tokens=None,
    )
    if not await wavelink.Pool.connect(nodes=[node], client=events):  # type: ignore[arg-type]
        raise LavalinkError(f"Couldn't connect to the check's Lavalink. See {LOG_PATH}.")
    # connect() returns before Lavalink's "ready" message arrives; until then loads fail.
    for _ in range(100):
        if node.status is wavelink.NodeStatus.CONNECTED:
            break
        await asyncio.sleep(0.1)
    try:
        async with aiohttp.ClientSession() as session:
            results = []
            for guild_id, (label, query) in enumerate(checks, start=1):
                result = await _check_one(node, events, session, guild_id, label, query)
                print(
                    f"  {'ok    ' if result.ok else 'FAILED'}  {label:<18} {result.detail}",
                    flush=True,
                )
                results.append(result)
            return results
    finally:
        await wavelink.Pool.close()


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    for noisy in ("wavelink", "TrackException"):
        logging.getLogger(noisy).setLevel(logging.CRITICAL)

    checks = [(truncate(q, 18), q) for q in sys.argv[1:]] or DEFAULT_CHECKS
    try:
        # Same settings as the bot (profile, cipher, OAuth), but a private port and password.
        base = load_settings(require_token=False)
        settings = dataclasses.replace(
            base, lavalink_port=_free_port(), lavalink_password=secrets.token_urlsafe(16)
        )
        process = LavalinkProcess(settings)
        print("Starting a private Lavalink for the check (about 15 seconds)...", flush=True)
        process.start()
    except (ConfigError, LavalinkError) as e:
        log.error("%s", e)
        sys.exit(1)

    try:
        process.wait_until_ready()
        results = asyncio.run(_run_checks(settings, checks))
    except LavalinkError as e:
        log.error("%s", e)
        sys.exit(1)
    finally:
        process.stop()

    failed = [r for r in results if not r.ok]
    if not failed:
        print(f"\nAll {len(results)} sources play.")
        return
    print(f"\n{len(failed)} of {len(results)} sources failed. Details: {LOG_PATH}")
    if any("YouTube" in r.detail or r.label.startswith("YouTube") for r in failed):
        print("YouTube is refusing playback from here. See README -> Troubleshooting.")
    sys.exit(1)


if __name__ == "__main__":
    main()
