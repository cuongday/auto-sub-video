import random
import subprocess
import threading
import pytest
from autosub import store
from autosub.models import PartInfo, ReviewSettings
from autosub.review.script import validate_blocks
from autosub.review.shots import MAX_SHOT, MIN_LAST, MIN_SHOT, BlockNeed, Shot, detect_cuts, plan_shots
from tests.review_helpers import ReviewRig, review_rig  # noqa: F401  (fixture)

def check(shots, blocks, part, window=None):
    w0, w1 = window or part
    for b in blocks:
        mine = [s for s in shots if s.block == b.id]
        assert abs(sum(s.end - s.start for s in mine) - b.duration) <= 0.04, (b, mine)
        assert all(part[0] - 1e-6 <= s.start < s.end <= part[1] + 1e-6 for s in mine), mine
        # footage outside the dialogue window only where an explicit scene of the block points (1 s: cut snapping)
        sc = [(min(max(a, part[0]), part[1] - MIN_SHOT), e) for a, e in b.scenes]
        lo, hi = min([w0] + [a - 1 for a, _ in sc]), max([w1] + [max(e, a + MIN_SHOT) + 1 for a, e in sc])
        assert all(lo - 1e-6 <= s.start and s.end <= hi + 1e-6 for s in mine), (b, mine, window)
        assert all(s.end - s.start <= MAX_SHOT + 1e-6 for s in mine), mine
        assert all(s.end - s.start >= MIN_SHOT - 1e-6 for s in mine[:-1]), mine
        assert mine[-1].end - mine[-1].start >= min(MIN_LAST, b.duration) - 1e-6, mine
        assert all(abs(x.start - y.start) >= 0.05 for x, y in zip(mine, mine[1:])), mine

def test_snaps_to_cut():
    assert plan_shots([BlockNeed(1, 4.0, [(100, 104)], None)], (0, 600), [100.6])[0].start == 100.6

def test_body_block_moves_forward_with_the_story():
    cuts = [float(c) for c in range(0, 2000, 5)]
    one = [BlockNeed(1, 40.0, [(610, 614)], (600, 1200))]
    shots = plan_shots(one, (0, 2000), cuts)
    check(shots, one, (0, 2000))
    starts = [s.start for s in shots]
    assert starts[0] == 610 and starts == sorted(starts)              # never back into earlier footage
    bare = [BlockNeed(1, 40.0, [], (600, 1200))]
    shots = plan_shots(bare, (0, 2000), cuts)
    check(shots, bare, (0, 2000))
    starts = [s.start for s in shots]
    assert starts == sorted(starts) and starts[0] <= 601 and starts[-1] >= 1200 - MAX_SHOT - 1   # the whole range

def test_no_footage_outside_the_dialogue_window():
    blocks = [BlockNeed(1, 15.0, [], None), BlockNeed(2, 20.0, [(300, 304)], (300, 400)),
              BlockNeed(3, 12.0, [], (0, 20)), BlockNeed(4, 12.0, [], None)]
    shots = plan_shots(blocks, (0, 1200), [], (25, 900))
    check(shots, blocks, (0, 1200), (25, 900))
    assert all(25 <= s.start and s.end <= 900 for s in shots), shots     # no logos under the hook, no credits

def test_sentence_durations_split_the_block_across_its_scenes():
    blocks = [BlockNeed(1, 11.0, [(100, 104), (200, 204), (300, 304)], None, [2.0, 6.0, 3.0])]
    shots = plan_shots(blocks, (0, 600), [])
    check(shots, blocks, (0, 600))
    per = [sum(s.end - s.start for s in shots if a <= s.start < a + 50) for a in (100, 200, 300)]
    assert per == pytest.approx([2.0, 6.0, 3.0])
    equal = plan_shots([BlockNeed(1, 12.0, [(100, 104), (200, 204), (300, 304)], None, [2.0, 6.0])], (0, 600), [])
    assert [sum(s.end - s.start for s in equal if a <= s.start < a + 50) for a in (100, 200, 300)] == pytest.approx([4] * 3)

def test_scenes_keep_the_narration_order():
    shots = plan_shots([BlockNeed(1, 9.0, [(300, 303), (100, 103), (200, 203)], None)], (0, 600), [])
    assert [s.start for s in shots] == [300, 100, 200]

def test_body_block_without_scenes_spreads_over_its_source():
    # the script gives a body block with no usable scene its source range as its one scene
    part = PartInfo(film_job="f", index=1, start=0, end=2000)
    raw = [{"kind": "than", "text": "Thân.", "scenes": [], "source_start": 600, "source_end": 1200}]
    blk = validate_blocks(raw, part, ReviewSettings())[0]
    need = BlockNeed(blk.id, 40.0, [(s.start, s.end) for s in blk.scenes], (blk.source_start, blk.source_end), [8.0] * 5)
    shots = plan_shots([need], (0, 2000), [float(c) for c in range(0, 2000, 5)])
    check(shots, [need], (0, 2000))
    starts = [s.start for s in shots]
    assert starts == sorted(starts) and starts[0] <= 601 and starts[-1] >= 1200 - 8 - 1, starts
    assert len({round(s // 100) for s in starts}) >= 5                     # every sentence its own stretch

def test_many_short_sentences_still_spread():
    blocks = [BlockNeed(1, 40.0, [], (600, 1200), [1.33] * 30)]          # "Trịnh Mộc Sinh." x 30
    shots = plan_shots(blocks, (0, 2000), [])
    check(shots, blocks, (0, 2000))
    starts = [s.start for s in shots]
    assert starts == sorted(starts) and starts[0] < 650 and starts[-1] > 1100, starts

def test_negative_weights_terminate():
    blocks = [BlockNeed(1, 87.9, [(960, 968), (924, 928), (624, 631)], (755, 1189), [-2.42, 0.40, 2.45])]
    got = []
    t = threading.Thread(target=lambda: got.append(plan_shots(blocks, (662.5, 1262.5), [])), daemon=True)
    t.start()
    t.join(5)                                                          # a hang fails here instead of freezing pytest
    assert got, "plan_shots did not return"
    check(got[0], blocks, (662.5, 1262.5))

def test_hook_and_ending_without_scenes_use_the_footage_next_to_the_body():
    blocks = [BlockNeed(1, 10.0, [], None), BlockNeed(2, 30.0, [(300, 304)], (300, 500)),
              BlockNeed(3, 30.0, [(520, 524)], (520, 700)), BlockNeed(4, 10.0, [], None)]
    shots = plan_shots(blocks, (0, 1200), [], (25, 1100))
    check(shots, blocks, (0, 1200), (25, 1100))
    assert all(300 <= s.start and s.end <= 310 for s in shots if s.block == 1), shots
    assert all(690 <= s.start and s.end <= 700 for s in shots if s.block == 4), shots

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
            weights = [r.uniform(-1, 8) for _ in range(r.choice([len(scenes), 1, 4]))] if r.random() < 0.5 else None
            blocks.append(BlockNeed(i, r.choice([r.uniform(0.5, 2), r.uniform(3, 60)]), scenes, source, weights))
        window = (part[0] + r.uniform(0, 15), part[1] - r.uniform(0, 15)) if r.random() < 0.6 else None
        shots = plan_shots(blocks, part, cuts, window)
        check(shots, blocks, part, window)
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
