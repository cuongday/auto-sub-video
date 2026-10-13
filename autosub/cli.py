"""Command line (inside the container): autosub run /videos/clip.mp4 --lang zh --out /videos/clip.vi.mp4"""
import argparse
import shutil
import sys
from . import media, pipeline, store, workdir
from .models import JobSettings, Region

def main(argv=None):
    ap = argparse.ArgumentParser(prog="autosub")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="Chạy thẳng một video đến thành phẩm")
    r.add_argument("video")
    r.add_argument("--lang", choices=["zh", "en"], default="zh")
    r.add_argument("--asr-model", default="")
    r.add_argument("--region", default="0.05,0.8,0.9,0.14", help="x,y,w,h theo tỉ lệ 0-1")
    r.add_argument("--cover", choices=["blur", "blur_dim", "solid"], default="blur_dim")
    r.add_argument("--llm", choices=["gemini", "openai"], default="gemini")
    r.add_argument("--llm-model", default="")
    r.add_argument("--notes", default="", help="Ghi chú cho người dịch")
    r.add_argument("--tts", choices=["edge", "vieneu"], default="edge")
    r.add_argument("--voice", default="")
    r.add_argument("--bg-db", type=float, default=0.0)
    r.add_argument("--out", help="Copy output.mp4 tới đây")
    a = ap.parse_args(argv)

    from pathlib import Path
    src = Path(a.video).expanduser().resolve()
    x, y, w, h = (float(v) for v in a.region.split(","))
    job = store.create(src.name, "source" + src.suffix.lower())
    w = workdir.WorkDir(job.id)
    shutil.copyfile(src, w.local(job.source))
    w.push(job.source)
    job.info = media.probe(src)
    job.settings = JobSettings(lang=a.lang, asr_model=a.asr_model, region=Region(x=x, y=y, w=w, h=h), cover=a.cover,
                               llm_provider=a.llm, llm_model=a.llm_model, translator_notes=a.notes,
                               tts_engine=a.tts, tts_voice=a.voice, bg_volume_db=a.bg_db)
    store.save(job)
    print(f"Job {job.id} -> MinIO {workdir.job_prefix(job.id)}")
    last = {"step": None}

    def progress(step, pct):
        if step != last["step"]:
            print(f"\n[{step}]", end="", flush=True); last["step"] = step
        print(f" {pct:.0%}", end="", flush=True)

    try:
        pipeline.run(job.id, mode="auto", progress=progress)
    except Exception as e:  # noqa: BLE001
        print(f"\nLỗi: {e}", file=sys.stderr)
        return 1
    print(f"\nXong: {workdir.job_prefix(job.id)}output.mp4")
    if a.out:
        w.fetch("output.mp4")
        shutil.copyfile(w.local("output.mp4"), a.out)
        print(f"Đã lưu: {a.out}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
