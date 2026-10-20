"""The project notebook: what earlier parts told, read when writing the next script."""
import json
import re
from ..llm.base import LLMProvider
from ..models import FilmCharacter, FilmInfo, Notebook, NotebookCharacter, NotebookEntry, PartInfo, Script

_STR = {"type": "string"}
_LIST = {"type": "array", "items": _STR}
ENTRY_SCHEMA = {
    "type": "object",
    "properties": {
        "entry": {"type": "object", "properties": {"summary": _STR, "ending": _STR, "open_threads": _LIST, "hooks": _LIST},
                  "required": ["summary", "ending", "open_threads", "hooks"]},
        "characters": {"type": "array", "items": {"type": "object", "properties": {
            "name": _STR, "aliases": _LIST, "role": _STR, "relations": _STR, "arc": _STR},
            "required": ["name", "aliases", "role", "relations", "arc"]}},
        "voice": _STR},
    "required": ["entry", "characters", "voice"],
}

def rev_before(nb: Notebook, index: int) -> int:
    """Notebook version a part's script depends on: the shared section and the entries of earlier parts."""
    return max([nb.shared_rev, *(e.rev for e in nb.entries if e.index < index)], default=0)

def is_stale(nb: Notebook, part: PartInfo) -> bool:
    return rev_before(nb, part.index) > part.notebook_rev

def used_hooks(nb: Notebook) -> list[str]:
    return [h for e in nb.entries for h in e.hooks]

def record_part(llm: LLMProvider, nb: Notebook, *, job_id: str, index: int, range_label: str, script: Script,
                film_characters: list[FilmCharacter]) -> Notebook:
    """Fold an approved part into the notebook (returns a new one)."""
    prompt = "\n".join([
        "Bạn giữ sổ tay cho dự án video review phim. Một phần vừa được duyệt; cập nhật sổ tay.",
        "Trả về: mục của phần này (tóm tắt, điểm dừng, tình tiết còn lửng), danh sách nhân vật (giữ nhân vật cũ, "
        "bổ sung quan hệ và diễn biến) và giọng kể đang dùng. Chỉ dựa vào kịch bản, không thêm tình tiết.",
        "", f"Sổ tay hiện tại: {nb.model_dump_json()}",
        f"Nhân vật cấp phim: {json.dumps([c.model_dump() for c in film_characters], ensure_ascii=False)}",
        f"Kịch bản phần {index}:", *(f"[{b.kind}] {b.text}" for b in script.blocks)])
    out = llm.generate_json(prompt, ENTRY_SCHEMA)
    e = out["entry"]
    new = nb.model_copy(deep=True)
    new.rev += 1
    entry = NotebookEntry(job=job_id, index=index, range_label=range_label, rev=new.rev, summary=e["summary"],
                          ending=e.get("ending", ""), open_threads=e.get("open_threads", []),
                          hooks=[b.text for b in script.blocks if b.kind == "hook"])
    new.entries = sorted([x for x in new.entries if x.job != job_id] + [entry], key=lambda x: x.index)
    # shared_rev stays: this entry's rev already covers every later part, and bumping it would mark this part
    # (and the earlier ones) stale right after their own approval. Only the user's hand edits bump it.
    new.characters, new.voice = [NotebookCharacter(**c) for c in out["characters"]], out["voice"]
    return new

def _cast_key(chars: list[NotebookCharacter]) -> list[str]:
    return sorted(c.model_dump_json() for c in chars)      # order-insensitive: a reorder is not a change

def apply_user_edit(old: Notebook, new: Notebook) -> Notebook:
    """Bump revs for what the user changed by hand, so later parts show as stale."""
    nb = new.model_copy(deep=True)
    nb.rev = old.rev + 1
    before = {e.job: e for e in old.entries}
    for e in nb.entries:
        o = before.get(e.job)
        if o is None or (o.summary, o.ending, o.open_threads, o.hooks) != (e.summary, e.ending, e.open_threads, e.hooks):
            e.rev = nb.rev
        else:
            e.rev = o.rev
    if _cast_key(nb.characters) != _cast_key(old.characters) or nb.voice != old.voice:
        nb.shared_rev = nb.rev
    else:
        nb.shared_rev = old.shared_rev
    return nb

def _clock(sec: float, hours: bool) -> str:
    s = round(sec)
    h, m, s = s // 3600, s // 60 % 60, s % 60
    return f"{h:02d}:{m:02d}:{s:02d}" if hours else f"{h * 60 + m:02d}:{s:02d}"

def range_label(part: PartInfo, film: FilmInfo | None) -> str:
    if film is None or film.episode is None:
        return f"{_clock(part.start, True)}–{_clock(part.end, True)}"
    m = re.search(r"\d+", film.episode.name)
    k = int(m.group()) if m else film.episode_index + 1
    return f"Tập {k} · {_clock(part.start, False)}–{_clock(part.end, False)}"
