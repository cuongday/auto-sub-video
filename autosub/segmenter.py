"""Group timed words into subtitle lines."""
import re
from .models import Lang, Segment, Word

MAX_CHARS = {"zh": 20, "en": 42, "ko": 24, "vi": 42}
SENTENCE_END = tuple("。！？!?.;；…")
CLAUSE_END = tuple("，,、：:")
_NO_SPACE_BEFORE = re.compile(r"^[,.!?;:%)\]}…'’”]")
_CJK = re.compile(r"[\u3000-\u303f\u4e00-\u9fff\uff00-\uffef]")

def text_len(text: str, lang: Lang) -> int:
    return len(re.sub(r"\s+", "", text)) if lang == "zh" else len(text)

def join_words(words: list[Word], lang: Lang) -> str:
    if lang == "zh":
        return "".join(w.text.strip() for w in words)
    out = ""
    for w in words:
        t = w.text.strip()
        if not t:
            continue
        # Chinese inside a mixed transcript: no space between its words, nor after its punctuation ("開始, 向" -> "開始,向")
        glued = not out or _NO_SPACE_BEFORE.match(t) or (_CJK.match(t) and _CJK.match(out.rstrip(",.!?;:，。！？")[-1:]))
        out += t if glued else " " + t
    return out

def _too_big(chunk: list[Word], lang: Lang, max_dur: float) -> bool:
    return (chunk[-1].end - chunk[0].start > max_dur) or text_len(join_words(chunk, lang), lang) > MAX_CHARS[lang]

def _split_point(chunk: list[Word]) -> int:
    """Index i: chunk is split into chunk[:i] and chunk[i:]. Prefer clause punctuation near the middle,
    then the largest pause, then the middle word."""
    n = len(chunk)
    mid = n / 2
    clauses = [i + 1 for i in range(n - 1) if chunk[i].text.strip().endswith(CLAUSE_END + SENTENCE_END)]
    if clauses:
        return min(clauses, key=lambda i: abs(i - mid))
    gaps = [(chunk[i + 1].start - chunk[i].end, i + 1) for i in range(n - 1)]
    best_gap, idx = max(gaps)
    if best_gap > 0.15:
        return idx
    return max(1, round(mid))

def _split_big(chunk: list[Word], lang: Lang, max_dur: float) -> list[list[Word]]:
    if len(chunk) < 2 or not _too_big(chunk, lang, max_dur):
        return [chunk]
    i = _split_point(chunk)
    return _split_big(chunk[:i], lang, max_dur) + _split_big(chunk[i:], lang, max_dur)

def build_segments(words: list[Word], lang: Lang, *, max_dur: float = 6.0, min_dur: float = 1.0,
                   gap: float = 0.4, merge_gap: float = 0.3) -> list[Segment]:
    words = [w for w in words if w.text.strip()]
    if not words:
        return []
    chunks: list[list[Word]] = [[]]
    for i, w in enumerate(words):
        chunks[-1].append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        speaker_change = nxt is not None and w.speaker is not None and nxt.speaker is not None and nxt.speaker != w.speaker
        if nxt and (w.text.strip().endswith(SENTENCE_END) or nxt.start - w.end > gap or speaker_change):
            chunks.append([])
    chunks = [c for big in chunks for c in _split_big(big, lang, max_dur)]

    merged: list[list[Word]] = []
    dur = lambda c: c[-1].end - c[0].start  # noqa: E731
    for c in chunks:
        same_speaker = not merged or c[0].speaker is None or merged[-1][-1].speaker is None \
            or c[0].speaker == merged[-1][-1].speaker
        if merged and same_speaker and (dur(c) < min_dur or dur(merged[-1]) < min_dur) \
                and c[0].start - merged[-1][-1].end < merge_gap and not _too_big(merged[-1] + c, lang, max_dur):
            merged[-1] = merged[-1] + c
        else:
            merged.append(c)
    return [Segment(id=i, start=round(c[0].start, 3), end=round(c[-1].end, 3), source=join_words(c, lang))
            for i, c in enumerate(merged, 1)]
