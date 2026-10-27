import unicodedata
import zipfile
from pathlib import Path

import pytest

from autosub.audio.script import Line, ScriptError, parse, split_sentences

def _enc(text: str, enc: str) -> bytes:
    if enc != "cp1258":
        return text.encode(enc)
    out = ""
    for ch in unicodedata.normalize("NFD", text):
        if unicodedata.combining(ch) and out:
            try:
                comp = unicodedata.normalize("NFC", out[-1] + ch)
                comp.encode(enc)
                out = out[:-1] + comp
                continue
            except UnicodeEncodeError:
                pass
        out += ch
    return out.encode(enc)


VI = "Xin chào các bạn. Hôm nay trời đẹp!\n\nChúng ta đi đâu?"


def test_txt_paragraphs_and_sentences(tmp_path: Path):
    p = tmp_path / "a.txt"
    p.write_text("Một. Hai!\n\nBa?", encoding="utf-8")
    lines = parse(p, "txt")
    assert [l.text for l in lines] == ["Một.", "Hai!", "Ba?"]
    assert [l.para for l in lines] == [0, 0, 1]


@pytest.mark.parametrize("enc", ["utf-8-sig", "utf-16", "cp1258"])
def test_txt_encodings(tmp_path: Path, enc):
    p = tmp_path / "a.txt"
    p.write_bytes(_enc(VI, enc))
    lines = parse(p, "txt")
    assert [l.text for l in lines] == ["Xin chào các bạn.", "Hôm nay trời đẹp!", "Chúng ta đi đâu?"]
    assert [l.para for l in lines] == [0, 0, 1]


def test_decimal_not_split():
    assert split_sentences("Giá là 3.5 triệu. Ok") == ["Giá là 3.5 triệu.", "Ok"]


def test_long_sentence_split_at_comma():
    s = ", ".join(f"mệnh đề số {i} khá dài" for i in range(20)) + "."
    assert len(s) > 300
    parts = split_sentences(s)
    assert len(parts) > 1 and all(len(x) <= 300 for x in parts)
    assert "".join(parts).replace(" ", "") == s.replace(" ", "")


def _docx(path: Path, body: str):
    ns = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
          'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
          'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" '
          'xmlns:v="urn:schemas-microsoft-com:vml"')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", f"<w:document {ns}><w:body>{body}</w:body></w:document>")
        z.writestr("word/media/image1.png", b"\x89PNG" * 10)


def test_docx_reads_paragraphs(tmp_path: Path):
    p = tmp_path / "a.docx"
    _docx(p, "<w:p><w:r><w:t>Xin </w:t></w:r><w:r><w:t>chào.</w:t></w:r></w:p><w:p><w:r><w:t>Tạm biệt.</w:t></w:r></w:p>")
    lines = parse(p, "docx")
    assert [(l.text, l.para) for l in lines] == [("Xin chào.", 0), ("Tạm biệt.", 1)]


def test_docx_text_box_read_once(tmp_path: Path):
    """A Word text box (mc:AlternateContent: Choice + a Fallback copy) is read once, as its own paragraph."""
    box = "<w:txbxContent><w:p><w:r><w:t>Hộp chữ.</w:t></w:r></w:p></w:txbxContent>"
    p = tmp_path / "a.docx"
    _docx(p, "<w:p><w:r><w:t>Mở đầu.</w:t></w:r><w:r><mc:AlternateContent>"
             f"<mc:Choice Requires=\"wps\"><w:drawing><wps:wsp><wps:txbx>{box}</wps:txbx></wps:wsp></w:drawing></mc:Choice>"
             f"<mc:Fallback><w:pict><v:shape><v:textbox>{box}</v:textbox></v:shape></w:pict></mc:Fallback>"
             "</mc:AlternateContent></w:r><w:r><w:t> Tiếp theo.</w:t></w:r></w:p>"
             "<w:p><w:r><w:t>Kết.</w:t></w:r></w:p>")
    lines = parse(p, "docx")
    assert [(l.text, l.para) for l in lines] == [("Mở đầu.", 0), ("Tiếp theo.", 0), ("Hộp chữ.", 1), ("Kết.", 2)]

def test_docx_old_vml_text_box_read_once(tmp_path: Path):
    p = tmp_path / "a.docx"
    _docx(p, "<w:p><w:r><w:t>A.</w:t></w:r><w:r><w:pict><v:shape><v:textbox><w:txbxContent>"
             "<w:p><w:r><w:t>B.</w:t></w:r></w:p></w:txbxContent></v:textbox></v:shape></w:pict></w:r></w:p>")
    assert [(l.text, l.para) for l in parse(p, "docx")] == [("A.", 0), ("B.", 1)]

def test_docx_table_cells_read(tmp_path: Path):
    p = tmp_path / "a.docx"
    _docx(p, "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Ô một.</w:t></w:r></w:p></w:tc>"
             "<w:tc><w:p><w:r><w:t>Ô hai.</w:t></w:r></w:p></w:tc></w:tr></w:tbl>")
    assert [l.text for l in parse(p, "docx")] == ["Ô một.", "Ô hai."]

def test_docx_not_zip_raises(tmp_path: Path):
    p = tmp_path / "a.docx"
    p.write_bytes(b"not a zip")
    with pytest.raises(ScriptError, match="File .docx bị hỏng"):
        parse(p, "docx")


def test_srt_tags_bom_crlf(tmp_path: Path):
    p = tmp_path / "a.srt"
    p.write_bytes("﻿1\r\n00:00:01,000 --> 00:00:02,500\r\n<i>Xin</i> {\\an8}chào\r\nbạn\r\n".encode())
    assert parse(p, "srt") == [Line("Xin chào bạn", 0, 1.0, 2.5)]


def test_srt_dot_timestamp(tmp_path: Path):
    p = tmp_path / "a.srt"
    p.write_text("1\n00:00:01.250 --> 00:00:02.000\nA\n\n2\n00:00:03,000 --> 00:00:04,000\nB\n", encoding="utf-8")
    assert [(l.start, l.end, l.para) for l in parse(p, "srt")] == [(1.25, 2.0, 0), (3.0, 4.0, 1)]


def test_srt_malformed_raises(tmp_path: Path):
    p = tmp_path / "a.srt"
    p.write_text("hello\nworld\n", encoding="utf-8")
    with pytest.raises(ScriptError, match=".srt"):
        parse(p, "srt")


def test_empty_script_raises(tmp_path: Path):
    p = tmp_path / "a.txt"
    p.write_text("  \n \n", encoding="utf-8")
    with pytest.raises(ScriptError, match="Kịch bản không có nội dung"):
        parse(p, "txt")
