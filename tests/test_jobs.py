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
