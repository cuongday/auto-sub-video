import subprocess
from pathlib import Path

def make_video(path: Path, seconds: float = 5, size=(640, 360), with_text: bool = True, audio: bool = True) -> Path:
    """Synthetic clip: moving test pattern, a sine tone and a fake burnt-in subtitle at the bottom."""
    w, h = size
    vf = "null"
    if with_text:
        vf = (f"drawbox=x=0:y={int(h*0.82)}:w={w}:h={int(h*0.14)}:color=black@0.3:t=fill,"
              f"drawtext=text='OLD SUBTITLE':fontcolor=white:fontsize={h//12}:x=(w-text_w)/2:y={int(h*0.85)}")
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size={w}x{h}:rate=25:duration={seconds}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=44100:duration={seconds}"]
    cmd += ["-vf", vf, "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    if audio:
        cmd += ["-c:a", "aac", "-shortest"]
    cmd.append(str(path))
    subprocess.run(cmd, check=True)
    return path
