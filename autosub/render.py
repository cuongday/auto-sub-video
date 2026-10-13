"""ffmpeg filter graph: cover the old subtitle region, then burn the new ASS subtitles."""

def cover_filter(box: tuple[int, int, int, int], cover: str, color: str) -> str:
    x, y, w, h = box
    rect = f"x={x}:y={y}:w={w}:h={h}"
    if cover == "solid":
        return f"[0:v]drawbox={rect}:color=0x{color.lstrip('#')}@1:t=fill[cv]"
    r = max(2, min(20, min(w, h) // 4))
    rc = max(1, r // 2)
    f = (f"[0:v]split=2[base][tmp];[tmp]crop={w}:{h}:{x}:{y},"
         f"boxblur=luma_radius={r}:luma_power=3:chroma_radius={rc}:chroma_power=3[bl];"
         f"[base][bl]overlay={x}:{y}")
    if cover == "blur_dim":
        f += f",drawbox={rect}:color=black@0.45:t=fill"
    return f + "[cv]"

def build_filter(box, cover: str, color: str, ass_name: str = "subs.ass", fonts_dir: str = "fonts") -> str:
    return cover_filter(box, cover, color) + f";[cv]ass={ass_name}:fontsdir={fonts_dir}[v]"
