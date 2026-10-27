"""Audio-story flow end to end with FakeTTS: parse -> tts -> mix -> render over a normalized looped background."""
import subprocess
import threading
import time
import pytest
from autosub import config, media, pipeline, proc, projects, store, workdir
from autosub.audio import background, flow as audio_flow
from autosub.projects import AudioProject
from autosub.storage import get_store
from autosub.workdir import WorkDir
from tests.fakes import FakeTTS
from tests.fixtures import make_video

TXT = "Ngày xưa có một cô bé. Cô sống ở làng.\n\nMột hôm cô đi chợ!"
SRT = "1\n00:00:03,000 --> 00:00:04,000\n<i>Xin chào</i>\n"

@pytest.fixture
def rig(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "FFMPEG_PRESET", "ultrafast")
    tts = FakeTTS(sec_per_char=0.03)
    engines = pipeline.Engines(tts=lambda name: tts)
    p = projects.create("Truyện thử", kind="audio", audio=AudioProject())
    return {"tmp": tmp_path, "pid": p.id, "engines": engines, "tts": tts}

def with_background(rig, ready=True):
    pid = rig["pid"]
    src = make_video(rig["tmp"] / "bg.mp4", seconds=2, size=(320, 180), with_text=False)
    key = projects.bg_key(pid, ".mp4")
    get_store().put_file(key, src)
    projects.update(pid, lambda p: setattr(p.audio, "background", key))
    if ready:
        background.normalize(pid, threading.Event(), lambda pct: None)
        assert projects.get(pid).audio.background_state == "ready"

def part(rig, name="chuong-1.txt", text=TXT, index=1):
    return audio_flow.new_part(rig["pid"], name, text.encode(), index)

def run(rig, jid, **kw):
    return pipeline.run(jid, mode="auto", engines=rig["engines"], **kw)

def test_audio_flow_txt_end_to_end(rig):
    with_background(rig)
    job = part(rig)
    assert job.kind == "audio" and job.name == "chuong-1" and job.audio_part.script_kind == "txt"
    assert run(rig, job.id).state == "done"
    lines = store.load_json(job.id, "lines.json")
    assert [l["text"] for l in lines] == ["Ngày xưa có một cô bé.", "Cô sống ở làng.", "Một hôm cô đi chợ!"]
    meta = store.load_json(job.id, "meta.json")
    assert meta["chars"] == sum(len(l["text"]) for l in lines)
    out = media.probe(WorkDir(job.id).fetch("output.mp4"))
    assert out.width == 320 and out.has_audio
    assert abs(out.duration - meta["duration"]) <= 1.1
    assert meta["duration"] > 2      # longer than the 2 s background: it was looped
    assert store.load(job.id).audio_meta == {"duration": meta["duration"], "chars": meta["chars"]}  # for the view

def test_audio_flow_with_music(rig):
    with_background(rig)
    music = make_video(rig["tmp"] / "m.mp4", seconds=1, size=(64, 64), with_text=False)
    mkey = projects.music_key(rig["pid"], ".m4a")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(music), "-vn", "-c:a", "copy",
                    str(rig["tmp"] / "m.m4a")], check=True)
    get_store().put_file(mkey, rig["tmp"] / "m.m4a")
    projects.update(rig["pid"], lambda p: setattr(p.audio, "music", mkey))
    job = part(rig)
    assert run(rig, job.id).state == "done"
    mix = media.probe_audio_duration(WorkDir(job.id).fetch("mix.m4a"))
    assert abs(mix - store.load_json(job.id, "meta.json")["duration"]) < 0.2   # music loops, cut to the voice

def test_audio_flow_srt_uses_cue_times(rig):
    with_background(rig)
    job = part(rig, "a.srt", SRT)
    assert run(rig, job.id).state == "done"
    assert store.load_json(job.id, "meta.json")["duration"] >= 4

def test_empty_script_fails_at_parse(rig):
    job = part(rig, "rong.txt", "\n\n  \n")
    with pytest.raises(Exception):
        run(rig, job.id)
    job = store.load(job.id)
    assert job.state == "error" and job.steps["parse"].status == "error"
    assert "Kịch bản không có nội dung" in job.error

def test_render_waits_for_background(rig):
    with_background(rig)
    projects.update(rig["pid"], lambda p: setattr(p.audio, "background_state", "processing"))
    job = part(rig)
    res = {}
    t = threading.Thread(target=lambda: res.setdefault("job", run(rig, job.id)))
    t.start()
    deadline = time.time() + 60
    while store.load(job.id).current_step != "render" and time.time() < deadline:
        time.sleep(0.1)
    time.sleep(0.5)
    assert t.is_alive() and store.load(job.id).current_step == "render"
    projects.update(rig["pid"], lambda p: setattr(p.audio, "background_state", "ready"))
    t.join(30)
    assert res["job"].state == "done"

def test_render_waiting_is_cancellable(rig):
    with_background(rig, ready=False)
    projects.update(rig["pid"], lambda p: setattr(p.audio, "background_state", "processing"))
    job = part(rig)
    cancel = threading.Event()
    err = {}

    def go():
        try:
            run(rig, job.id, cancel=cancel)
        except proc.Cancelled as e:
            err["e"] = e
    t = threading.Thread(target=go)
    t.start()
    deadline = time.time() + 60
    while store.load(job.id).current_step != "render" and time.time() < deadline:
        time.sleep(0.1)
    cancel.set()
    t.join(10)
    assert not t.is_alive() and "e" in err and store.load(job.id).state == "cancelled"

@pytest.mark.parametrize("state", ["error", "none"])
def test_render_fails_without_background(rig, state):
    if state == "error":
        with_background(rig, ready=False)
        projects.update(rig["pid"], lambda p: (setattr(p.audio, "background_state", "error"),
                                               setattr(p.audio, "background_error", "hỏng")))
    job = part(rig)
    with pytest.raises(RuntimeError):
        run(rig, job.id)
    job = store.load(job.id)
    assert job.state == "error" and job.steps["render"].status == "error" and "video nền" in job.error
    assert job.steps["mix"].status == "done"

def test_changing_settings_marks_parts_stale(rig):
    from autosub import api
    with_background(rig)
    job = part(rig)
    run(rig, job.id)
    stale = lambda: api._stale_from(store.load(job.id), store.names(job.id))  # noqa: E731
    assert stale() is None
    projects.update(rig["pid"], lambda p: setattr(p.audio, "background_etag", "x"))
    assert stale() == "render"
    projects.update(rig["pid"], lambda p: setattr(p.audio, "music_volume", 0.3))
    assert stale() == "mix"
    projects.update(rig["pid"], lambda p: setattr(p.audio, "voice", "khac"))
    assert stale() == "tts"
    get_store().put_bytes(store.key(job.id, "script.txt"), b"Khac.")
    assert stale() == "parse"

def test_normalize_error_sets_state(rig):
    pid = rig["pid"]
    key = projects.bg_key(pid, ".mp4")
    get_store().put_bytes(key, b"not a video")
    projects.update(pid, lambda p: setattr(p.audio, "background", key))
    with pytest.raises(Exception):
        background.normalize(pid, threading.Event(), lambda pct: None)
    a = projects.get(pid).audio
    assert a.background_state == "error" and a.background_error

def test_local_loop_refetches_on_new_etag(rig):
    with_background(rig)
    pid = rig["pid"]
    p1 = background.local_loop(pid)
    m1 = p1.stat().st_mtime_ns
    assert background.local_loop(pid).stat().st_mtime_ns == m1        # cached
    get_store().put_bytes(projects.bg_loop_key(pid), p1.read_bytes() + b"\0")
    etag = get_store().stat(projects.bg_loop_key(pid)).etag
    projects.update(pid, lambda p: setattr(p.audio, "background_etag", etag))
    assert background.local_loop(pid).stat().st_size == p1.stat().st_size and p1.stat().st_mtime_ns != m1

def test_evict_keeps_pinned_project_dirs_and_uploads():
    root = config.WORK_DIR
    for d in ["_projects/a", "_projects/b", "_uploads", "job1"]:
        (root / d).mkdir(parents=True)
        (root / d / "f").write_bytes(b"x" * 1000)
    with workdir.pinned("_projects/a"):
        removed = workdir.evict(max_bytes=0)
    assert set(removed) >= {"_projects/b", "job1"}
    assert (root / "_projects/a/f").exists() and (root / "_uploads/f").exists()

@pytest.mark.slow
def test_render_does_not_reencode(rig, monkeypatch):
    with_background(rig)
    calls = []
    real = proc.run_ffmpeg
    monkeypatch.setattr(proc, "run_ffmpeg", lambda args, **kw: (calls.append(args), real(args, **kw))[1])
    job = part(rig)
    assert run(rig, job.id).state == "done"
    render_args = calls[-1]
    assert "-c:v" in render_args and render_args[render_args.index("-c:v") + 1] == "copy"
    assert "-stream_loop" in render_args

    def codec(path):
        return subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                               "stream=codec_name,profile,width,height", "-of", "csv=p=0", str(path)],
                              capture_output=True, text=True, check=True).stdout.strip()
    assert codec(WorkDir(job.id).fetch("output.mp4")) == codec(background.local_loop(rig["pid"]))


def test_parse_writes_chars_before_tts(rig):
    """The view shows the script length (and the > 500 000 chars warning) as soon as parse is done, even when
    tts then fails."""
    from autosub import api
    job = part(rig)

    class Broken:
        def synth(self, *a, **k):
            raise RuntimeError("mạng lỗi")
        def __getattr__(self, name):
            raise RuntimeError("mạng lỗi")
    rig["engines"] = pipeline.Engines(tts=lambda name: Broken())
    with pytest.raises(RuntimeError, match="TTS lỗi"):
        run(rig, job.id)
    j = store.load(job.id)
    assert j.steps["parse"].status == "done" and j.steps["tts"].status == "error"
    lines = store.load_json(job.id, "lines.json")
    assert j.audio_meta == {"duration": None, "chars": sum(len(l["text"]) for l in lines)}
    assert api._view(j)["meta"] == {"duration": None, "chars": sum(len(l["text"]) for l in lines)}
