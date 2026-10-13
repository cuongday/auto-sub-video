import json
from autosub.models import Segment, TranslationContext
from autosub.translate import analyze, translate_all, translate_ids, shorten, ITEMS_SCHEMA
from tests.fakes import FakeLLM, ids_in

def segs(n):
    return [Segment(id=i, start=i * 2.0, end=i * 2.0 + 1.5, source=f"句子{i}") for i in range(1, n + 1)]

def slots_of(ss): return [1.95] * len(ss)

def test_analyze():
    ctx = analyze(FakeLLM(), segs(3), "zh", "phim hiện đại")
    assert ctx.characters[0].vi_name == "Tiểu Minh"

def test_analyze_prompt_contains_notes_and_text():
    llm = FakeLLM()
    analyze(llm, segs(2), "zh", "xưng ta/ngươi")
    assert "xưng ta/ngươi" in llm.prompts[0] and "句子1" in llm.prompts[0]

def test_batches_and_previous_context():
    llm = FakeLLM()
    out = translate_all(llm, segs(85), slots_of(segs(85)), TranslationContext(), "zh", "")
    assert len(llm.prompts) == 3
    assert ids_in(llm.prompts[1])[0] == 41 and len(ids_in(llm.prompts[2])) == 5
    assert "VI 句子40" in llm.prompts[1]           # previous translated lines are shown
    assert out[0].vi == "VI 句子1" and out[84].vi == "VI 句子85"
    assert all(not s.flags for s in out)

def test_max_chars_in_prompt():
    llm = FakeLLM()
    translate_all(llm, segs(1), [2.0], TranslationContext(), "zh", "")
    item = json.loads(llm.prompts[0][llm.prompts[0].rindex("<<<ITEMS") + 8: llm.prompts[0].rindex("ITEMS>>>")])[0]
    assert item["max_chars"] == 30 and item["seconds"] == 2.0

def test_missing_id_retries_then_falls_back():
    calls = []
    def hook(prompt, schema):
        calls.append(1)
        return {"items": [{"id": i, "vi": "x"} for i in ids_in(prompt) if i != 2]}
    out = translate_all(FakeLLM(hook), segs(3), slots_of(segs(3)), TranslationContext(), "zh", "")
    assert len(calls) == 3
    assert out[1].vi == "句子2" and "translate_failed" in out[1].flags
    assert out[0].vi == "x"

def test_retry_recovers():
    state = {"n": 0}
    def hook(prompt, schema):
        state["n"] += 1
        return {"items": []} if state["n"] == 1 else None
    out = translate_all(FakeLLM(hook), segs(2), slots_of(segs(2)), TranslationContext(), "zh", "")
    assert out[0].vi == "VI 句子1" and state["n"] == 2

def test_long_lines_get_shortened_once():
    def hook(prompt, schema):
        if "RÚT GỌN" in prompt:
            return {"items": [{"id": i, "vi": "ngắn" if i == 1 else "vẫn còn quá dài " * 5} for i in ids_in(prompt)]}
        return {"items": [{"id": i, "vi": "rất dài " * 20} for i in ids_in(prompt)]}
    out = translate_all(FakeLLM(hook), segs(2), [1.0, 1.0], TranslationContext(), "zh", "")
    assert out[0].vi == "ngắn" and not out[0].flags
    assert "too_long" in out[1].flags

def test_translate_ids_only_touches_given():
    ss = translate_all(FakeLLM(), segs(4), slots_of(segs(4)), TranslationContext(), "zh", "")
    llm = FakeLLM(lambda p, s: {"items": [{"id": i, "vi": "mới"} for i in ids_in(p)]})
    out = translate_ids(llm, ss, slots_of(ss), TranslationContext(), "zh", "", {3})
    assert [s.vi for s in out] == ["VI 句子1", "VI 句子2", "mới", "VI 句子4"]
    assert ids_in(llm.prompts[0]) == [3]

def test_shorten():
    llm = FakeLLM(lambda p, s: {"items": [{"id": 7, "vi": "gọn"}]})
    assert shorten(llm, [(Segment(id=7, start=0, end=1, source="a", vi="dài dòng quá"), 5)], TranslationContext(), "zh") == {7: "gọn"}

def test_items_schema_shape():
    assert ITEMS_SCHEMA["properties"]["items"]["items"]["required"] == ["id", "vi"]
