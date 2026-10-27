"""Read a narration script (.txt/.docx/.srt) into sentence lines."""
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from xml.etree import ElementTree as ET

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_SENT = re.compile(r"(?<=[.!?…])[\"”’)]*\s+|(?<=[.!?…][\"”’)])\s+|\n+")
_TS = r"(\d+):(\d{1,2}):(\d{2})[.,](\d{3})"
_CUE = re.compile(rf"{_TS}\s*-->\s*{_TS}")
_TAGS = re.compile(r"<[^>]+>|\{[^}]*\}")


class ScriptError(Exception):
    pass


@dataclass
class Line:
    text: str
    para: int
    start: float | None = None
    end: float | None = None


def _decode(raw: bytes) -> str:
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        text = raw.decode("utf-16")
    else:
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp1258", errors="replace")
    return unicodedata.normalize("NFC", text)


def _split_long(s: str, limit: int) -> list[str]:
    out: list[str] = []
    cur = ""
    for piece in re.split(r"(?<=,)\s*", s):
        while len(piece) > limit:
            cut = piece.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            if cur:
                out.append(cur)
                cur = ""
            out.append(piece[:cut].strip())
            piece = piece[cut:].strip()
        if cur and len(cur) + 1 + len(piece) > limit:
            out.append(cur)
            cur = piece
        else:
            cur = f"{cur} {piece}".strip()
    if cur:
        out.append(cur)
    return out


def split_sentences(text: str, limit: int = 300) -> list[str]:
    out: list[str] = []
    for s in _SENT.split(text):
        s = " ".join((s or "").split())
        if s:
            out.extend(_split_long(s, limit) if len(s) > limit else [s])
    return out


def _paragraphs(paras: list[str]) -> list[Line]:
    lines: list[Line] = []
    n = 0
    for p in paras:
        sents = split_sentences(p)
        if sents:
            lines.extend(Line(s, n) for s in sents)
            n += 1
    return lines


def _docx(path: Path) -> list[str]:
    try:
        with zipfile.ZipFile(path) as z:
            root = ET.fromstring(z.read("word/document.xml"))
    except (zipfile.BadZipFile, KeyError, ET.ParseError):
        raise ScriptError("File .docx bị hỏng hoặc không đọc được") from None
    out = []
    for p in root.iter(f"{_W}p"):
        buf = []
        for el in p.iter():
            if el.tag == f"{_W}t":
                buf.append(el.text or "")
            elif el.tag == f"{_W}tab":
                buf.append(" ")
            elif el.tag == f"{_W}br":
                buf.append("\n")
        out.append("".join(buf))
    return out


def _srt(text: str) -> list[Line]:
    lines: list[Line] = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n")):
        rows = block.strip().split("\n")
        for i, row in enumerate(rows):
            m = _CUE.search(row)
            if not m:
                continue
            g = [int(x) for x in m.groups()]
            body = " ".join(_TAGS.sub("", " ".join(rows[i + 1:])).split())
            if body:
                a = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
                b = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
                lines.append(Line(body, len(lines), a, b))
            break
    if not lines:
        raise ScriptError("File .srt không hợp lệ: không tìm thấy phụ đề nào")
    lines.sort(key=lambda l: l.start or 0)
    for i, l in enumerate(lines):
        l.para = i
    return lines


def parse(path: Path, kind: Literal["txt", "docx", "srt"]) -> list[Line]:
    if kind == "docx":
        lines = _paragraphs(_docx(path))
    elif kind == "srt":
        lines = _srt(_decode(path.read_bytes()))
    else:
        lines = _paragraphs(re.split(r"\n\s*\n", _decode(path.read_bytes()).replace("\r\n", "\n").replace("\r", "\n")))
    if not lines:
        raise ScriptError("Kịch bản không có nội dung")
    return lines
