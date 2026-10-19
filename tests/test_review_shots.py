import random
import subprocess
from autosub import store
from autosub.review.shots import MAX_SHOT, MIN_LAST, MIN_SHOT, BlockNeed, Shot, detect_cuts, plan_shots
from tests.review_helpers import ReviewRig, review_rig  # noqa: F401  (fixture)

def check(shots, blocks, part):
    for b in blocks:
        mine = [s for s in shots if s.block == b.id]
        assert abs(sum(s.end - s.start for s in mine) - b.duration) <= 0.04, (b, mine)
        assert all(part[0] - 1e-6 <= s.start < s.end <= part[1] + 1e-6 for s in mine), mine
        assert all(s.end - s.start <= MAX_SHOT + 1e-6 for s in mine), mine
        assert all(s.end - s.start >= MIN_SHOT - 1e-6 for s in mine[:-1]), mine
        assert mine[-1].end - mine[-1].start >= min(MIN_LAST, b.duration) - 1e-6, mine
        assert all(abs(x.start - y.start) >= 0.05 for x, y in zip(mine, mine[1:])), mine

def test_snaps_to_cut():
    assert plan_shots([BlockNeed(1, 4.0, [(100, 104)], None)], (0, 600), [100.6])[0].start == 100.6

def test_fills_from_source_range_first():
    blocks = [BlockNeed(1, 30.0, [(50, 53)], (200, 260))]
    shots = plan_shots(blocks, (0, 600), [float(c) for c in range(0, 600, 5)])
    check(shots, blocks, (0, 600))
    assert shots[0].start == 50 and len(shots) > 1
    assert all(200 <= s.start <= 260 for s in shots[1:])

def test_short_part_reuses_but_not_back_to_back():
    blocks = [BlockNeed(1, 60.0, [(2, 5)], None)]
    shots = plan_shots(blocks, (0, 20), [5.0, 12.0])
    check(shots, blocks, (0, 20))
    assert all(a != b for a, b in zip(shots, shots[1:]))

def test_same_start_scenes_not_repeated():
    blocks = [BlockNeed(1, 4.0, [(10, 12), (10, 16)], None)]
    shots = plan_shots(blocks, (0, 600), [])
    check(shots, blocks, (0, 600))
    assert shots == [Shot(1, 10, 14)]

def test_scenes_snapping_to_one_cut_not_repeated():
    blocks = [BlockNeed(1, 4.8, [(100, 103), (100.5, 110)], None)]
    shots = plan_shots(blocks, (0, 600), [100.6])
    check(shots, blocks, (0, 600))
    assert [s.start for s in shots] == [100.6]

def test_part_of_min_shot_terminates():
    shots = plan_shots([BlockNeed(1, 7.0, [], None)], (0, MIN_SHOT), [])
    assert abs(sum(s.end - s.start for s in shots) - 7.0) <= 0.04

def test_blocks_in_order_and_property():
    for seed in range(60):
        r = random.Random(seed)
        p0 = r.uniform(0, 1000)
        part = (p0, p0 + r.choice([r.uniform(60, 90), r.uniform(60, 1200)]))
        cuts = sorted(r.uniform(*part) for _ in range(r.choice([0, 0, 3, 30, 300])))
        blocks = []
        for i in range(1, r.randint(1, 8) + 1):
            scenes = [(a, a + r.uniform(0.2, 12))
                      for a in (r.uniform(part[0] - 5, part[1] + 5) for _ in range(r.randint(0, 3)))]
            if r.random() < 0.5:                       # 2-4 clustered scenes within 20 s, some sharing a start
                c = r.uniform(*part)
                scenes += [(a, a + r.uniform(1, 8)) for a in (r.choice([c, c + r.uniform(0, 20)]) for _ in range(r.randint(2, 4)))]
            s0 = r.uniform(*part)
            source = (s0, min(part[1], s0 + r.uniform(5, 120))) if r.random() < 0.7 else None
            blocks.append(BlockNeed(i, r.choice([r.uniform(0.5, 2), r.uniform(3, 60)]), scenes, source))
        shots = plan_shots(blocks, part, cuts)
        check(shots, blocks, part)
        assert [s.block for s in shots] == sorted(s.block for s in shots)

def test_detect_cuts_on_hard_cut(tmp_path):
    src = tmp_path / "rb.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=320x240:d=2:r=25",
                    "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=2:r=25", "-filter_complex", "concat=n=2:v=1:a=0",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(src)], check=True)
    cuts = detect_cuts(src, 0, 4)
    assert len(cuts) == 1 and abs(cuts[0] - 2.0) <= 0.1
    late = detect_cuts(src, 1, 3)                          # times are film seconds, not offsets into the range
    assert len(late) == 1 and abs(late[0] - 2.0) <= 0.1

def test_scenes_step_saves_cuts(review_rig):
    review_rig.film_done()
    p = review_rig.part()
    assert review_rig.run(p.id, mode="auto").state == "done"
    assert isinstance(store.load_json(p.id, "cuts.json"), list)
    h = store.load(p.id).steps["scenes"].hash
    sc = store.load_json(p.id, "script.json")
    sc["blocks"][0]["text"] = "Đổi lời một chút."
    store.save_json(p.id, "script.json", sc)
    review_rig.run(p.id, mode="auto", from_step="tts")
    assert store.load(p.id).steps["scenes"].hash == h
