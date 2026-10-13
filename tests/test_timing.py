import numpy as np
from autosub.models import Segment
from autosub.timing import slots, max_chars, trim_silence

def seg(i, a, b): return Segment(id=i, start=a, end=b, source="x")

def test_slots_use_gap_to_next_start():
    s = slots([seg(1, 0, 1), seg(2, 2.5, 3), seg(3, 3.0, 4)], duration=10)
    assert s[0] == 2.45 and round(s[1], 3) == 0.45

def test_last_slot_extends_one_second_capped_by_duration():
    assert slots([seg(1, 0, 1)], duration=10) == [2.0]
    assert slots([seg(1, 0, 1)], duration=1.5) == [1.5]

def test_slot_floor():
    assert slots([seg(1, 0, 1), seg(2, 0.1, 1)], duration=5)[0] == 0.3

def test_max_chars():
    assert max_chars(2.0) == 30 and max_chars(0.1) == 4

def test_trim_silence():
    sr = 1000
    pcm = np.concatenate([np.zeros(500), 0.5 * np.ones(1000), np.zeros(700)]).astype(np.float32)
    out = trim_silence(pcm, sr, pad=0.0)
    assert len(out) == 1000
    assert len(trim_silence(np.zeros(100, np.float32), sr)) == 0
