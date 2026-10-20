"""The review script of one part: blocks of narration (hook, opening, body, ending), each with the film
scenes that illustrate it. Written by the LLM from the chunk summaries, never from beyond them; the part's
timestamped dialogue lets it point each scene at the moment its sentence tells."""
import json
import math
import re
from ..llm.base import LLMProvider
from ..models import ChunkSummary, FilmCharacter, MovieMeta, Notebook, PartInfo, ReviewSettings, Script, ScriptBlock, Segment, TimeSpan
from . import notebook as nb_mod, templates
from .film import _meta
from .narration import BLOCK_GAP, SENT_GAP, sentences
from .pace import syllables

KINDS = ["hook", "mo_dau", "than", "ket"]
MIN_SCENE = 0.5
LENGTH_TOLERANCE = 0.15
BODY_SYLLABLES = 220     # one body block: a long script gets more blocks, not longer ones
MAX_BODY = 30
SENTENCE_SYLLABLES = 15  # an average sentence before any is written, for the pauses between sentences
EXTEND_ROUNDS = 3
MAX_LINES = 1200    # dialogue lines in the prompt; a longer part keeps every k-th line

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
         "- Mỗi khối kèm các cảnh minh hoạ (giây, nằm trong RANGE) liệt kê theo đúng thứ tự lời đọc kể: khoảng một cảnh "
         "cho mỗi câu, mỗi cảnh dài 2–8 giây, đặt đúng lúc trong lời thoại hoặc sự kiện mà câu đó nói tới.\n"
         "- hook, mo_dau và ket cũng phải có cảnh: hook là khoảnh khắc nó gợi tò mò, mo_dau là những cảnh mở ra bối cảnh "
         "của phần, ket là khoảnh khắc cuối cùng mà các khối than đã kể.")

def opening_for(settings: ReviewSettings, part: PartInfo) -> str:
    return settings.opening or ("gioi_thieu" if part.index == 1 else "tom_tat_truoc")

def pause_seconds(text: str) -> float:
    """The silence assemble lays around a block: one gap after it, one between two of its sentences."""
    return BLOCK_GAP + SENT_GAP * max(0, len(sentences(text)) - 1)

def estimate_seconds(script: Script, spm: float) -> float:
    return sum(syllables(b.text) / spm * 60 + pause_seconds(b.text) for b in script.blocks)

def _body_count(syl: float) -> int:
    return min(MAX_BODY, max(3, round(syl / BODY_SYLLABLES)))

def target_syllables(seconds: float, spm: float) -> int:
    """Syllables that fill `seconds` of narration once the pauses between blocks and sentences are taken out."""
    rough = seconds / 60 * spm
    blocks = _body_count(rough) + 3
    pauses = BLOCK_GAP * blocks + SENT_GAP * max(0, round(rough / SENTENCE_SYLLABLES) - blocks)
    return max(1, round((seconds - pauses) / 60 * spm))

def _budget(target: int) -> str:
    n = _body_count(target)
    frame = min(200, target // 3)                        # hook 1 : mo_dau 2 : ket 2
    hook, side = max(1, frame // 5), max(1, 2 * frame // 5)
    return (f"Cấu trúc: hook khoảng {hook} âm tiết, mo_dau khoảng {side}, {n} khối than mỗi khối khoảng "
            f"{max(1, (target - frame) // n)} âm tiết, ket khoảng {side}. Kịch bản ngắn hơn TARGET là không đạt: "
            "kể đủ từng diễn biến trong tóm tắt và lời thoại cho tới khi đủ độ dài.")

def _clamp(a, b, part: PartInfo) -> TimeSpan | None:
    if a is None or b is None:
        return None
    s, e = max(part.start, float(a)), min(part.end, float(b))
    return TimeSpan(start=s, end=e) if e - s >= MIN_SCENE else None

def _order(b: ScriptBlock, part: PartInfo):
    return KINDS.index(b.kind), (b.source_start if b.source_start is not None else part.start) if b.kind == "than" else 0

def story_end(blocks: list[ScriptBlock], part: PartInfo, keep_ending: bool) -> float:
    """Where the footage stops: the end of the part, or, with the ending kept, the end of what the body tells."""
    ends = [b.source_end for b in blocks if b.kind == "than" and b.source_end is not None]
    return min(part.end, max(ends)) if keep_ending and ends else part.end

def validate_blocks(raw: list[dict], part: PartInfo, settings: ReviewSettings,
                    locked: list[ScriptBlock] = (), keep_ending: bool = False) -> list[ScriptBlock]:
    """Clean the LLM's blocks: scenes inside the part (ending kept: never past the body), canonical order, ids from 1;
    the user's locked blocks keep their text and scenes and take the place of the model's block of the same kind
    (body: by source_start)."""
    out = _clean(raw, part)
    if (end := story_end([*out, *locked], part, keep_ending)) < part.end:
        out = _clean(raw, part.model_copy(update={"end": end}))
    mine = {b.kind for b in locked if b.kind != "than"}
    out = [b for b in out if b.kind not in mine] + [b.model_copy(update={"edited": True}) for b in locked]
    out.sort(key=lambda b: _order(b, part))
    tpl = {"hook": settings.hook, "mo_dau": opening_for(settings, part)}
    return [b.model_copy(update={"id": i, "template": tpl.get(b.kind, "")})
            for i, b in enumerate(out, 1)]

def _clean(raw: list[dict], part: PartInfo) -> list[ScriptBlock]:
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
    return out

def _span(a: float, b: float) -> str:
    return f"[{a:.1f}–{b:.1f}]"

def _chunks(chunks: list[ChunkSummary], part: PartInfo) -> str:
    rows = []
    inside = lambda n: n.end > part.start and n.start < part.end  # noqa: E731
    for c in chunks:
        if not inside(c):
            continue
        whole = part.start <= c.start and c.end <= part.end    # across the boundary: its summary tells another part
        rows.append(f"{_span(c.start, c.end)} {c.summary}" if whole
                    else _span(max(c.start, part.start), min(c.end, part.end)))
        rows += [f"  - Sự kiện {_span(e.start, e.end)} {e.text}" for e in c.events if inside(e)]
        rows += [f"  - Cảnh nổi bật {_span(h.start, h.end)} {h.text}" for h in c.highlights if inside(h)]
    return "\n".join(rows) or "(không có)"

def _dialogue(lines: list[Segment], part: PartInfo) -> str:
    rows = [s for s in lines if part.start <= s.start < part.end]
    k = math.ceil(len(rows) / MAX_LINES) or 1
    return "\n".join(f"[{s.start:.1f}] {s.source}" for s in rows[::k]) or "(không có)"

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

def _uncovered(blocks: list[ScriptBlock], start: float, end: float) -> list[tuple[float, float]]:
    """Stretches of [start, end] no body block tells; when the body spans it all, the three stretches it tells most
    briefly (fewest syllables per second of film), whose details an extension can still add."""
    body = sorted((b for b in blocks if b.kind == "than" and b.source_start is not None and b.source_end is not None),
                  key=lambda b: b.source_start)
    gaps, t, least = [], start, (end - start) / 20
    for b in body:
        if b.source_start - t > least:
            gaps.append((t, b.source_start))
        t = max(t, b.source_end)
    if end - t > least:
        gaps.append((t, end))
    thin = sorted(body, key=lambda b: syllables(b.text) / max(b.source_end - b.source_start, 1.0))[:3]
    return gaps or sorted((b.source_start, b.source_end) for b in thin)

def build_script(llm: LLMProvider, *, meta: MovieMeta, characters: list[FilmCharacter], chunks: list[ChunkSummary],
                 part: PartInfo, total_parts: int, is_last: bool, settings: ReviewSettings, notebook: Notebook,
                 spm: float, locked: list[ScriptBlock] = (), lines: list[Segment] = ()) -> Script:
    goal = settings.minutes * 60
    target = target_syllables(goal, spm)
    opening = opening_for(settings, part)
    known = {c.name for c in notebook.characters}
    cast = [*notebook.characters, *(c for c in characters if c.name not in known)]   # notebook wins on a name
    used = nb_mod.used_hooks(notebook.model_copy(update={"entries": [e for e in notebook.entries if e.index != part.index]}))
    rows = [f"Bạn là người viết kịch bản video review phim. Viết lời đọc cho phần {part.index}/{total_parts} của video review.",
            RULES, "", _meta(meta), "", "Nhân vật:", _cast(cast), "",
            "Tóm tắt các đoạn phim trong phần này:", _chunks(chunks, part), "",
            "Lời thoại trong phần này ([giây] câu thoại gốc), để đặt cảnh đúng lúc:", _dialogue(lines, part), "",
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
    rows += ["", f"TARGET {target}  (tổng số âm tiết của toàn bộ lời đọc)", _budget(target),
             f"RANGE {part.start} {part.end}"]
    prompt = "\n".join(rows)

    keep_ending = is_last and not settings.spoil_ending
    fix, length_tries, hook_tries = "", 0, 0
    while True:
        raw = llm.generate_json(prompt + fix, SCRIPT_SCHEMA).get("blocks", [])
        blocks = validate_blocks(raw, part, settings, locked, keep_ending)
        sec = estimate_seconds(Script(blocks=blocks), spm)
        draft = f"\n\nBản trước: {_dump(blocks)}"
        if abs(sec - goal) / goal > LENGTH_TOLERANCE and length_tries < 2:
            length_tries += 1
            fix = f"{draft}\nKịch bản đang {'ngắn' if sec < goal else 'dài'} hơn mục tiêu: viết lại cho khoảng {target} âm tiết."
            continue
        hook = next((b for b in blocks if b.kind == "hook" and not b.edited), None)
        if hook and _norm(hook.text) in {_norm(h) for h in used} and hook_tries < 1:
            hook_tries += 1
            fix = f"{draft}\nHook bị trùng với phần trước: viết hook khác."
            continue
        if not blocks:
            raise RuntimeError("LLM không trả về kịch bản")
        break
    for _ in range(EXTEND_ROUNDS):      # still short (models stop near 1,500 syllables a call): add body blocks
        if sec >= goal * (1 - LENGTH_TOLERANCE):
            break
        need = max(1, round((goal - sec) / 60 * spm))
        k = min(MAX_BODY, max(1, round(need / BODY_SYLLABLES)))
        spans = _uncovered(blocks, part.start, story_end(blocks, part, keep_ending))
        ask = (f"\n\nBản nháp hiện tại: {_dump(blocks)}\nBản nháp còn thiếu khoảng {need} âm tiết. "
               f"Viết thêm {k} khối than, mỗi khối khoảng {need // k} âm tiết, kể những diễn biến trong các khoảng phim "
               "dưới đây mà bản nháp chưa kể hoặc mới kể sơ lược. Chỉ lấy từ tóm tắt và lời thoại của các khoảng đó, "
               "không bịa thêm, không lặp lại bản nháp. Chỉ trả về các khối than mới.\n"
               + "\n".join(f"UNCOVERED {_span(a, b)}" for a, b in spans))
        more = [r for r in llm.generate_json(prompt + ask, SCRIPT_SCHEMA).get("blocks", []) if r.get("kind") == "than"]
        longer = validate_blocks(raw + more, part, settings, locked, keep_ending)
        if (n := estimate_seconds(Script(blocks=longer), spm)) <= sec:
            break
        raw, blocks, sec = raw + more, longer, n
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
