from voldemar.music.resolver import Candidate, best_match, score

TARGET = Candidate("Never Gonna Give You Up", "Rick Astley", 213_573)


def test_prefers_official_audio_with_matching_length() -> None:
    candidates = [
        Candidate("Never Gonna Give You Up (Live at Glastonbury)", "Rick Astley", 260_000),
        Candidate("Never Gonna Give You Up (Official Video) (4K Remaster)", "Rick Astley", 214_000),
        Candidate("Never Gonna Give You Up", "Rick Astley - Topic", 213_000),
    ]
    assert best_match(TARGET, candidates) == (2, score(TARGET, candidates[2]))


def test_penalises_different_versions() -> None:
    cover = Candidate("Never Gonna Give You Up (Cover)", "Some Band", 213_000)
    nightcore = Candidate("Never Gonna Give You Up - Nightcore", "NC Channel", 170_000)
    real = Candidate("Rick Astley - Never Gonna Give You Up", "RickAstleyVEVO", 213_000)
    assert best_match(TARGET, [cover, nightcore, real])[0] == 2


def test_version_words_in_the_spotify_title_are_not_penalised() -> None:
    target = Candidate("Hotel California - Live", "Eagles", 431_000)
    live = Candidate("Hotel California (Live)", "Eagles - Topic", 431_500)
    assert score(target, live) >= 5


def test_featured_artists_and_title_additions_still_match() -> None:
    target = Candidate("Global Warming (feat. Sensato)", "Pitbull, Sensato", 85_400)
    candidate = Candidate("Global Warming", "Pitbull - Topic", 86_000)
    assert score(target, candidate) >= 8


def test_matches_non_latin_titles() -> None:
    target = Candidate("Группа крови", "КИНО", 286_000)
    candidates = [
        Candidate("Звезда по имени Солнце", "КИНО - Topic", 226_000),
        Candidate("Группа крови", "КИНО - Topic", 286_500),
    ]
    assert best_match(target, candidates)[0] == 1


def test_ties_keep_search_order_and_unknown_lengths_are_ignored() -> None:
    target = Candidate("Song", "Artist", 0)
    candidates = [Candidate("Song", "Artist", 100_000), Candidate("Song", "Artist", 200_000)]
    assert best_match(target, candidates)[0] == 0


def test_no_candidates() -> None:
    assert best_match(TARGET, []) is None
