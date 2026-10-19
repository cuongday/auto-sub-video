"""LLM translation: one pass to build a context sheet, then batched line translation within length budgets."""
import json
import threading
from typing import Callable
from .llm.base import LLMError, LLMProvider
from .models import Lang, Segment, TranslationContext
from .timing import max_chars

LANG_NAME = {"zh": "tiếng Trung", "en": "tiếng Anh", "ko": "tiếng Hàn"}
CONTEXT_CHAR_LIMIT = 30_000

CONTEXT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "genre_tone": {"type": "string"},
        "characters": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "vi_name": {"type": "string"}, "addressing": {"type": "string"}},
            "required": ["name", "vi_name", "addressing"]}},
        "glossary": {"type": "array", "items": {"type": "object", "properties": {
            "source": {"type": "string"}, "vi": {"type": "string"}}, "required": ["source", "vi"]}},
    },
    "required": ["summary", "genre_tone", "characters", "glossary"],
}

ITEMS_SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {
        "id": {"type": "integer"}, "vi": {"type": "string"}}, "required": ["id", "vi"]}}},
    "required": ["items"],
}

def _transcript(segs: list[Segment]) -> str:
    lines = [s.source for s in segs]
    text = "\n".join(lines)
    if len(text) <= CONTEXT_CHAR_LIMIT:
        return text
    # keep lines spread evenly over the whole video
    keep = max(1, int(len(lines) * CONTEXT_CHAR_LIMIT / len(text)))
    step = len(lines) / keep
    return "\n".join(lines[int(i * step)] for i in range(keep))

def analyze(llm: LLMProvider, segs: list[Segment], lang: Lang, notes: str) -> TranslationContext:
    prompt = (
        f"Bạn là biên dịch viên phim chuyên nghiệp, dịch phụ đề {LANG_NAME[lang]} sang tiếng Việt.\n"
        "Đọc toàn bộ lời thoại dưới đây (do máy nhận dạng giọng nói, có thể sai chính tả) và lập bảng bối cảnh dịch:\n"
        "- summary: tóm tắt nội dung 2-4 câu (tiếng Việt).\n"
        "- genre_tone: thể loại và giọng điệu (ví dụ: cổ trang trang trọng, hài đời thường, review công nghệ...).\n"
        "- characters: các nhân vật/người nói; name = tên gốc, vi_name = tên dùng trong bản dịch "
        "(tiếng Trung: phiên âm Hán Việt; tiếng Anh: giữ nguyên), addressing = cách xưng hô phù hợp.\n"
        "- glossary: tên riêng, thuật ngữ cần dịch thống nhất.\n"
        + (f"\nGhi chú của người dùng: {notes}\n" if notes.strip() else "")
        + f"\nLỜI THOẠI:\n{_transcript(segs)}"
    )
    data = llm.generate_json(prompt, CONTEXT_SCHEMA, temperature=0.2)
    try:
        return TranslationContext.model_validate(data)
    except ValueError as e:
        raise LLMError(f"Bối cảnh dịch không hợp lệ: {e}") from e

def _context_block(ctx: TranslationContext, notes: str) -> str:
    parts = []
    if ctx.summary:
        parts.append(f"Tóm tắt: {ctx.summary}")
    if ctx.genre_tone:
        parts.append(f"Thể loại/giọng điệu: {ctx.genre_tone}")
    if ctx.characters:
        parts.append("Nhân vật: " + "; ".join(f"{c.name} → {c.vi_name} ({c.addressing})" for c in ctx.characters))
    if ctx.glossary:
        parts.append("Thuật ngữ: " + "; ".join(f"{g.source} → {g.vi}" for g in ctx.glossary))
    if notes.strip():
        parts.append(f"Ghi chú của người dùng: {notes.strip()}")
    return "\n".join(parts)

def _batch_prompt(lang: Lang, ctx_block: str, prev: list[Segment], items: list[dict]) -> str:
    prev_txt = "\n".join(f"[{s.id}] {s.source} => {s.vi}" for s in prev) or "(không có)"
    return (
        f"Dịch phụ đề {LANG_NAME[lang]} sang tiếng Việt để làm phụ đề và lồng tiếng thuyết minh.\n"
        "Yêu cầu:\n"
        "- Câu tiếng Việt tự nhiên, mềm mại, đúng ngữ cảnh, dùng khẩu ngữ khi là lời thoại; không dịch word-by-word.\n"
        "- Giữ thống nhất xưng hô, tên nhân vật và thuật ngữ theo bối cảnh.\n"
        "- Mỗi câu KHÔNG dài quá max_chars ký tự (để đọc kịp trong seconds giây); cần thì lược ý phụ, giữ ý chính.\n"
        "- Lời thoại do máy nhận dạng nên có thể sai; nếu rõ ràng nghe nhầm thì dịch theo ý đúng.\n"
        "- Trả về đúng một mục cho mỗi id, không gộp hay tách câu.\n\n"
        f"BỐI CẢNH:\n{ctx_block or '(không có)'}\n\n"
        f"CÁC CÂU ĐÃ DỊCH NGAY TRƯỚC (chỉ để tham khảo mạch văn):\n{prev_txt}\n\n"
        f"CẦN DỊCH:\n<<<ITEMS{json.dumps(items, ensure_ascii=False, indent=0)}ITEMS>>>"
    )

def _items(segs: list[Segment], slot_of: dict[int, float]) -> list[dict]:
    return [{"id": s.id, "source": s.source, "seconds": round(slot_of[s.id], 2), "max_chars": max_chars(slot_of[s.id])}
            for s in segs]

def _translate_batch(llm, lang, ctx_block, prev, batch, slot_of, attempts=3) -> dict[int, str]:
    """Returns translations by id; ids still missing after `attempts` tries are left out.
    LLMError (auth, quota exhausted after retries) propagates: the step fails instead of silently copying."""
    want = {s.id for s in batch}
    prompt = _batch_prompt(lang, ctx_block, prev, _items(batch, slot_of))
    best: dict[int, str] = {}
    for _ in range(attempts):
        data = llm.generate_json(prompt, ITEMS_SCHEMA)
        try:
            got = {int(it["id"]): str(it["vi"]).strip() for it in data.get("items", [])}
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        got = {k: v for k, v in got.items() if k in want and v}
        if set(got) == want:
            return got
        if len(got) > len(best):
            best = got
    return best

def shorten(llm: LLMProvider, items: list[tuple[Segment, int]], ctx: TranslationContext, lang: Lang) -> dict[int, str]:
    payload = [{"id": s.id, "source": s.source, "vi": s.vi, "max_chars": mc} for s, mc in items]
    prompt = (
        "RÚT GỌN các câu phụ đề tiếng Việt sau để mỗi câu không dài quá max_chars ký tự, giữ ý chính và giọng văn, "
        "vẫn tự nhiên khi đọc thành tiếng.\n\n"
        f"BỐI CẢNH:\n{_context_block(ctx, '') or '(không có)'}\n\n"
        f"<<<ITEMS{json.dumps(payload, ensure_ascii=False, indent=0)}ITEMS>>>"
    )
    try:
        data = llm.generate_json(prompt, ITEMS_SCHEMA)
        want = {s.id for s, _ in items}
        return {int(it["id"]): str(it["vi"]).strip() for it in data.get("items", [])
                if int(it["id"]) in want and str(it["vi"]).strip()}
    except (LLMError, KeyError, TypeError, ValueError):
        return {}

def _clear(s: Segment, *flags: str) -> None:
    s.flags = [f for f in s.flags if f not in flags]

def _run(llm, segs, slots, ctx, lang, notes, todo: list[Segment], batch, prev, progress, cancel) -> list[Segment]:
    out = [s.model_copy(deep=True) for s in segs]
    by_id = {s.id: s for s in out}
    slot_of = {s.id: sl for s, sl in zip(segs, slots)}
    ctx_block = _context_block(ctx, notes)
    todo_ids = [s.id for s in todo]
    order = [s.id for s in out]
    for start in range(0, len(todo_ids), batch):
        if cancel is not None and cancel.is_set():
            from .proc import Cancelled
            raise Cancelled()
        chunk = [by_id[i] for i in todo_ids[start:start + batch]]
        first = order.index(chunk[0].id)
        previous = [s for s in out[max(0, first - prev):first] if s.vi]
        got = _translate_batch(llm, lang, ctx_block, previous, chunk, slot_of)
        for s in chunk:
            _clear(s, "translate_failed", "too_long")
            if s.id in got:
                s.vi = got[s.id]
            else:
                s.vi = s.source
                s.flags.append("translate_failed")
        if progress:
            progress(min(1.0, (start + len(chunk)) / max(1, len(todo_ids))))
    long = [(by_id[i], max_chars(slot_of[i])) for i in todo_ids
            if "translate_failed" not in by_id[i].flags and len(by_id[i].vi) > 1.2 * max_chars(slot_of[i])]
    if long:
        fixed = shorten(llm, long, ctx, lang)
        for s, mc in long:
            if s.id in fixed:
                s.vi = fixed[s.id]
            if len(s.vi) > 1.2 * mc:
                s.flags.append("too_long")
    return out

def translate_all(llm: LLMProvider, segs: list[Segment], slots: list[float], ctx: TranslationContext, lang: Lang,
                  notes: str, *, batch: int = 40, prev: int = 5, progress: Callable[[float], None] | None = None,
                  cancel: threading.Event | None = None) -> list[Segment]:
    return _run(llm, segs, slots, ctx, lang, notes, segs, batch, prev, progress, cancel)

def translate_ids(llm: LLMProvider, segs: list[Segment], slots: list[float], ctx: TranslationContext, lang: Lang,
                  notes: str, ids: set[int]) -> list[Segment]:
    return _run(llm, segs, slots, ctx, lang, notes, [s for s in segs if s.id in ids], 40, 5, None, None)
