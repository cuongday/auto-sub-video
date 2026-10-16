"""Who speaks each line, and which TTS voice reads it."""
from collections import Counter
from .models import JobSettings, Segment, Word

def assign_speakers(segs: list[Segment], words: list[Word]) -> list[Segment]:
    """Label each line with the speaker of most of its words (time overlap)."""
    labelled = [w for w in words if w.speaker is not None]
    if not labelled:
        return segs
    for s in segs:
        votes = Counter()
        for w in labelled:
            overlap = min(s.end, w.end) - max(s.start, w.start)
            if overlap > 0:
                votes[w.speaker] += overlap
        s.speaker = votes.most_common(1)[0][0] if votes else None
    return segs

def speakers_of(segs: list[Segment]) -> dict[int, int]:
    """speaker -> number of lines, in order of first appearance."""
    out: dict[int, int] = {}
    for s in segs:
        if s.speaker is not None:
            out[s.speaker] = out.get(s.speaker, 0) + 1
    return out

def voice_for(settings: JobSettings, seg: Segment) -> str:
    if seg.speaker is not None:
        v = settings.speaker_voices.get(str(seg.speaker))
        if v:
            return v
    return settings.tts_voice
