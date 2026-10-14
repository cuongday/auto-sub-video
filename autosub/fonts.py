"""Subtitle fonts bundled in fonts/ (all cover Vietnamese diacritics; licenses in fonts/FONTS.md)."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Font:
    id: str
    label: str
    family: str          # the family name libass matches in the ASS style
    bold: bool           # ASS Bold flag, for files registered as the bold face of a family
    file: str
    css_weight: int      # weight the browser preview uses (Google Fonts)

FONTS: list[Font] = [
    Font("bevietnam", "Be Vietnam Pro — mặc định, rõ ràng", "Be Vietnam Pro SemiBold", False, "BeVietnamPro-SemiBold.ttf", 600),
    Font("roboto", "Roboto — trung tính, dễ đọc", "Roboto", True, "Roboto-Bold.ttf", 700),
    Font("montserrat", "Montserrat — hiện đại, đậm", "Montserrat", True, "Montserrat-Bold.ttf", 700),
    Font("nunito", "Nunito — tròn, thân thiện", "Nunito ExtraBold", False, "Nunito-ExtraBold.ttf", 800),
    Font("lexend", "Lexend — rộng, rất dễ đọc", "Lexend SemiBold", False, "Lexend-SemiBold.ttf", 600),
    Font("oswald", "Oswald — cao, hẹp (tiết kiệm chỗ)", "Oswald SemiBold", False, "Oswald-SemiBold.ttf", 600),
    Font("merriweather", "Merriweather — có chân, sách vở", "Merriweather", True, "Merriweather-Bold.ttf", 700),
    Font("notoserif", "Noto Serif — có chân, cổ trang", "Noto Serif", True, "NotoSerif-Bold.ttf", 700),
    Font("pacifico", "Pacifico — viết tay, vui", "Pacifico", False, "Pacifico-Regular.ttf", 400),
    Font("dancing", "Dancing Script — viết tay mềm mại", "Dancing Script", True, "DancingScript-Bold.ttf", 700),
    Font("bangers", "Bangers — truyện tranh, in hoa", "Bangers", False, "Bangers-Regular.ttf", 400),
    Font("patrick", "Patrick Hand — chữ viết tay đơn giản", "Patrick Hand", False, "PatrickHand-Regular.ttf", 400),
]
DEFAULT_FONT = "bevietnam"
_BY_ID = {f.id: f for f in FONTS}

def get_font(font_id: str | None) -> Font:
    return _BY_ID.get(font_id or DEFAULT_FONT, _BY_ID[DEFAULT_FONT])
