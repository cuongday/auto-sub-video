import pytest
from autosub import projects, store
from autosub.models import ChunkSummary, JobSettings, SceneNote, Segment
from autosub.review import parts
from autosub.review.split import propose_cuts
from tests.review_helpers import review_rig  # noqa: F401  (fixture)

def _gap_lines(duration, gaps):
    """Back-to-back 1 s lines, none starting inside a (start, end) silence."""
    return [Segment(id=t, start=t, end=t + 1, source="x") for t in range(duration)
            if not any(a <= t < b for a, b in gaps)]

def test_three_parts_snap_to_big_gaps():
    lines = _gap_lines(9000, [(3020, 3032), (5980, 5992)])
    assert propose_cuts(lines, 9000, parts=3) == [3026.0, 5986.0]

def test_event_bonus_beats_slightly_bigger_gap():
    lines = _gap_lines(6000, [(2900, 2905), (3100, 3103)])
    ev = ChunkSummary(start=0, end=6000, summary="", events=[SceneNote(start=3000, end=3101, text="e")])
    assert propose_cuts(lines, 6000, parts=2, chunks=[ev]) == [3101.5]
    assert propose_cuts(lines, 6000, parts=2) == [2902.5]

def test_minutes_per_part():
    assert len(propose_cuts(_gap_lines(7200, []), 7200, minutes=45)) == 2     # ceil(7200/2700) = 3 parts

def test_no_gaps_falls_back_to_targets():
    lines = [Segment(id=i, start=i * 4, end=i * 4 + 4, source="x") for i in range(100)]
    assert propose_cuts(lines, 400, parts=2) == [200.0]

def _ok(cuts, duration):
    b = [0, *cuts, duration]
    return cuts == sorted(cuts) and all(y - x >= 60 for x, y in zip(b, b[1:]))

def test_cuts_sorted_and_min_length():
    lines = [Segment(id=0, start=0, end=1, source="x"), Segment(id=1, start=7001, end=7002, source="x")]
    lines[0].end = 6999.0
    cuts = propose_cuts(lines, 9000, parts=3)
    assert len(cuts) == 2 and _ok(cuts, 9000)
    assert propose_cuts([], 100, parts=2) == []
    assert propose_cuts([], 130, parts=2) == [65.0]

def test_create_parts_rejects_bad_cuts(review_rig):
    film = store.load(review_rig.film.id)
    film.info.duration = 200
    for bad in ([30.0], [100.0, 90.0], [250.0], [-5.0], [100.0, 100.0]):
        with pytest.raises(ValueError):
            parts.create_parts(film, bad)
    assert parts.parts_of(review_rig.project.id) == []

def test_create_parts_and_resplit_guard(review_rig):
    film = store.load(review_rig.film.id)
    film.info.duration = 200
    jobs = parts.create_parts(film, [100.0])
    assert [j.part.index for j in jobs] == [1, 2] and jobs[1].part.start == 100 and jobs[0].name == "Phim thử · Phần 1"
    assert jobs[0].kind == "review" and jobs[0].review == projects.get(review_rig.project.id).review.settings
    assert jobs[0].settings == JobSettings()
    jobs[0].steps["script"].status = "done"
    store.save(jobs[0])
    with pytest.raises(ValueError):
        parts.create_parts(film, [50.0])
    assert len(parts.parts_of(review_rig.project.id)) == 2

def test_series_two_parts_per_episode(review_rig):
    p = projects.get(review_rig.project.id)
    p.review.parts_per_episode = 2
    p.review.movie.type = "series"
    projects.save(p)
    f2 = review_rig.add_film(1)
    for f in (f2, review_rig.film):
        f = store.load(f.id); f.info.duration = 300; store.save(f)
        parts.ensure_default_parts(store.load(f.id))
    got = parts.parts_of(p.id)
    assert [j.part.index for j in got] == [1, 2, 3, 4]
    assert [store.load(j.part.film_job).film.episode_index for j in got] == [0, 0, 1, 1]

def test_ensure_default_parts_idempotent_and_single_noop(review_rig):
    film = store.load(review_rig.film.id)
    parts.ensure_default_parts(film)                 # single movie: nothing
    assert parts.parts_of(review_rig.project.id) == []
    p = projects.get(review_rig.project.id)
    p.review.movie.type = "series"; projects.save(p)
    parts.ensure_default_parts(film)
    first = [j.id for j in parts.parts_of(p.id)]
    assert len(first) == 1
    parts.ensure_default_parts(film)
    assert [j.id for j in parts.parts_of(p.id)] == first
