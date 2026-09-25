"""Find Java, download Lavalink and run it as a child process of the bot.

`uv run voldemar-lavalink` runs Lavalink alone in the foreground, which is handy for watching its
output or completing the YouTube sign-in flow.
"""

from __future__ import annotations

import glob
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from io import BufferedWriter
from pathlib import Path

from voldemar.config import PROJECT_ROOT, ConfigError, Settings, load_settings

log = logging.getLogger(__name__)

LAVALINK_VERSION = "4.2.2"
LAVALINK_URL = (
    f"https://github.com/lavalink-devs/Lavalink/releases/download/{LAVALINK_VERSION}/Lavalink.jar"
)
LAVALINK_DIR = PROJECT_ROOT / "lavalink"
JAR_PATH = LAVALINK_DIR / "Lavalink.jar"
LOG_PATH = PROJECT_ROOT / "logs" / "lavalink.log"
MIN_JAVA = 17
JAVA_OPTIONS = ["-Xmx512m"]
# The first start also downloads the YouTube and LavaSrc plugins, which can take a while.
READY_TIMEOUT = 180.0

# Local requests must never go through a system-wide HTTP proxy.
_local_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_JAVA_VERSION_RE = re.compile(r'version "(\d+)(?:\.(\d+))?')


class LavalinkError(Exception):
    """Lavalink couldn't be started. The message is shown to the user as-is."""


def parse_java_major(version_output: str) -> int | None:
    """Major version from `java -version` output: `"1.8.0_431"` -> 8, `"21.0.12.1"` -> 21."""
    match = _JAVA_VERSION_RE.search(version_output)
    if not match:
        return None
    major = int(match.group(1))
    if major == 1 and match.group(2):  # the "1.x" scheme used up to Java 8
        major = int(match.group(2))
    return major


def java_major_version(java: Path) -> int | None:
    try:
        result = subprocess.run(
            [str(java), "-version"], capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return parse_java_major(result.stderr or result.stdout)


def _java_candidates() -> list[Path]:
    candidates: list[Path] = []
    if java_home := os.getenv("JAVA_HOME"):
        candidates.append(Path(java_home) / "bin" / ("java.exe" if os.name == "nt" else "java"))
    if os.name == "nt":
        # Checked before PATH because an old Oracle Java 8 often sits first on PATH on Windows.
        for pattern in (
            r"C:\Program Files\Eclipse Adoptium\*\bin\java.exe",
            r"C:\Program Files\Microsoft\jdk-*\bin\java.exe",
            r"C:\Program Files\Zulu\*\bin\java.exe",
            r"C:\Program Files\Java\*\bin\java.exe",
        ):
            candidates.extend(Path(p) for p in sorted(glob.glob(pattern), reverse=True))
    if on_path := shutil.which("java"):
        candidates.append(Path(on_path))
    return candidates


def find_java(explicit: str = "") -> Path:
    """Path of a Java 17+ executable: JAVA_PATH if set, else the first suitable install found."""
    if explicit:
        path = Path(explicit)
        major = java_major_version(path) if path.is_file() else None
        if major is None or major < MIN_JAVA:
            raise LavalinkError(f"JAVA_PATH ({explicit}) is not a Java {MIN_JAVA}+ executable.")
        return path

    for candidate in _java_candidates():
        if not candidate.is_file():
            continue
        major = java_major_version(candidate)
        if major is not None and major >= MIN_JAVA:
            return candidate
        log.debug("Skipping %s (Java %s)", candidate, major)

    raise LavalinkError(
        f"Lavalink needs Java {MIN_JAVA} or newer and none was found. Install it with "
        "`winget install EclipseAdoptium.Temurin.21.JRE`, or set JAVA_PATH in .env."
    )


def ensure_jar() -> Path:
    """Download Lavalink.jar on first use."""
    if JAR_PATH.is_file():
        return JAR_PATH

    LAVALINK_DIR.mkdir(exist_ok=True)
    partial = JAR_PATH.with_suffix(".jar.part")
    log.info("Downloading Lavalink %s (about 100 MB, first start only)...", LAVALINK_VERSION)
    try:
        with (
            urllib.request.urlopen(LAVALINK_URL, timeout=60) as response,
            partial.open("wb") as out,
        ):
            total = int(response.headers.get("Content-Length") or 0)
            done, next_report = 0, 25
            while chunk := response.read(1 << 20):
                out.write(chunk)
                done += len(chunk)
                if total and done * 100 // total >= next_report:
                    log.info("  %d%%", done * 100 // total)
                    next_report += 25
        if total and done != total:
            raise LavalinkError(f"Lavalink download was cut off ({done} of {total} bytes).")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        partial.unlink(missing_ok=True)
        raise LavalinkError(f"Couldn't download Lavalink from {LAVALINK_URL}: {e}") from e
    except LavalinkError:
        partial.unlink(missing_ok=True)
        raise

    partial.replace(JAR_PATH)
    return JAR_PATH


def probe(settings: Settings) -> bool:
    """True if our Lavalink answers; raises if another Lavalink holds the port."""
    request = urllib.request.Request(
        f"{settings.lavalink_uri}/version", headers={"Authorization": settings.lavalink_password}
    )
    try:
        with _local_opener.open(request, timeout=2) as response:
            return response.status == 200
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise LavalinkError(
                f"A Lavalink with a different password is already running on "
                f"{settings.lavalink_uri}. Stop it, or change LAVALINK_PORT in .env."
            ) from e
        return False
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _child_env(settings: Settings) -> dict[str, str]:
    env = {**os.environ, **settings.lavalink_env()}
    env.pop("DISCORD_TOKEN", None)  # Lavalink has no use for it
    return env


def _log_tail(lines: int = 15) -> str:
    try:
        text = LOG_PATH.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "(no log output)"
    return "\n".join(text.splitlines()[-lines:])


class LavalinkProcess:
    """Lavalink running in the background; its console output goes to logs/lavalink.log."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._process: subprocess.Popen[bytes] | None = None
        self._log_file: BufferedWriter | None = None

    def start(self) -> None:
        java = find_java(self.settings.java_path)
        jar = ensure_jar()

        LOG_PATH.parent.mkdir(exist_ok=True)
        self._log_file = LOG_PATH.open("ab")
        self._log_file.write(f"\n===== Lavalink started {time.strftime('%c')} =====\n".encode())
        self._log_file.flush()

        log.info("Starting Lavalink %s with %s (output: %s)", LAVALINK_VERSION, java, LOG_PATH)
        self._process = subprocess.Popen(
            [str(java), *JAVA_OPTIONS, "-jar", str(jar)],
            cwd=LAVALINK_DIR,
            env=_child_env(self.settings),
            stdin=subprocess.DEVNULL,
            stdout=self._log_file,
            stderr=subprocess.STDOUT,
            # Keep Ctrl+C away from Java so the bot can leave voice channels before Lavalink stops.
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            start_new_session=os.name != "nt",
        )

    def wait_until_ready(self, timeout: float = READY_TIMEOUT) -> None:
        assert self._process is not None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if (code := self._process.poll()) is not None:
                raise LavalinkError(
                    f"Lavalink exited with code {code}. Last output:\n{_log_tail()}"
                )
            if probe(self.settings):
                log.info("Lavalink is ready on %s", self.settings.lavalink_uri)
                return
            time.sleep(1)
        self.stop()
        raise LavalinkError(f"Lavalink didn't start within {timeout:.0f} s. See {LOG_PATH}.")

    def stop(self) -> None:
        if self._process is not None and self._process.poll() is None:
            log.info("Stopping Lavalink")
            self._process.terminate()
            try:
                self._process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait()
        if self._log_file is not None:
            self._log_file.close()
            self._log_file = None


def main() -> None:
    """Run Lavalink in the foreground with the same settings the bot uses."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        settings = load_settings(require_token=False)
        java = find_java(settings.java_path)
        jar = ensure_jar()
    except (ConfigError, LavalinkError) as e:
        log.error("%s", e)
        sys.exit(1)

    log.info("Starting Lavalink %s on %s (Ctrl+C to stop)", LAVALINK_VERSION, settings.lavalink_uri)
    try:
        code = subprocess.call(
            [str(java), *JAVA_OPTIONS, "-jar", str(jar)], cwd=LAVALINK_DIR, env=_child_env(settings)
        )
    except KeyboardInterrupt:
        code = 0
    sys.exit(code)


if __name__ == "__main__":
    main()
