from pathlib import Path
from typing import Callable, Protocol
from ..models import Word

class ASR(Protocol):
    def transcribe(self, wav16k: Path, progress: Callable[[float], None] | None = None) -> list[Word]: ...
