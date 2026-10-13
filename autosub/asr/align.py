"""Map FunASR output (text + one [start_ms, end_ms] per token) to Words."""
import re
from ..models import Word

# a CJK char, or a run of latin letters/digits/apostrophes
_TOKEN = re.compile(r"[㐀-鿿豈-﫿]|[A-Za-z0-9']+")

def align_tokens(text: str, timestamps: list[list[int]]) -> list[Word]:
    if not text or not timestamps:
        return []
    tokens: list[str] = []
    pos = 0
    for m in _TOKEN.finditer(text):
        if tokens and m.start() > pos:
            tokens[-1] += text[pos:m.start()].strip()     # punctuation sticks to the previous token
        tokens.append(m.group())
        pos = m.end()
    if tokens and pos < len(text):
        tokens[-1] += text[pos:].strip()
    n, k = len(tokens), len(timestamps)
    out = []
    for i, tok in enumerate(tokens):
        a, b = timestamps[i] if n == k else timestamps[min(k - 1, i * k // n)]
        out.append(Word(text=tok, start=a / 1000, end=b / 1000))
    return out
