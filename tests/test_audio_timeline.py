import pytest

from autosub.audio.script import Line
from autosub.audio.timeline import TAIL, sequential, timed


def test_sequential_gaps():
    lines = [Line("a", 0), Line("b", 0), Line("c", 1)]
    starts, total = sequential(lines, [1, 2, 1])
    assert starts == pytest.approx([0, 1.35, 4.15])
    assert total == pytest.approx(5.15 + TAIL)


def test_timed_keeps_cue_times():
    lines = [Line("a", 0, 1, 2), Line("b", 1, 3, 4)]
    starts, total = timed(lines, [0.8, 0.9])
    assert starts == [1, 3]
    assert total == pytest.approx(4 + TAIL)


def test_timed_overflow_pushes_later():
    lines = [Line("a", 0, 0, 1), Line("b", 1, 1, 2), Line("c", 2, 5, 6)]
    starts, total = timed(lines, [1.5, 1, 1])
    assert starts == pytest.approx([0, 1.5, 5])
    assert total == pytest.approx(6 + TAIL)
