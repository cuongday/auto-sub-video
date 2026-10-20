"""The review script of one part: blocks of narration (hook, opening, body, ending), each with the film
scenes that illustrate it. Written by the LLM from the chunk summaries, never from beyond them."""
import json
import re
from ..llm.base import LLMProvider
from ..models import ChunkSummary, FilmCharacter, MovieMeta, Notebook, PartInfo, ReviewSettings, Script, ScriptBlock, TimeSpan
from . import notebook as nb_mod, templates
from .film import _meta
from .pace import syllables

KINDS = ["hook", "mo_dau", "than", "ket"]
MIN_SCENE = 0.5
LENGTH_TOLERANCE = 0.15
BLOCK_PAUSE = 0.35

_SPAN = {"type": "object", "properties": {"start": {"type": "number"}, "end": {"type": "number"}}, "required": ["start", "end"]}

SCRIPT_SCHEMA = {
    "type": "object",
    "properties": {"blocks": {"type": "array", "items": {"type": "object", "properties": {
        "kind": {"type": "string", "enum": KINDS}, "text": {"type": "string"},
        "scenes": {"type": "array", "items": _SPAN},
        "source_start": {"type": "number"}, "source_end": {"type": "number"}},
        "required": ["kind", "text", "scenes", "source_start", "source_end"]}}},
    "required": ["blocks"],
}

TEXT_SCHEMA = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}

RULES = ("Quy tắc:\n"
         "- Chỉ kể những gì có trong tóm tắt, không thêm tình tiết. Được phân tích nhân vật và nêu cảm nhận.\n"
         "- Lời đọc kể ở ngôi thứ ba, bằng tiếng Việt, câu ngắn dễ đọc thành tiếng.\n"
         "- Các khối theo thứ tự: hook, mo_dau, các khối than (theo diễn biến), ket. "
         "source_start/source_end là khoảng phim mà khối đang kể.\n"
         "- mỗi khối kèm các cảnh minh hoạ lấy từ mốc thời gian trong tóm tắt (giây), nằm trong RANGE.")

def opening_for(settings: ReviewSettings, part: PartInfo) -> str:
    return settings.opening or ("gioi_thieu" if part.index == 1 else "tom_tat_truoc")

def estimate_seconds(script: Script, spm: float) -> float:
    return sum(syllables(b.text) for b in script.blocks) / spm * 60 + BLOCK_PAUSE * len(script.blocks)

def _clamp(a, b, part: PartInfo) -> TimeSpan | None:
    if a is None or b is None:
        return None
    s, e = max(part.start, float(a)), min(part.end, float(b))
    return TimeSpan(start=s, end=e) if e - s >= MIN_SCENE else None

def _order(b: ScriptBlock, part: PartInfo):
    return KINDS.index(b.kind), (b.source_start if b.source_start is not None else part.start) if b.kind == "than" else 0

def validate_blocks(raw: list[dict], part: PartInfo, settings: ReviewSettings,
                    locked: list[ScriptBlock] = ()) -> list[ScriptBlock]:
    """Clean the LLM's blocks: scenes inside the part, canonical order, ids from 1; the user's locked blocks
    keep their text and scenes and take the place of the model's block of the same kind (body: by source_start)."""
    out = []
    for r in raw:
        text = str(r.get("text", "")).strip()
        if not text or r.get("kind") not in KINDS:
            continue
        src = _clamp(r.get("source_start"), r.get("source_end"), part)
        scenes = [s for s in (_clamp(x.get("start"), x.get("end"), part) for x in r.get("scenes") or []) if s]
        if r["kind"] == "than" and not scenes:
            if not src:
                continue
            scenes = [src]
        out.append(ScriptBlock(id=0, kind=r["kind"], text=text, scenes=scenes,
                               source_start=src.start if src else None, source_end=src.end if src else None))
    mine = {b.kind for b in locked if b.kind != "than"}
    out = [b for b in out if b.kind not in mine] + [b.model_copy(update={"edited": True}) for b in locked]
    out.sort(key=lambda b: _order(b, part))
    tpl = {"hook": settings.hook, "mo_dau": opening_for(settings, part)}
    return [b.model_copy(update={"id": i, "template": tpl.get(b.kind, "")})
            for i, b in enumerate(out, 1)]

def _span(a: float, b: float) -> str:
    return f"[{a:.1f}–{b:.1f}]"

def _chunks(chunks: list[ChunkSummary], part: PartInfo) -> str:
    rows = []
    inside = lambda n: n.end > part.start and n.start < part.end  # noqa: E731
    for c in chunks:
        if not inside(c):
            continue
        rows.append(f"{_span(c.start, c.end)} {c.summary}")
        rows += [f"  - Sự kiện {_span(e.start, e.end)} {e.text}" for e in c.events if inside(e)]
        rows += [f"  - Cảnh nổi bật {_span(h.start, h.end)} {h.text}" for h in c.highlights if inside(h)]
    return "\n".join(rows) or "(không có)"

def _cast(chars) -> str:
    rows = []
    for c in chars:
        extra = [x for x in (c.role, getattr(c, "relations", ""), getattr(c, "arc", "")) if x]
        rows.append(f"- {c.name}" + (f" ({', '.join(c.aliases)})" if c.aliases else "") + (f": {'; '.join(extra)}" if extra else ""))
    return "\n".join(rows) or "(chưa có)"

def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text.lower()).split())

def _dump(blocks: list[ScriptBlock]) -> str:
    return json.dumps([b.model_dump(include={"kind", "text", "source_start", "source_end"}) for b in blocks],
                      ensure_ascii=False)

def build_script(llm: LLMProvider, *, meta: MovieMeta, characters: list[FilmCharacter], chunks: list[ChunkSummary],
                 part: PartInfo, total_parts: int, is_last: bool, settings: ReviewSettings, notebook: Notebook,
                 spm: float, locked: list[ScriptBlock] = ()) -> Script:
    target = round(settings.minutes * spm)
    opening = opening_for(settings, part)
    known = {c.name for c in notebook.characters}
    cast = [*notebook.characters, *(c for c in characters if c.name not in known)]   # notebook wins on a name
    used = nb_mod.used_hooks(notebook.model_copy(update={"entries": [e for e in notebook.entries if e.index != part.index]}))
    rows = [f"Bạn là người viết kịch bản video review phim. Viết lời đọc cho phần {part.index}/{total_parts} của video review.",
            RULES, "", _meta(meta), "", "Nhân vật:", _cast(cast), "",
            "Tóm tắt các đoạn phim trong phần này:", _chunks(chunks, part), "",
            f"Phong cách: {templates.prompt('styles', settings.style)}",
            f"Hook: {templates.prompt('hooks', settings.hook)}",
            f"Mở đầu: {templates.prompt('openings', opening)}"]
    if part.index > 1:
        earlier = [e for e in notebook.entries if e.index < part.index]
        rows += ["", "Sổ tay các phần trước:"]
        rows += [f"- Phần {e.index} ({e.range_label}): {e.summary}" + (f" Điểm dừng: {e.ending}." if e.ending else "")
                 + (f" Tình tiết còn lửng: {'; '.join(e.open_threads)}." if e.open_threads else "") for e in earlier]
        if notebook.voice:
            rows.append(f"Giọng kể đã dùng, giữ cho thống nhất: {notebook.voice}")
        rows.append(f"Hook đã dùng: {'; '.join(used) or '(chưa có)'}")
    if is_last and not settings.spoil_ending:
        rows.append("Không được tiết lộ cái kết của phim: dừng trước cao trào và để lửng.")
    if settings.notes.strip():
        rows.append(f"Yêu cầu thêm: {settings.notes.strip()}")
    if locked:
        rows.append(f"Các khối người dùng đã tự viết (giữ nguyên, không kể lặp lại): {_dump(list(locked))}")
    rows += ["", f"TARGET {target}  (tổng số âm tiết của toàn bộ lời đọc)", f"RANGE {part.start} {part.end}"]
    prompt = "\n".join(rows)

    fix, length_tries, hook_tries = "", 0, 0
    while True:
        raw = llm.generate_json(prompt + fix, SCRIPT_SCHEMA).get("blocks", [])
        blocks = validate_blocks(raw, part, settings, locked)
        n = sum(syllables(b.text) for b in blocks)
        draft = f"\n\nBản trước: {_dump(blocks)}"
        if target and abs(n - target) / target > LENGTH_TOLERANCE and length_tries < 2:
            length_tries += 1
            fix = f"{draft}\nKịch bản đang {'ngắn' if n < target else 'dài'} hơn mục tiêu: viết lại cho khoảng {target} âm tiết."
            continue
        hook = next((b for b in blocks if b.kind == "hook" and not b.edited), None)
        if hook and _norm(hook.text) in {_norm(h) for h in used} and hook_tries < 1:
            hook_tries += 1
            fix = f"{draft}\nHook bị trùng với phần trước: viết hook khác."
            continue
        if not blocks:
            raise RuntimeError("LLM không trả về kịch bản")
        return Script(blocks=blocks)

def rewrite_block(llm: LLMProvider, script: Script, bid: int, instruction: str, *, meta: MovieMeta,
                  settings: ReviewSettings, part: PartInfo) -> ScriptBlock:
    """Rewrite one block's narration on the user's request; its scenes stay."""
    block = next((b for b in script.blocks if b.id == bid), None)
    if block is None:
        raise ValueError(f"Không tìm thấy khối {bid}")
    prompt = "\n".join([
        "Bạn là người viết kịch bản video review phim. Viết lại một khối lời đọc theo yêu cầu.",
        "- Chỉ kể những gì có trong kịch bản và thông tin phim, không thêm tình tiết.",
        "- kể ở ngôi thứ ba, bằng tiếng Việt, giữ mạch với các khối xung quanh.",
        f"- Nếu yêu cầu không nói về độ dài, giữ khoảng {syllables(block.text)} âm tiết.", "",
        _meta(meta), f"Phong cách: {templates.prompt('styles', settings.style)}", "",
        f"Kịch bản phần {part.index}: {_dump(script.blocks)}", "",
        f"Khối cần viết lại ({block.kind}): {block.text}", f"Yêu cầu: {instruction.strip() or 'viết hay hơn'}"])
    text = str(llm.generate_json(prompt, TEXT_SCHEMA).get("text", "")).strip()
    if not text:
        raise RuntimeError("LLM không trả về lời đọc mới")
    return block.model_copy(update={"text": text, "edited": True})
