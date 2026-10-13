from pathlib import Path
from ..models import Word
from .align import align_tokens

_MODEL: dict = {}

class FunASRZH:
    def __init__(self, model: str = ""):
        self.model = model or "paraformer-zh"

    def _load(self):
        if self.model not in _MODEL:
            from funasr import AutoModel
            _MODEL[self.model] = AutoModel(model=self.model, vad_model="fsmn-vad", punc_model="ct-punc",
                                           device="cpu", disable_update=True, disable_pbar=True, log_level="ERROR")
        return _MODEL[self.model]

    def transcribe(self, wav16k: Path, progress=None) -> list[Word]:
        res = self._load().generate(input=str(wav16k), batch_size_s=300, sentence_timestamp=False)
        words: list[Word] = []
        for r in res or []:
            words += align_tokens(r.get("text", ""), r.get("timestamp") or [])
        if progress:
            progress(1.0)
        return words
