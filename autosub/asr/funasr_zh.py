from pathlib import Path
from ..models import Word
from .align import align_tokens

_MODEL: dict = {}

TURN_GAP = 0.8      # s: a pause this long inside a sentence usually is a speaker change
_SENT_END = tuple("。！？!?.")

def _fix_turn_starts(words: list[Word]) -> None:
    """CAM++ labels whole VAD sentences. When a pause of TURN_GAP or more splits a run of one speaker and
    the words after it run (without another long pause) into a different speaker, those words belong
    to that next speaker - e.g. "...出门。好 | 的，我们开始" where "的，" is the teacher's."""
    i = 1
    while i < len(words):
        if words[i].start - words[i - 1].end >= TURN_GAP and words[i].speaker == words[i - 1].speaker:
            j = i
            while j + 1 < len(words) and words[j + 1].speaker == words[i].speaker \
                    and words[j + 1].start - words[j].end < TURN_GAP:
                j += 1
            if j + 1 < len(words) and words[j + 1].speaker != words[i].speaker \
                    and words[j + 1].start - words[j].end < TURN_GAP:
                # the ASR often stamps the first word of the new turn right after the previous sentence's
                # full stop ("门。好 ... 的，"): pull up to 2 such words over to the new speaker as well
                start = i
                for m in range(i - 1, max(0, i - 3), -1):
                    if words[m - 1].text.strip().endswith(_SENT_END):
                        start = m
                        break
                for w in words[start:j + 1]:
                    w.speaker = words[j + 1].speaker
            i = j + 1
        else:
            i += 1

class FunASRZH:
    def __init__(self, model: str = "", diarize: bool = False):
        self.model = model or "paraformer-zh"
        self.diarize = diarize

    def _load(self):
        key = (self.model, self.diarize)
        if key not in _MODEL:
            from funasr import AutoModel
            extra = {"spk_model": "cam++"} if self.diarize else {}
            _MODEL[key] = AutoModel(model=self.model, vad_model="fsmn-vad", punc_model="ct-punc", device="cpu",
                                    disable_update=True, disable_pbar=True, log_level="ERROR", **extra)
        return _MODEL[key]

    def transcribe(self, wav16k: Path, progress=None) -> list[Word]:
        res = self._load().generate(input=str(wav16k), batch_size_s=300, sentence_timestamp=False)
        words: list[Word] = []
        for r in res or []:
            sents = r.get("sentence_info") if self.diarize else None
            if sents:
                # align each sentence with its own timestamps, so speaker turns land on the right words
                for si in sents:
                    ws = align_tokens(si.get("text", ""), si.get("timestamp") or [])
                    for w in ws:
                        w.speaker = si.get("spk")
                    words += ws
                _fix_turn_starts(words)
            else:
                words += align_tokens(r.get("text", ""), r.get("timestamp") or [])
        if progress:
            progress(1.0)
        return words
