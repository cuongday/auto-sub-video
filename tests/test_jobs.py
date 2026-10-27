import time
from autosub import jobs, pipeline, store
from tests.fakes import FakeASR, FakeLLM, FakeTTS, fake_separate
from tests.fixtures import make_video
from tests.helpers import new_job

def engines():
    return pipeline.Engines(separate=fake_separate(), asr=lambda l, m: FakeASR(), llm=lambda p, m: FakeLLM(),
                            tts=lambda n: FakeTTS())

def wait(jid, states, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if store.load(jid).state in states:
            return store.load(jid)
        time.sleep(0.1)
    raise AssertionError(store.load(jid).state)

def test_queue_runs_jobs_in_order(tmp_path):
    q = jobs.JobQueue(engines)
    sub = q.subscribe()
    a = new_job(make_video(tmp_path / "a.mp4", 3))
    b = new_job(make_video(tmp_path / "b.mp4", 3))
    assert q.submit(a.id, "auto") and q.submit(b.id, "review")
    assert not q.submit(a.id, "auto")
    assert wait(a.id, {"done"}).state == "done"
    assert wait(b.id, {"awaiting_review"}).state == "awaiting_review"
    evs = []
    while not sub.empty():
        evs.append(sub.get())
    states = [(e["job"], e["state"]) for e in evs if e["type"] == "state"]
    assert states.index((a.id, "done")) < states.index((b.id, "running"))
    assert any(e["type"] == "progress" and e["step"] == "render" for e in evs)

def test_cancel_queued(tmp_path):
    q = jobs.JobQueue(engines)
    a = new_job(make_video(tmp_path / "a.mp4", 3))
    b = new_job(make_video(tmp_path / "b.mp4", 3))
    q.submit(a.id, "auto"); q.submit(b.id, "auto")
    assert q.cancel(b.id)
    wait(a.id, {"done"})
    time.sleep(0.3)
    assert store.load(b.id).state == "cancelled"

def test_reset_interrupted():
    j = store.create("a", "/x"); j.state = "running"; j.steps["asr"].status = "running"; store.save(j)
    jobs.reset_interrupted()
    j = store.load(j.id)
    assert j.state == "interrupted" and j.steps["asr"].status == "pending"

# ---------------------------------------------------------------- audio lane

import sys
import threading
import pytest
from autosub import proc
from autosub.models import AUDIO_STEPS, StepState

GATES: dict[str, threading.Event] = {}

@pytest.fixture
def audio_flow(monkeypatch):
    """A fake 'audio' flow whose first step blocks on a per-job gate (and honours cancel)."""
    def block(ctx):
        gate = GATES.setdefault(ctx.job.id, threading.Event())
        while not gate.wait(0.05):
            ctx.check()

    def noop(ctx):
        pass

    flow = pipeline.Flow(steps=list(AUDIO_STEPS), runners={s: (block if s == "parse" else noop) for s in AUDIO_STEPS},
                         step_hash=lambda ctx, step: f"h-{step}", inputs=lambda ctx, step: [],
                         pushes=lambda ctx, step: [], outputs=lambda ctx, step: [],
                         review_stop=None, overwrites=set())
    monkeypatch.setitem(pipeline._FLOWS, "audio", flow)      # restored (removed) on teardown
    GATES.clear()
    yield flow
    for g in GATES.values():
        g.set()
    GATES.clear()

def audio_job(name="a"):
    j = store.create(name, kind="audio")
    GATES[j.id] = threading.Event()
    return j

def wait_for(cond, timeout=10):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return
        time.sleep(0.05)
    raise AssertionError("timed out")

def states(*jids):
    return [store.load(j).state for j in jids]

def test_audio_lane_runs_two_at_once(audio_flow):
    q = jobs.JobQueue(engines)
    a, b, c = audio_job("a"), audio_job("b"), audio_job("c")
    for j in (a, b, c):
        assert q.submit(j.id, "auto")
    assert not q.submit(a.id, "auto")
    wait_for(lambda: sorted(states(a.id, b.id, c.id)).count("running") == 2, timeout=5)
    first = [j for j in (a, b, c) if store.load(j.id).state == "running"]
    third = next(j for j in (a, b, c) if j not in first)
    assert store.load(third.id).state == "queued"
    assert q.running() == {j.id for j in first}
    assert all(q.is_active(j.id) for j in (a, b, c))
    GATES[first[0].id].set()
    assert wait(first[0].id, {"done"}, timeout=10).state == "done"
    wait_for(lambda: store.load(third.id).state == "running")
    for j in (a, b, c):
        GATES[j.id].set()
    for j in (a, b, c):
        assert wait(j.id, {"done"}, timeout=10).state == "done"
    wait_for(lambda: q.running() == set())

def test_cancel_one_audio_job_keeps_other(audio_flow, monkeypatch):
    def boom():
        raise AssertionError("audio lane must not kill every process")
    monkeypatch.setattr(proc, "kill_all", boom)
    q = jobs.JobQueue(engines)
    a, b = audio_job("a"), audio_job("b")
    q.submit(a.id, "auto"); q.submit(b.id, "auto")
    wait_for(lambda: states(a.id, b.id) == ["running", "running"])
    assert q.cancel(a.id)
    assert wait(a.id, {"cancelled", "error"}, timeout=10).state == "cancelled"
    assert store.load(b.id).state == "running"
    GATES[b.id].set()
    assert wait(b.id, {"done", "error", "cancelled"}, timeout=10).state == "done"

def test_cancel_queued_audio_job_never_starts(audio_flow):
    q = jobs.JobQueue(engines)
    a, b, c = audio_job("a"), audio_job("b"), audio_job("c")
    for j in (a, b, c):
        q.submit(j.id, "auto")
    wait_for(lambda: states(a.id, b.id).count("running") == 2)
    assert store.load(c.id).state == "queued"
    assert q.cancel(c.id)
    assert store.load(c.id).state == "cancelled"
    GATES[a.id].set(); GATES[b.id].set()
    wait(a.id, {"done"}); wait(b.id, {"done"})
    wait_for(lambda: q.running() == set())
    assert store.load(c.id).state == "cancelled" and not q.is_active(c.id)

def test_sub_job_not_blocked_by_audio_lane(audio_flow, tmp_path):
    q = jobs.JobQueue(engines)
    a, b = audio_job("a"), audio_job("b")
    q.submit(a.id, "auto"); q.submit(b.id, "auto")
    wait_for(lambda: states(a.id, b.id) == ["running", "running"])
    s = new_job(make_video(tmp_path / "s.mp4", 3))
    assert q.submit(s.id, "review")
    assert wait(s.id, {"awaiting_review", "error"}).state == "awaiting_review"
    assert states(a.id, b.id) == ["running", "running"]
    GATES[a.id].set(); GATES[b.id].set()
    wait(a.id, {"done"}); wait(b.id, {"done"})
    wait_for(lambda: q.running() == set())

def test_submit_task_runs_in_audio_lane_and_cancels(audio_flow):
    q = jobs.JobQueue(engines)
    sub = q.subscribe()
    started, release = threading.Event(), threading.Event()
    seen = {}

    def task(cancel, progress):
        progress(0.5)
        started.set()
        while not release.wait(0.05):
            if cancel.is_set():
                seen["cancelled"] = True
                raise proc.Cancelled()

    assert q.submit_task("bg:p1", task)
    assert started.wait(5)
    assert not q.submit_task("bg:p1", task)                  # key unique while active
    assert "bg:p1" in q.running() and q.is_active("bg:p1")
    assert q.cancel("bg:p1")
    wait_for(lambda: not q.is_active("bg:p1"))
    assert seen.get("cancelled")
    # a finished key can be submitted again; ok and error both reported
    assert q.submit_task("bg:p1", lambda cancel, progress: progress(1.0))
    wait_for(lambda: not q.is_active("bg:p1"))
    assert q.submit_task("bg:p2", lambda cancel, progress: 1 / 0)
    wait_for(lambda: not q.is_active("bg:p2"))
    evs = []
    while not sub.empty():
        evs.append(sub.get())
    tasks = [(e["key"], e["state"]) for e in evs if e["type"] == "task"]
    assert tasks == [("bg:p1", "queued"), ("bg:p1", "running"), ("bg:p1", "cancelled"),
                     ("bg:p1", "queued"), ("bg:p1", "running"), ("bg:p1", "done"),
                     ("bg:p2", "queued"), ("bg:p2", "running"), ("bg:p2", "error")]
    assert any(e["type"] == "task_progress" and e["key"] == "bg:p1" and e["pct"] == 0.5 for e in evs)
    assert next(e for e in evs if e["type"] == "task" and e["state"] == "error")["error"]

def test_resubmit_does_not_save_stale_snapshot(audio_flow, monkeypatch):
    """submit() must not save a job state it read before the previous run finished."""
    calls = []
    flow = audio_flow
    block = flow.runners["parse"]
    monkeypatch.setitem(flow.runners, "parse", lambda ctx: (calls.append(ctx.job.id), block(ctx)))
    q = jobs.JobQueue(engines)
    a = audio_job("a")
    q.submit(a.id, "auto")
    wait_for(lambda: store.load(a.id).state == "running" and store.load(a.id).current_step == "parse")
    real = store.load
    armed = {"on": True}

    def racy_load(jid):
        snap = real(jid)
        if armed["on"] and threading.current_thread() is threading.main_thread():
            armed["on"] = False                     # the previous run finishes between the read and the check
            GATES[a.id].set()
            wait_for(lambda: not q.is_active(a.id))
        return snap
    monkeypatch.setattr(store, "load", racy_load)
    assert q.submit(a.id, "auto")
    monkeypatch.setattr(store, "load", real)
    assert wait(a.id, {"done", "error"}).state == "done"
    wait_for(lambda: not q.is_active(a.id))
    assert calls == [a.id]                          # parse stayed done: the rerun skipped it

def test_main_lane_cancel_spares_audio_processes(audio_flow, monkeypatch):
    def sleeper(secs):
        def run(ctx):
            proc.run(["sleep", str(secs)], cancel=ctx.cancel)
        return run
    monkeypatch.setitem(audio_flow.runners, "parse", sleeper(3))
    film = pipeline.Flow(steps=["a"], runners={"a": sleeper(30)}, step_hash=lambda ctx, step: "h",
                         inputs=lambda ctx, step: [], pushes=lambda ctx, step: [], outputs=lambda ctx, step: [],
                         review_stop=None, overwrites=set())
    monkeypatch.setitem(pipeline._FLOWS, "film", film)
    monkeypatch.setitem(sys.modules, "autosub.review.flows", None)
    m = store.create("m", kind="film"); m.steps = {"a": StepState()}; store.save(m)
    a = audio_job("a")
    q = jobs.JobQueue(engines)
    q.submit(a.id, "auto"); q.submit(m.id, "auto")
    wait_for(lambda: len(proc._LIVE) >= 2)
    assert q.cancel(m.id)
    assert wait(m.id, {"cancelled", "error", "done"}).state == "cancelled"
    assert wait(a.id, {"done", "error", "cancelled"}).state == "done"

def test_resubmitted_task_runs_new_fn_not_stale_one(audio_flow):
    q = jobs.JobQueue(engines, audio_workers=1)
    blocker = audio_job("blocker")
    q.submit(blocker.id, "auto")
    wait_for(lambda: store.load(blocker.id).state == "running")
    ran = []
    assert q.submit_task("bg:x", lambda cancel, progress: ran.append("old"))
    assert q.cancel("bg:x")
    assert q.submit_task("bg:x", lambda cancel, progress: ran.append("new"))
    GATES[blocker.id].set()
    wait(blocker.id, {"done"})
    wait_for(lambda: ran and not q.is_active("bg:x"))
    wait_for(lambda: q.running() == set())
    assert ran == ["new"]
