import json
import re
import pytest
from autosub import projects, store
from autosub.models import (ChunkSummary, FilmCharacter, MovieMeta, Notebook, NotebookCharacter, NotebookEntry, PartInfo,
                            ReviewSettings, SceneNote, ScriptBlock, TimeSpan)
from autosub.review import notebook, pace, script, templates
from autosub.storage import get_store
from tests.fakes import FakeLLM, FakeTTS, review_llm_hook
from tests.review_helpers import ReviewRig, review_rig  # noqa: F401  (fixture)

def test_syllables():
    assert pace.syllables("Ở phần trước, nhóm Avengers còn sót lại…") == 8
    assert pace.syllables("— 3 ... con mèo _") == 3

def test_measure_spm_cached(monkeypatch):
    tts = FakeTTS()
    spm = pace.measure_spm(tts, "v", 1.0, None)
    assert spm > 0 and spm != pace.DEFAULT_SPM and len(tts.calls) == 1
    assert list(json.loads(get_store().get_bytes("review/pace.json")).values()) == [spm]
    assert pace.measure_spm(FakeTTS(fail_on="a"), "x", 1.2, None) == pace.DEFAULT_SPM   # error -> default
    monkeypatch.setattr(pace, "cached_synthesize", lambda *a, **k: pytest.fail("measured twice"))
    assert pace.measure_spm(tts, "v", 1.0, None) == spm and len(tts.calls) == 1

def test_notebook_rev_and_hooks():
    nb = Notebook(shared_rev=2, entries=[NotebookEntry(job="a", index=1, range_label="", summary="", hooks=["h1"], rev=5),
                                         NotebookEntry(job="b", index=2, range_label="", summary="", hooks=["h2"], rev=7)])
    assert notebook.rev_before(nb, 1) == 2 and notebook.rev_before(nb, 2) == 5 and notebook.rev_before(nb, 3) == 7
    assert notebook.rev_before(Notebook(), 4) == 0
    assert notebook.used_hooks(nb) == ["h1", "h2"]

PART = PartInfo(film_job="f", index=1, start=100, end=400)

def test_validate_clamps_and_orders():
    sc = lambda a, b: {"start": a, "end": b}  # noqa: E731
    raw = [{"kind": "ket", "text": "Kết.", "scenes": [sc(390, 500)], "source_start": 350, "source_end": 400},
           {"kind": "than", "text": "Thân hai.", "scenes": [], "source_start": 300, "source_end": 350},
           {"kind": "hook", "text": "Hook?", "scenes": [sc(-10, 5)], "source_start": 0, "source_end": 5},
           {"kind": "than", "text": "  ", "scenes": [sc(150, 160)], "source_start": 150, "source_end": 160},
           {"kind": "than", "text": "Ngoài phần.", "scenes": [], "source_start": 500, "source_end": 600},
           {"kind": "than", "text": "Thân một.", "scenes": [sc(150, 160), sc(399.8, 420)], "source_start": 150,
            "source_end": 200},
           {"kind": "mo_dau", "text": "Mở đầu.", "scenes": [], "source_start": 100, "source_end": 110}]
    out = script.validate_blocks(raw, PART, ReviewSettings())
    assert [(b.id, b.kind, b.text) for b in out] == [(1, "hook", "Hook?"), (2, "mo_dau", "Mở đầu."),
                                                     (3, "than", "Thân một."), (4, "than", "Thân hai."), (5, "ket", "Kết.")]
    assert out[0].scenes == [] and out[4].scenes == [TimeSpan(start=390, end=400)]
    assert out[2].scenes == [TimeSpan(start=150, end=160)] and out[3].scenes == [TimeSpan(start=300, end=350)]
    assert (out[0].template, out[1].template, out[2].template) == ("cau_hoi", "gioi_thieu", "")
    assert script.validate_blocks(raw, PART.model_copy(update={"index": 2}), ReviewSettings())[1].template == "tom_tat_truoc"

def test_locked_block_survives_rewrite():
    mine = ScriptBlock(id=3, kind="than", text="Câu tôi tự viết", scenes=[TimeSpan(start=90, end=95)],
                       source_start=200, source_end=220, edited=True)
    hook = ScriptBlock(id=1, kind="hook", text="Hook của tôi", edited=True)
    raw = [{"kind": k, "text": f"LLM {k} {s}", "scenes": [], "source_start": s, "source_end": s + 50}
           for k, s in [("hook", 100), ("than", 150), ("than", 300), ("ket", 350)]]
    out = script.validate_blocks(raw, PART, ReviewSettings(), [mine, hook])
    assert [b.text for b in out] == ["Hook của tôi", "LLM than 150", "Câu tôi tự viết", "LLM than 300", "LLM ket 350"]
    assert [b.id for b in out] == [1, 2, 3, 4, 5]
    assert out[2].edited and out[2].scenes == mine.scenes and out[0].edited and not out[1].edited

def _build(llm, **kw):
    args = dict(meta=MovieMeta(name="Phim thử"), characters=[FilmCharacter(name="Tiểu Minh", role="nhân vật chính")],
                chunks=[ChunkSummary(start=0, end=600, summary="Tiểu Minh lên đường.",
                                     events=[SceneNote(start=150, end=180, text="Tiểu Minh rời nhà"),
                                             SceneNote(start=10, end=20, text="Sự kiện ngoài phần")]),
                        ChunkSummary(start=1200, end=1800, summary="Đoạn không thuộc phần này.")],
                part=PART, total_parts=1, is_last=False, settings=ReviewSettings(), notebook=Notebook(), spm=190)
    return script.build_script(llm, **{**args, **kw})

def test_length_retry():
    calls = []
    def hook(prompt, schema):
        calls.append(prompt)
        if len(calls) == 1:
            prompt = re.sub(r"TARGET (\d+)", lambda m: f"TARGET {int(m[1]) // 2}", prompt)
        return review_llm_hook(prompt, schema)
    s = _build(FakeLLM(hook))
    assert len(calls) == 2 and "ngắn hơn mục tiêu" in calls[1] and "khoảng 950 âm tiết" in calls[1]
    assert sum(pace.syllables(b.text) for b in s.blocks) == 950
    assert script.estimate_seconds(s, 190) == pytest.approx(300 + 4 * 0.35)

def test_prompt_rules():
    llm = FakeLLM(review_llm_hook)
    nb = Notebook(voice="xưng mình, gọi khán giả là các bạn", entries=[
        NotebookEntry(job="a", index=1, range_label="0–100", summary="Tiểu Minh rời làng ra đi.", ending="Đứng trước cổng thành",
                      open_threads=["Ai gửi lá thư?"], hooks=["Ai đã giết Tiểu Minh?"], rev=1),
        NotebookEntry(job="c", index=3, range_label="400–600", summary="Phần sau không được đọc.", rev=2)])
    part2 = PART.model_copy(update={"index": 2})
    _build(llm, part=part2, total_parts=3, notebook=nb, settings=ReviewSettings(notes="Nhắc tên đạo diễn"))
    p = llm.prompts[-1]
    for text in ["Tiểu Minh rời làng ra đi.", "Đứng trước cổng thành", "Ai gửi lá thư?", "xưng mình",
                 "Hook đã dùng: Ai đã giết Tiểu Minh?", templates.prompt("styles", "kich_tinh"),
                 templates.prompt("hooks", "cau_hoi"), templates.prompt("openings", "tom_tat_truoc"), "Nhắc tên đạo diễn",
                 "Tiểu Minh rời nhà", "Phim thử", "Tiểu Minh", "RANGE 100.0 400.0", "TARGET 950",
                 "Chỉ kể những gì có trong tóm tắt, không thêm tình tiết", "kể ở ngôi thứ ba, bằng tiếng Việt",
                 "mỗi khối kèm các cảnh minh hoạ lấy từ mốc thời gian trong tóm tắt"]:
        assert text in p, text
    for text in ["Phần sau không được đọc.", "Đoạn không thuộc phần này.", "Sự kiện ngoài phần", "Không được tiết lộ cái kết"]:
        assert text not in p, text
    _build(llm, is_last=True)
    assert "Không được tiết lộ cái kết" in llm.prompts[-1] and "Hook đã dùng" not in llm.prompts[-1]
    _build(llm, is_last=True, settings=ReviewSettings(spoil_ending=True))
    assert "Không được tiết lộ cái kết" not in llm.prompts[-1]

def test_duplicate_hook_retried_once():
    def hook(prompt, schema):
        r = review_llm_hook(prompt, schema)
        r["blocks"][0]["text"] = "ai đã giết tiểu minh"                  # 5 syllables = TARGET 20 / 4
        return r
    llm = FakeLLM(hook)
    nb = Notebook(entries=[NotebookEntry(job="a", index=1, range_label="", summary="", hooks=["Ai đã giết Tiểu Minh?"], rev=1)])
    _build(llm, notebook=nb, spm=20, settings=ReviewSettings(minutes=1), part=PART.model_copy(update={"index": 2}))
    assert len(llm.prompts) == 2 and "Hook bị trùng với phần trước: viết hook khác" in llm.prompts[1]

def test_script_step_stops_for_review(review_rig):
    review_rig.film_done()
    p = review_rig.part()
    job = review_rig.run(p.id, mode="review")
    assert job.state == "awaiting_review" and job.steps["script"].status == "done"
    blocks = store.load_json(p.id, "script.json")["blocks"]
    assert [b["kind"] for b in blocks] == ["hook", "mo_dau", "than", "ket"]
    assert "Không được tiết lộ cái kết" in review_rig.llm.prompts[-1]          # the only part is the last
    assert "TARGET 20 " in review_rig.llm.prompts[-1]                          # minutes 1 x seeded pace 20/min
    n = len(review_rig.llm.prompts)
    job = review_rig.run(p.id, mode="auto")
    assert job.state == "done" and len(review_rig.llm.prompts) == n           # script cached

def test_script_step_errors_on_empty_transcript(tmp_path):
    rig = ReviewRig(tmp_path, subtitles="WEBVTT\n\n00:00:01.000 --> 00:00:03.000\ntryray.app\n")
    rig.film_done()
    p = rig.part()
    with pytest.raises(RuntimeError):
        rig.run(p.id, mode="review")
    assert "Không có lời thoại" in store.load(p.id).error

def test_script_step_needs_prepared_film(review_rig):
    p = review_rig.part()                                                     # film never run
    with pytest.raises(RuntimeError):
        review_rig.run(p.id, mode="review")
    assert "Phim chưa chuẩn bị xong" in store.load(p.id).error

def test_rewrite_block_keeps_scenes():
    s = script.Script(blocks=[ScriptBlock(id=1, kind="hook", text="Cũ", scenes=[TimeSpan(start=120, end=125)])])
    llm = FakeLLM(review_llm_hook)
    b = script.rewrite_block(llm, s, 1, "ngắn hơn", meta=MovieMeta(name="Phim thử"), settings=ReviewSettings(), part=PART)
    assert (b.text, b.edited, b.scenes) == ("Viết lại", True, s.blocks[0].scenes) and "ngắn hơn" in llm.prompts[-1]

def test_notebook_change_does_not_rewrite_script(review_rig):
    review_rig.film_done()
    p = review_rig.part()
    review_rig.run(p.id, mode="auto")
    before, n = store.load_json(p.id, "script.json"), len(review_rig.llm.prompts)
    proj = projects.get(review_rig.project.id)
    proj.review.notebook.shared_rev = 5
    proj.review.notebook.entries.append(NotebookEntry(job="x", index=0, range_label="", summary="Trước đó.", rev=6))
    projects.save(proj)
    assert review_rig.run(p.id, mode="auto").state == "done"
    assert len(review_rig.llm.prompts) == n and store.load_json(p.id, "script.json") == before
    job = review_rig.run(p.id, mode="auto", from_step="script")
    assert len(review_rig.llm.prompts) > n and job.part.notebook_rev == 6

def test_own_previous_hook_is_not_a_duplicate():
    def hook(prompt, schema):
        r = review_llm_hook(prompt, schema)
        r["blocks"][0]["text"] = "ai đã giết tiểu minh"
        return r
    llm = FakeLLM(hook)
    nb = Notebook(entries=[NotebookEntry(job="a", index=1, range_label="", summary="", hooks=["Ai đã giết Tiểu Minh?"], rev=1)])
    _build(llm, notebook=nb, spm=20, settings=ReviewSettings(minutes=1))      # PART is index 1: its own entry
    assert len(llm.prompts) == 1

def test_rewrite_unknown_block():
    with pytest.raises(ValueError, match="Không tìm thấy khối 9"):
        script.rewrite_block(FakeLLM(review_llm_hook), script.Script(blocks=[]), 9, "", meta=MovieMeta(name="P"),
                             settings=ReviewSettings(), part=PART)

def test_locked_block_survives_length_retry():
    mine = ScriptBlock(id=3, kind="than", text="Câu tôi tự viết", scenes=[TimeSpan(start=90, end=95)],
                       source_start=200, source_end=220, edited=True)
    calls = []
    def hook(prompt, schema):
        calls.append(prompt)
        if len(calls) == 1:
            prompt = re.sub(r"TARGET (\d+)", lambda m: f"TARGET {int(m[1]) // 2}", prompt)
        return review_llm_hook(prompt, schema)
    s = _build(FakeLLM(hook), locked=[mine])
    assert len(calls) == 2 and "Câu tôi tự viết" in calls[1]
    got = [b for b in s.blocks if b.edited]
    assert len(got) == 1 and (got[0].text, got[0].scenes, got[0].source_start) == (mine.text, mine.scenes, 200)

def test_cast_merges_notebook_and_film_characters():
    llm = FakeLLM(review_llm_hook)
    nb = Notebook(characters=[NotebookCharacter(name="Tiểu Minh", arc="đã rời làng")])
    _build(llm, notebook=nb, characters=[FilmCharacter(name="Tiểu Minh", role="nhân vật chính"),
                                         FilmCharacter(name="Lão Trương", role="trưởng làng")])
    cast = llm.prompts[0].split("Nhân vật:\n", 1)[1].split("\n\n", 1)[0].splitlines()
    assert cast == ["- Tiểu Minh: đã rời làng", "- Lão Trương: trưởng làng"]

def test_unknown_template_falls_back_to_first():
    first = templates.load()["styles"][0]
    assert templates.prompt("styles", "khong_con") == first["prompt"]
    assert templates.label("styles", "khong_con") == first["label"]
