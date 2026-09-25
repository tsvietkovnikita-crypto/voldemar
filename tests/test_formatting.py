import pytest

from voldemar.music.queue import QueueEntry
from voldemar.ui.formatting import entry_link, format_duration, parse_time, progress_bar


@pytest.mark.parametrize(
    ("ms", "text"),
    [(0, "0:00"), (5_999, "0:05"), (83_000, "1:23"), (3_723_000, "1:02:03"), (-5, "0:00")],
)
def test_format_duration(ms: int, text: str) -> None:
    assert format_duration(ms) == text


@pytest.mark.parametrize(
    ("text", "ms"),
    [
        ("83", 83_000),
        ("1:23", 83_000),
        ("01:02:03", 3_723_000),
        ("1m23s", 83_000),
        ("2h", 7_200_000),
        (" 45s ", 45_000),
        ("0", 0),
    ],
)
def test_parse_time(text: str, ms: int) -> None:
    assert parse_time(text) == ms


@pytest.mark.parametrize("text", ["", "abc", "1:75", "1:2:3:4", "-5", "1.5"])
def test_parse_time_rejects_garbage(text: str) -> None:
    with pytest.raises(ValueError):
        parse_time(text)


def test_progress_bar() -> None:
    assert progress_bar(0, 100_000, width=5).startswith("🔘▬▬▬▬")
    assert progress_bar(100_000, 100_000, width=5).startswith("▬▬▬▬🔘")
    assert progress_bar(500_000, 100_000, width=5).startswith("▬▬▬▬🔘")  # clamped
    assert progress_bar(1_000, 0) == "🔴 LIVE"


def test_entry_link_escapes_markdown() -> None:
    entry = QueueEntry("Song [Live] *wow*", "a", 1, 1, "youtube", uri="https://youtu.be/x")
    assert entry_link(entry) == r"[Song (Live) \*wow\*](https://youtu.be/x)"
    entry.uri = None
    assert entry_link(entry) == r"**Song (Live) \*wow\***"
