from autosub import projects, store
from autosub.models import FilmCharacter, NotebookCharacter
from autosub.storage import get_store
from tests.fakes import review_llm_hook
from tests.review_helpers import ReviewRig, review_rig  # noqa: F401  (fixture)

def test_film_flow_with_subtitles_skips_asr(review_rig):
    job = review_rig.film_done()
    assert job.state == "done" and review_rig.asr.calls == 0
    assert [s["source"] for s in store.load_json(job.id, "transcript.json")][0] == "Anh đi đâu vậy?"
    assert store.load_json(job.id, "characters.json")[0]["name"] == "Tiểu Minh"
    assert store.load_json(job.id, "summary.json")["chunks"][0]["events"]
    assert "Dùng phụ đề có sẵn (vie)" in get_store().get_bytes(f"jobs/{job.id}/log.txt").decode()
    n = len(review_rig.llm.prompts)
    assert review_rig.film_done().state == "done" and len(review_rig.llm.prompts) == n      # every step cached

def test_film_flow_without_subtitles_uses_asr(tmp_path):
    rig = ReviewRig(tmp_path, subtitles=None)
    job = rig.film_done()
    assert job.state == "done" and rig.asr.calls == 1
    assert "你好世界" in "".join(s["source"] for s in store.load_json(job.id, "transcript.json"))

def test_film_flow_empty_transcript_warns(tmp_path):
    rig = ReviewRig(tmp_path, subtitles="WEBVTT\n\n00:00:01.000 --> 00:00:03.000\ntryray.app\n")
    job = rig.film_done()
    assert job.state == "done" and job.warnings[0].startswith("Không có lời thoại")
    assert store.load_json(job.id, "transcript.json") == []
    assert store.load_json(job.id, "characters.json") == [] and store.load_json(job.id, "summary.json") == {"chunks": []}
    assert rig.llm.prompts == []

def test_summary_times_clamped(review_rig):
    def hook(prompt, schema):
        if "events" in schema["properties"]:
            return {"summary": "x", "characters": [], "events": [{"start": -5, "end": 999, "text": "e"}],
                    "highlights": [{"start": 30, "end": 40, "text": "ngoài đoạn"}]}
        return review_llm_hook(prompt, schema)
    review_rig.llm.hook = hook
    job = review_rig.film_done()
    c = store.load_json(job.id, "summary.json")["chunks"][0]
    assert (c["start"], c["end"]) == (0, job.info.duration)
    assert [(e["start"], e["end"]) for e in c["events"]] == [(0, job.info.duration)]
    assert c["highlights"] == []
    assert "SPAN 0.0" in review_rig.llm.prompts[-1] and "[1.0] Anh đi đâu vậy?" in review_rig.llm.prompts[-1]

def test_characters_prompt_includes_known_names(review_rig):
    p = projects.get(review_rig.project.id)
    p.review.notebook.characters = [NotebookCharacter(name="Tiểu Minh", role="em trai")]
    projects.save(p)
    review_rig.film_done()
    prompt = review_rig.llm.prompts[0]
    assert "Nhân vật đã biết" in prompt and "Tiểu Minh" in prompt and "Phim thử" in prompt and "Hán-Việt" in prompt

def test_known_characters_grow_across_episodes(review_rig):
    first = review_rig.film_done()
    store.save_json(first.id, "characters.json", [FilmCharacter(name="Lão Trương", role="trưởng làng").model_dump()])
    second = review_rig.add_film(episode_index=1)
    job = review_rig.run(second.id, mode="auto")
    assert "Lão Trương" in review_rig.llm.prompts[-2]                     # characters prompt of episode 2
    assert [c["name"] for c in store.load_json(job.id, "characters.json")] == ["Tiểu Minh", "Lão Trương"]
