from autosub import pipeline, prune, store
from autosub.storage import get_store
from tests.test_pipeline import Rig

def test_prune_frees_intermediates_and_keeps_results(tmp_path):
    rig = Rig(tmp_path)
    rig.run(mode="auto")
    before = store.object_sizes(rig.job.id)
    freed = prune.prune(rig.job.id)
    after = store.object_sizes(rig.job.id)
    assert freed == sum(before[n] for n in prune.PRUNABLE if n in before) > 0
    for n in prune.PRUNABLE:
        assert n not in after
    for keep in ("output.mp4", "subs.srt", "voice.wav", "source.mp4", "no_vocals.wav", "vocals16k.wav", "segments.json"):
        assert keep in after, keep
    assert set(store.load(rig.job.id).pruned) == {n for n in prune.PRUNABLE if n in before}

def test_after_prune_nothing_heavy_reruns(tmp_path):
    rig = Rig(tmp_path)
    rig.run(mode="auto")
    prune.prune(rig.job.id)
    job = rig.run(mode="auto")
    assert job.state == "done" and len(rig.sep_calls) == 1 and rig.asr.calls == 1

def test_pruned_input_is_regenerated_cheaply(tmp_path):
    rig = Rig(tmp_path)
    rig.run(mode="auto")
    prune.prune(rig.job.id)
    job = store.load(rig.job.id); job.settings.bg_volume_db = -6; store.save(job)   # mix reruns, needs voice_raw.wav
    job = rig.run(mode="auto")
    assert job.state == "done" and len(rig.sep_calls) == 1
    assert "voice_raw.wav" in store.object_sizes(job.id) and "voice_raw.wav" not in job.pruned

def test_rerun_separation_after_prune_rebuilds_audio(tmp_path):
    rig = Rig(tmp_path)
    rig.run(mode="auto")
    prune.prune(rig.job.id)
    job = rig.run(mode="auto", from_step="separate")
    assert job.state == "done" and len(rig.sep_calls) == 2
    assert "audio.wav" in store.object_sizes(job.id)

def test_auto_prune_on_done(tmp_path):
    store.save_app_settings({"auto_prune": True})
    rig = Rig(tmp_path)
    rig.run(mode="auto")
    assert "audio.wav" not in store.object_sizes(rig.job.id)
    assert get_store().stat(f"jobs/{rig.job.id}/output.mp4") is not None
