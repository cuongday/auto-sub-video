"""LLM passes over a film's transcript: the film-level character list, then one summary per chunk."""
from ..llm.base import LLMProvider
from ..models import ChunkSummary, FilmCharacter, MovieMeta, SceneNote, Segment
from ..translate import LANG_NAME, _transcript

LANGS = {"vi": "tiếng Việt", **LANG_NAME}

CHAR_SCHEMA = {
    "type": "object",
    "properties": {"characters": {"type": "array", "items": {"type": "object", "properties": {
        "name": {"type": "string"}, "aliases": {"type": "array", "items": {"type": "string"}}, "role": {"type": "string"}},
        "required": ["name", "aliases", "role"]}}},
    "required": ["characters"],
}

_NOTES = {"type": "array", "items": {"type": "object", "properties": {
    "start": {"type": "number"}, "end": {"type": "number"}, "text": {"type": "string"}}, "required": ["start", "end", "text"]}}

CHUNK_SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string"}, "events": _NOTES,
                   "characters": {"type": "array", "items": {"type": "string"}}, "highlights": _NOTES},
    "required": ["summary", "events", "characters", "highlights"],
}

def _meta(meta: MovieMeta) -> str:
    rows = [f"Phim: {meta.name}" + (f" (tên gốc: {meta.origin_name})" if meta.origin_name else "")]
    if meta.actors:
        rows.append(f"Diễn viên: {', '.join(meta.actors)}")
    if meta.content:
        rows.append(f"Nội dung: {meta.content}")
    return "\n".join(rows)

def _cast(chars: list[FilmCharacter]) -> str:
    return "\n".join(f"- {c.name}" + (f" ({', '.join(c.aliases)})" if c.aliases else "") + (f": {c.role}" if c.role else "")
                     for c in chars) or "(chưa có)"

def characters(llm: LLMProvider, meta: MovieMeta, lines: list[Segment], lang: str,
               known: list[FilmCharacter]) -> list[FilmCharacter]:
    prompt = (
        "Bạn là biên tập viên phim. Đọc thông tin phim và lời thoại dưới đây, lập danh sách nhân vật của phim:\n"
        "- name: tên gọi thống nhất bằng tiếng Việt; aliases: các cách gọi khác trong lời thoại; role: vai trò ngắn gọn.\n"
        "- Giữ nguyên tên các nhân vật đã biết, chỉ thêm nhân vật mới.\n"
        "- Tên tiếng Trung thì phiên âm Hán-Việt (ví dụ 小明 → Tiểu Minh).\n\n"
        f"{_meta(meta)}\n\nNhân vật đã biết:\n{_cast(known)}\n\n"
        f"Lời thoại ({LANGS.get(lang, lang)}):\n{_transcript(lines)}")
    out: dict[str, FilmCharacter] = {}
    for c in llm.generate_json(prompt, CHAR_SCHEMA).get("characters", []):
        c = FilmCharacter.model_validate(c)
        if c.name.strip():
            out.setdefault(c.name.strip(), c.model_copy(update={"name": c.name.strip()}))
    for c in known:                       # a known character the model left out stays on the list
        out.setdefault(c.name, c)
    return list(out.values())

def _clip(items: list[dict], a: float, b: float) -> list[SceneNote]:
    out = []
    for it in items:
        s, e = max(a, float(it["start"])), min(b, float(it["end"]))
        if e > s:
            out.append(SceneNote(start=s, end=e, text=str(it["text"]).strip()))
    return out

def summarize_chunk(llm: LLMProvider, meta: MovieMeta, chars: list[FilmCharacter], lines: list[Segment],
                    span: tuple[float, float], lang: str) -> ChunkSummary:
    a, b = span
    prompt = (
        "Bạn là biên tập viên phim. Tóm tắt đoạn phim dưới đây bằng tiếng Việt, chỉ dựa vào lời thoại:\n"
        "- summary: diễn biến chính 3-6 câu.\n"
        "- events: các sự kiện, mỗi sự kiện có start/end (giây) nằm trong SPAN.\n"
        "- characters: nhân vật xuất hiện, dùng đúng tên trong danh sách nhân vật.\n"
        "- highlights: cảnh đáng chú ý (gay cấn, xúc động, lời thoại đắt giá), kèm start/end (giây).\n\n"
        f"{_meta(meta)}\n\nNhân vật:\n{_cast(chars)}\n\nSPAN {a} {b}\n"
        f"Lời thoại ({LANGS.get(lang, lang)}), mỗi dòng có mốc giây bắt đầu:\n"
        + "\n".join(f"[{s.start:.1f}] {s.source}" for s in lines))
    r = llm.generate_json(prompt, CHUNK_SCHEMA)
    return ChunkSummary(start=a, end=b, summary=str(r.get("summary", "")).strip(),
                        events=_clip(r.get("events", []), a, b), characters=list(r.get("characters", [])),
                        highlights=_clip(r.get("highlights", []), a, b))
