"""The review flow end to end with fakes: script -> scenes -> tts -> assemble -> render."""
import subprocess
import numpy as np
import pytest
from autosub import media, projects, store
from autosub.models import Episode
from autosub.review import compose
from autosub.review.narration import BLOCK_GAP, SENT_GAP
from autosub.storage import get_store
from autosub.workdir import WorkDir
from tests.review_helpers import ReviewRig, review_rig  # noqa: F401  (fixture)

def narration_total(jid):
    by_block = {}
    for n in store.load_json(jid, "narration.json"):
        by_block.setdefault(n["block"], []).append(n["dur"])
    return sum(sum(d) + SENT_GAP * (len(d) - 1) + BLOCK_GAP for d in by_block.values())

def fetch(jid, name):
    return WorkDir(jid).fetch(name)

def test_part_end_to_end(review_rig):
    review_rig.film_done()
    p = review_rig.part()
    assert review_rig.run(p.id, mode="review").state == "awaiting_review"
    assert review_rig.run(p.id, mode="auto").state == "done"
    out = media.probe(fetch(p.id, "output.mp4"))
    assert (out.width, out.height) == (1080, 1920) and out.has_audio
    assert abs(out.duration - narration_total(p.id)) < 0.3
    srt = get_store().get_bytes(store.key(p.id, "subs.srt")).decode()
    assert "chữ" in srt and "VI " not in srt
    ass = get_store().get_bytes(store.key(p.id, "subs.ass")).decode()
    assert "Phim thử\\NPHẦN 1" in ass
    plan = store.load_json(p.id, "shots.json")
    assert abs(sum(s["end"] - s["start"] for s in plan) - narration_total(p.id)) < 0.01
    assert all(store.exists(p.id, n) for n in ["voice_raw.wav", "voice.wav", "mix.m4a"])

def test_original_audio_is_not_used(review_rig):
    review_rig.film_done()                    # film source carries a 440 Hz tone, FakeTTS speaks at 220 Hz
    p = review_rig.part()
    review_rig.run(p.id, mode="auto")
    pcm = media.decode_mono(fetch(p.id, "output.mp4"), 44100)
    spec = np.abs(np.fft.rfft(pcm))
    freqs = np.fft.rfftfreq(len(pcm), 1 / 44100)
    peak = lambda f: spec[(freqs > f - 5) & (freqs < f + 5)].max()  # noqa: E731
    assert peak(220) > 50 * peak(440)

def test_16x9_without_subtitles(review_rig):
    review_rig.film_done()
    p = review_rig.part()
    job = store.load(p.id)
    job.review.aspect, job.review.subtitles = "16:9", False
    store.save(job)
    assert review_rig.run(p.id, mode="auto").state == "done"
    out = media.probe(fetch(p.id, "output.mp4"))
    assert (out.width, out.height) == (1920, 1080) and out.has_audio
    assert not store.exists(p.id, "subs.ass") and not store.exists(p.id, "subs.srt")

def test_music_change_reruns_assemble_not_tts(review_rig, tmp_path, monkeypatch):
    review_rig.film_done()
    p = review_rig.part()
    review_rig.run(p.id, mode="auto")
    before = store.load(p.id)
    music = tmp_path / "music.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=660:duration=3", str(music)], check=True)
    proj = projects.get(review_rig.project.id)
    proj.review.music = projects.music_key(proj.id, ".wav")
    get_store().put_file(proj.review.music, music)
    projects.save(proj)
    review_rig.tts.calls.clear()
    calls = []
    monkeypatch.setattr(compose, "render_shot", lambda *a, **k: calls.append(a) or a[3])
    job = review_rig.run(p.id, mode="auto")
    assert job.state == "done" and review_rig.tts.calls == [] and calls == []      # shots reused from storage
    assert job.steps["tts"].hash == before.steps["tts"].hash
    assert job.steps["assemble"].hash != before.steps["assemble"].hash
    pcm = media.decode_mono(fetch(p.id, "output.mp4"), 44100)
    spec, freqs = np.abs(np.fft.rfft(pcm)), np.fft.rfftfreq(len(pcm), 1 / 44100)
    assert spec[(freqs > 655) & (freqs < 665)].max() > 5 * np.median(spec)          # the music is in the mix

def test_script_edit_after_render_reencodes_changed_shots_only(review_rig, monkeypatch):
    review_rig.film_done()
    p = review_rig.part()
    review_rig.run(p.id, mode="auto")
    old = set(keys(p.id))
    sc = store.load_json(p.id, "script.json")
    sc["blocks"][1]["text"] = "Câu mới hoàn toàn. Và câu nữa."
    store.save_json(p.id, "script.json", sc)
    calls, real = [], compose.render_shot
    monkeypatch.setattr(compose, "render_shot", lambda *a, **k: calls.append(a[1:3]) or real(*a, **k))
    assert review_rig.run(p.id, mode="auto", from_step="tts").state == "done"
    new = keys(p.id)
    changed = [k for k in dict.fromkeys(new) if k not in old]
    assert changed and len(calls) == len(changed) < len(new)
    assert abs(media.probe(fetch(p.id, "output.mp4")).duration - narration_total(p.id)) < 0.3

def keys(jid):
    """(start, frames) of each planned shot: what names an encoded shot."""
    plan = store.load_json(jid, "shots.json")
    return list(zip([round(s["start"], 3) for s in plan], compose.frame_counts([s["end"] - s["start"] for s in plan])))

def test_title_single_and_series(review_rig):
    from autosub.review import flows
    p = review_rig.part()
    assert flows._title(store.load(p.id)) == "Phim thử\\NPHẦN 1"
    proj = projects.get(review_rig.project.id)
    proj.review.movie.type = "series"
    proj.review.episodes = [Episode(name=f"Tập {i}", slug=f"tap-{i}", embed="e") for i in (1, 2)]
    projects.save(proj)
    assert flows._title(store.load(p.id)) == "Phim thử\\NTẬP 1 · PHẦN 1"

def test_series_position_counts_every_episode(review_rig):
    from autosub.review import flows, parts
    proj = projects.get(review_rig.project.id)
    proj.review.movie.type = "series"
    proj.review.episodes = [Episode(name=f"Tập {i}", slug=f"tap-{i}", embed="e") for i in (1, 2, 3)]
    projects.save(proj)
    ep3 = review_rig.add_film(episode_index=2)
    first = parts.create_parts(store.load(review_rig.film.id), [])[0]
    last = parts.create_parts(store.load(ep3.id), [])[0]
    # episode 2 has no parts yet: neither the part count nor "last" may come from the parts made so far
    assert flows._position(store.load(first.id), store.load(review_rig.film.id)) == (3, False)
    assert flows._position(store.load(last.id), ep3) == (3, True)
    proj.review.parts_per_episode = 2
    projects.save(proj)
    assert flows._position(store.load(first.id), store.load(review_rig.film.id))[0] == 6
    proj.review.episodes = proj.review.episodes[:1]           # a one-episode "series" is a single movie
    projects.save(proj)
    assert flows._title(store.load(first.id)) == "Phim thử\\NPHẦN 1"

def test_kept_ending_shows_no_footage_past_the_story(review_rig):
    from autosub.pipeline import make_ctx
    from autosub.review import flows
    review_rig.film_done()
    p = review_rig.part()                                     # the only part is the last; spoil_ending is off
    review_rig.run(p.id, mode="review")
    sc = store.load_json(p.id, "script.json")
    for b in sc["blocks"]:
        b["source_end"] = 8.0 if b["kind"] == "than" else b["source_end"]     # the body stops telling at 8 s
    store.save_json(p.id, "script.json", sc)
    assert review_rig.run(p.id, mode="auto").state == "done"
    plan = store.load_json(p.id, "shots.json")
    assert plan and all(s["end"] <= 8.0 + 1e-6 for s in plan), plan    # hook/ket/fill never show the climax
    job = store.load(p.id)
    h = flows.review_step_hash(make_ctx(job), "assemble")
    job.review.spoil_ending = True
    assert flows.review_step_hash(make_ctx(job), "assemble") != h

def test_part_outside_every_summary_fails_clearly(review_rig):
    review_rig.film_done()
    p = review_rig.part()
    store.save_json(review_rig.film.id, "summary.json", {"chunks": [{"start": 100, "end": 200, "summary": "Sau này."}]})
    with pytest.raises(RuntimeError, match="Không có tóm tắt cho đoạn phim này"):
        review_rig.run(p.id, mode="review")

def test_hook_and_ending_without_scenes_show_no_footage_before_the_dialogue(review_rig):
    review_rig.film_done()
    p = review_rig.part()
    review_rig.run(p.id, mode="review")
    lines = store.load_json(review_rig.film.id, "transcript.json")
    store.save_json(review_rig.film.id, "transcript.json", [l for l in lines if l["start"] >= 6])   # first line at 12 s
    sc = store.load_json(p.id, "script.json")
    for b in sc["blocks"]:
        if b["kind"] in ("hook", "ket"):
            b["scenes"], b["source_start"], b["source_end"] = [], None, None
    store.save_json(p.id, "script.json", sc)
    assert review_rig.run(p.id, mode="auto").state == "done"
    ids = {b["id"] for b in sc["blocks"] if b["kind"] in ("hook", "ket")}
    plan = [s for s in store.load_json(p.id, "shots.json") if s["block"] in ids]
    assert plan and all(s["start"] >= 10 - 1e-6 for s in plan), plan       # no studio logo under the hook

def test_hook_toggle_changes_the_script_hash(review_rig):
    from autosub.pipeline import make_ctx
    from autosub.review import flows
    review_rig.film_done()
    p = review_rig.part()
    review_rig.run(p.id, mode="review")
    job = store.load(p.id)
    h = flows.review_step_hash(make_ctx(job), "script")
    job.review.use_hook = False
    assert flows.review_step_hash(make_ctx(job), "script") != h

def test_layout_change_reruns_assemble_and_render_only(review_rig):
    from autosub.models import Region
    review_rig.film_done()
    p = review_rig.part()
    before = review_rig.run(p.id, mode="auto")
    job = store.load(p.id)
    job.review.sub_region = Region(x=0.1, y=0.5, w=0.8, h=0.1)
    job.review.show_title = False
    store.save(job)
    review_rig.tts.calls.clear()
    review_rig.llm.prompts.clear()
    job = review_rig.run(p.id, mode="auto")
    assert job.state == "done" and review_rig.tts.calls == [] and review_rig.llm.prompts == []
    assert [job.steps[s].hash == before.steps[s].hash for s in ("script", "scenes", "tts", "assemble", "render")] == \
        [True, True, True, False, False]
    ass = get_store().get_bytes(store.key(p.id, "subs.ass")).decode()
    assert "\\pos(540,1056)" in ass and "PHẦN 1" not in ass

def test_old_parts_keep_their_assemble_hash_and_bare_9x16_burns_nothing(review_rig, monkeypatch):
    from autosub.pipeline import make_ctx
    from autosub.review import flows
    review_rig.film_done()
    p = review_rig.part()
    review_rig.run(p.id, mode="review")
    job = store.load(p.id)
    args, real = [], flows._h
    monkeypatch.setattr(flows, "_h", lambda *a: args.append(a) or real(*a))
    flows.review_step_hash(make_ctx(job), "assemble")
    assert len(args[-1]) == 12               # default layout: the same 12 inputs as before, old parts stay fresh
    job.review.show_title = False
    flows.review_step_hash(make_ctx(job), "assemble")
    assert args[-1][-1] == {"show_title": False}
    job.review.subtitles = False
    store.save(job)
    assert review_rig.run(p.id, mode="auto").state == "done"
    assert not store.exists(p.id, "subs.ass")                                    # nothing to burn
    with pytest.raises(RuntimeError, match="Dựng video trước"):
        store.save_json(p.id, "shots.json", [])
        flows.preview(store.load(p.id), 1.0)
