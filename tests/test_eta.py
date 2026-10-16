from autosub import eta, store
from autosub.models import STEPS

def done_job(duration, secs: dict, **settings):
    j = store.create("x")
    from autosub.models import VideoInfo
    j.info = VideoInfo(width=1280, height=720, duration=duration, fps=25, has_audio=True)
    for k, v in secs.items():
        j.steps[k].status, j.steps[k].seconds = "done", v
    for k, v in settings.items():
        setattr(j.settings, k, v)
    j.state = "done"
    store.save(j)
    return j

def test_rates_are_seconds_per_video_second_after_fixed_cost():
    done_job(100, {"separate": 56, "asr": 55, "render": 31.5})
    done_job(200, {"separate": 106, "asr": 75, "render": 61.5})
    r = eta.rates()
    assert r["separate"] == 0.5 and r["asr"] == 0.2 and r["render"] == 0.3

def test_estimate_remaining_for_a_running_job():
    done_job(100, {"separate": 56, "asr": 55, "translate": 13, "tts": 43, "render": 31.5})
    j = store.create("y")
    from autosub.models import VideoInfo
    j.info = VideoInfo(width=1280, height=720, duration=300, fps=25, has_audio=True)
    for k in ("probe", "extract", "separate"):
        j.steps[k].status = "done"
    j.mode = "auto"
    store.save(j)
    est = eta.estimate(j, current="asr", pct=0.5)
    assert est["steps"]["asr"] == 47.5                  # (0.2 s/s * 300 s + 35 s) * (1 - 0.5)
    assert est["steps"]["render"] == 91.5 and "separate" not in est["steps"]
    assert est["total"] == sum(est["steps"].values())

def test_defaults_without_history_and_review_stops_at_translate():
    j = store.create("z")
    from autosub.models import VideoInfo
    j.info = VideoInfo(width=1280, height=720, duration=60, fps=25, has_audio=True)
    j.mode = "review"
    store.save(j)
    est = eta.estimate(j)
    assert "tts" not in est["steps"] and est["steps"]["separate"] > 0 and est["calibrated"] is False

def test_skipped_separation_costs_nothing():
    j = store.create("w")
    from autosub.models import VideoInfo
    j.info = VideoInfo(width=1280, height=720, duration=60, fps=25, has_audio=True)
    j.settings.separate = False
    store.save(j)
    assert eta.estimate(j)["steps"].get("separate", 0) < 1
