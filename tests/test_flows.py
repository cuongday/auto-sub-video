"""Each job kind runs its own flow (steps, runners, hashes, outputs); "sub" is the subtitle flow."""
import sys
import pytest
from autosub import eta, pipeline, store, workdir
from autosub.models import FILM_STEPS, REVIEW_STEPS, STEPS, STEPS_BY_KIND, Job, StepState, VideoInfo
from tests.test_api import client  # noqa: F401  (fixture)

def test_steps_by_kind():
    assert STEPS_BY_KIND == {"sub": STEPS, "film": FILM_STEPS, "review": REVIEW_STEPS}

def test_old_job_json_without_kind_is_sub():
    j = Job.model_validate({"id": "old", "name": "x", "created": 0, "source": "source.mp4"})
    assert j.kind == "sub" and list(j.steps) == STEPS

def test_create_review_job_has_review_steps():
    j = store.create("p1", "source.mp4", kind="review")
    assert list(j.steps) == REVIEW_STEPS and store.load(j.id).kind == "review"
    assert list(store.load(j.id).steps) == REVIEW_STEPS

def test_create_film_job_has_film_steps():
    assert list(store.create("f", kind="film").steps) == FILM_STEPS

def test_flow_for_sub():
    flow = pipeline.flow_for(store.create("a"))
    assert flow is pipeline.SUB_FLOW and flow.steps == STEPS
    assert flow.review_stop == "translate" == pipeline.REVIEW_STOP
    assert flow.overwrites == {"segment", "translate"}
    assert flow.runners is pipeline.RUNNERS and flow.step_hash is pipeline.step_hash

def test_unregistered_kind_is_a_clear_error(monkeypatch):
    monkeypatch.delitem(pipeline._FLOWS, "review", raising=False)
    monkeypatch.setitem(sys.modules, "autosub.review.flows", None)      # module not there
    with pytest.raises(LookupError):
        pipeline.flow_for(store.create("r", kind="review"))

def toy_flow(calls: list, **kw) -> pipeline.Flow:
    def runner(name):
        def run(ctx):
            calls.append(name)
            store.save_json(ctx.job.id, f"{name}.json", {"step": name})
        return run
    return pipeline.Flow(steps=["a", "b"], runners={"a": runner("a"), "b": runner("b")},
                         step_hash=lambda ctx, step: f"h-{step}", inputs=lambda ctx, step: [],
                         pushes=lambda ctx, step: [], outputs=lambda ctx, step: [f"{step}.json"],
                         review_stop="a", overwrites=set(), **kw)

def toy_job(monkeypatch, flow: pipeline.Flow) -> Job:
    monkeypatch.setitem(pipeline._FLOWS, "film", flow)
    monkeypatch.setitem(sys.modules, "autosub.review.flows", None)      # registered kinds need no import
    j = store.create("toy", kind="film")
    j.steps = {"a": StepState(), "b": StepState()}
    store.save(j)
    return j

def test_registered_flow_runs_and_stops_at_review(monkeypatch):
    calls = []
    j = toy_job(monkeypatch, toy_flow(calls))
    job = pipeline.run(j.id, mode="review")
    assert job.state == "awaiting_review"
    assert job.steps["a"].status == "done" and job.steps["b"].status == "pending"
    assert calls == ["a"]
    job = pipeline.run(j.id, mode="auto")
    assert job.state == "done" and job.steps["b"].status == "done"
    assert calls == ["a", "b"]                       # runner a not called again
    assert store.load_json(j.id, "b.json") == {"step": "b"}

def test_after_step_warning_stops_review(monkeypatch):
    calls = []
    flow = toy_flow(calls, after_step=lambda ctx, step: "Có cảnh báo" if step == "b" else None)
    flow.review_stop = None
    j = toy_job(monkeypatch, flow)
    job = pipeline.run(j.id, mode="review")
    assert job.state == "awaiting_review" and job.warnings == ["Có cảnh báo"]
    assert job.steps["b"].status == "done"
    assert pipeline.run(j.id, mode="auto").state == "done"       # auto mode ignores the warning

def test_pins_hold_other_jobs_while_running(monkeypatch):
    seen = []
    flow = toy_flow([], pins=lambda job: ["other"])
    flow.runners["a"] = lambda ctx: (seen.append(dict(workdir._PINNED)), store.save_json(ctx.job.id, "a.json", {}))
    j = toy_job(monkeypatch, flow)
    pipeline.run(j.id, mode="review")
    assert seen and seen[0].get("other") == 1 and seen[0].get(j.id) == 1
    assert "other" not in workdir._PINNED and j.id not in workdir._PINNED

def test_invalidate_from_uses_the_job_flow(monkeypatch):
    j = toy_job(monkeypatch, toy_flow([]))
    for s in j.steps.values():
        s.status, s.hash = "done", "x"
    pipeline.invalidate_from(j, "b")
    assert j.steps["a"].status == "done" and j.steps["b"].status == "pending" and j.steps["b"].hash is None

def test_view_exposes_flow(client):  # noqa: F811
    j = store.create("v")
    flow = client.get(f"/api/jobs/{j.id}").json()["flow"]
    assert flow == {"steps": STEPS, "review_stop": "translate"}

def test_run_rejects_step_not_in_flow(client):  # noqa: F811
    j = store.create("v")
    assert client.post(f"/api/jobs/{j.id}/run", json={"mode": "review", "from_step": "script"}).status_code == 400

def test_eta_basis_and_default_rates_per_kind():
    info = VideoInfo(width=1280, height=720, duration=600, fps=25, has_audio=True)
    sub = store.create("s"); sub.info = info
    film = store.create("f", kind="film"); film.info = info
    assert eta.basis_seconds(sub, "asr") == 600 and eta.basis_seconds(film, "separate") == 600
    review = store.create("r", kind="review")
    assert eta.basis_seconds(review, "script") == 0 and eta.basis_seconds(review, "tts") == 0   # no data yet
    assert eta.DEFAULT_RATE_BY_KIND["film"] == {"probe": 0, "extract": 0.002, "separate": 0.45, "asr": 0.25,
                                                "transcript": 0, "characters": 0.002, "summarize": 0.01}
    assert eta.DEFAULT_RATE_BY_KIND["review"] == {"script": 0.01, "scenes": 0.08, "tts": 0.6, "assemble": 0.01,
                                                  "render": 0.25}
    assert eta.DEFAULT_RATE_BY_KIND["sub"] == eta.DEFAULT_RATE

def test_eta_review_basis_from_part_and_minutes():
    from types import SimpleNamespace         # Job gains part/review in a later task
    j = SimpleNamespace(kind="review", info=None, part=SimpleNamespace(start=60, end=1260),
                        review=SimpleNamespace(minutes=5))
    assert eta.basis_seconds(j, "script") == 1200 and eta.basis_seconds(j, "scenes") == 1200
    assert eta.basis_seconds(j, "tts") == 300 and eta.basis_seconds(j, "render") == 300

def test_eta_rates_are_kept_per_kind():
    info = VideoInfo(width=1280, height=720, duration=100, fps=25, has_audio=True)
    for kind, secs in (("sub", 56), ("film", 106)):
        j = store.create("x", kind=kind)
        j.info = info
        j.steps["separate"].status, j.steps["separate"].seconds = "done", secs
        store.save(j)
    assert eta.rates()["separate"] == 0.5 and eta.rates("sub")["separate"] == 0.5
    assert eta.rates("film")["separate"] == 1.0
