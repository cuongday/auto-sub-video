import pytest
from autosub import store
from autosub.review.narration import BLOCK_GAP, SENT_GAP, sentences, subtitle_lines
from autosub.review.pace import syllables
from tests.review_helpers import ReviewRig, review_rig  # noqa: F401  (fixture)

def test_sentences():
    t = "Đội thứ nhất đáp xuống. Kế hoạch tưởng chừng hoàn hảo, cho đến khi Scott làm rơi khối Tesseract…"
    assert sentences(t) == ["Đội thứ nhất đáp xuống.", "Kế hoạch tưởng chừng hoàn hảo, cho đến khi Scott làm rơi khối Tesseract…"]
    assert sentences("Một! Hai?\n\nBa... Bốn") == ["Một!", "Hai?", "Ba...", "Bốn"]
    assert sentences("  \n ") == []

def test_long_sentence_split_at_comma():
    a, b, c = " ".join(["a"] * 15), " ".join(["b"] * 10), " ".join(["c"] * 15)
    parts = sentences(f"{a}, {b}, {c}.")
    assert len(parts) == 2 and all(syllables(p) <= 30 for p in parts)
    assert parts[0].endswith("b,") or parts[0].endswith("a,")

def test_subtitle_lines_contiguous():
    text = " ".join(["từ"] * 40)
    segs = subtitle_lines(text, 10.0, 6.0)
    assert segs[0].start == 10.0 and segs[-1].end == 16.0 and len(segs) > 1
    assert all(len(s.vi) <= 48 for s in segs) and all(a.end == b.start for a, b in zip(segs, segs[1:]))
    assert " ".join(s.vi for s in segs) == text

def test_gaps():
    assert SENT_GAP == 0.15 and BLOCK_GAP == 0.35

def _expected(rig, jid):
    from autosub.models import Script
    from autosub.review.narration import sentences
    return {b.id: sentences(b.text) for b in Script.model_validate(store.load_json(jid, "script.json")).blocks}

def test_tts_step_writes_narration(review_rig):
    review_rig.film_done()
    p = review_rig.part()
    assert review_rig.run(p.id, mode="auto").state == "done"
    nar = store.load_json(p.id, "narration.json")
    exp = _expected(review_rig, p.id)
    assert [(n["block"], n["text"]) for n in nar] == [(b, s) for b, ss in exp.items() for s in ss]
    assert all(n["dur"] > 0 and n["file"] == f"tts/b{n['block']:03d}_s{n['n']:03d}.wav" for n in nar)
    assert all(store.exists(p.id, n["file"]) for n in nar)

def test_edit_one_block_resynthesizes_only_it(review_rig):
    review_rig.film_done()
    p = review_rig.part()
    review_rig.run(p.id, mode="auto")
    sc = store.load_json(p.id, "script.json")
    sc["blocks"][1]["text"] = "Câu mới hoàn toàn. Và câu nữa."
    store.save_json(p.id, "script.json", sc)
    review_rig.tts.calls.clear()
    review_rig.run(p.id, mode="auto", from_step="tts")
    assert [c[0] for c in review_rig.tts.calls] == sentences_of("Câu mới hoàn toàn. Và câu nữa.")

def sentences_of(t):
    return sentences(t)

def test_tts_failure_reports_blocks(review_rig):
    review_rig.film_done()
    p = review_rig.part()
    review_rig.run(p.id, mode="review")
    sc = store.load_json(p.id, "script.json")
    sc["blocks"][0]["text"] = "Câu hỏng ZZZ."
    store.save_json(p.id, "script.json", sc)
    review_rig.tts.fail_on = "ZZZ"
    with pytest.raises(RuntimeError, match=r"TTS lỗi ở 1 câu \(khối 1\)"):
        review_rig.run(p.id, mode="auto")
