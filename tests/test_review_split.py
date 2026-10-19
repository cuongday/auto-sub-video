import pytest
from autosub import projects, store
from autosub.models import ChunkSummary, SceneNote, Segment
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

def test_create_parts_and_resplit_guard(review_rig):
    film = store.load(review_rig.film.id)
    film.info.duration = 200
    jobs = parts.create_parts(film, [100.0])
    assert [j.part.index for j in jobs] == [1, 2] and jobs[1].part.start == 100 and jobs[0].name == "Phim thử · Phần 1"
    assert jobs[0].review and jobs[0].kind == "review"
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
