"""The review flow end to end with fakes: script -> scenes -> tts -> assemble -> render."""
import subprocess
import numpy as np
from autosub import media, projects, store
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
    projects.save(proj)
    assert flows._title(store.load(p.id)) == "Phim thử\\NTẬP 1 · PHẦN 1"
