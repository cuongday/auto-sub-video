"""ASS/SRT generation; the new subtitle is laid out inside the covered region."""
from .fonts import get_font
from .models import Region, Segment, SubStyle


def _even(v: float) -> int:
    return int(2 * round(v / 2))

def region_px(region: Region, W: int, H: int) -> tuple[int, int, int, int]:
    x = min(max(0, _even(region.x * W)), W - 16)
    y = min(max(0, _even(region.y * H)), H - 16)
    w = max(16, min(_even(region.w * W), (W - x) // 2 * 2))
    h = max(16, min(_even(region.h * H), (H - y) // 2 * 2))
    return x, y, w, h

CHARS_PER_LINE = 24       # Vietnamese subtitle line that should fit the region width

def auto_font_size(h_px: int, w_px: int | None = None) -> int:
    """Two lines fit the region height and ~CHARS_PER_LINE characters fit its width
    (the width limit matters for narrow regions, e.g. portrait videos)."""
    fs = h_px / 2.6
    if w_px:
        fs = min(fs, w_px / (CHARS_PER_LINE * 0.55))
    return max(14, round(fs))

def ass_color(hex_rgb: str, alpha: int = 0) -> str:
    h = hex_rgb.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()

def _ass_time(t: float) -> str:
    cs = max(0, round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"

def _srt_time(t: float) -> str:
    ms = max(0, round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"

def _escape(text: str) -> str:
    return (text.replace("\\", "＼").replace("{", "｛").replace("}", "｝")
            .replace("\r", "").strip().replace("\n", "\\N"))

def build_ass(segs: list[Segment], W: int, H: int, region: Region, style: SubStyle) -> str:
    x, y, w, h = region_px(region, W, H)
    fs = style.font_size or auto_font_size(h, w)
    outline = style.outline if style.outline is not None else max(1.5, round(fs / 18, 1))
    shadow = 1 if fs < 40 else 2
    cx, cy = x + w // 2, y + h // 2
    font = get_font(style.font)
    head = (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {W}\nPlayResY: {H}\nWrapStyle: 0\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{font.family},{fs},{ass_color(style.color)},{ass_color(style.color)},"
        f"{ass_color(style.outline_color)},{ass_color('#000000', 0x80)},{-1 if font.bold else 0},0,0,0,100,100,0,0,1,"
        f"{outline:g},{shadow},5,{x},{W - (x + w)},0,1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    lines = [f"Dialogue: 0,{_ass_time(s.start)},{_ass_time(s.end)},Default,,0,0,0,,{{\\pos({cx},{cy})}}{_escape(s.vi)}"
             for s in segs if s.vi.strip()]
    return head + "\n".join(lines) + "\n"

def build_srt(segs: list[Segment]) -> str:
    blocks = [f"{n}\n{_srt_time(s.start)} --> {_srt_time(s.end)}\n{s.vi.strip()}\n"
              for n, s in enumerate((s for s in segs if s.vi.strip()), 1)]
    return "\n".join(blocks)
