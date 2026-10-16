"""Free storage on finished jobs by deleting intermediate files that are cheap to rebuild.

Kept: the source video, results (output.mp4, subs, voice.wav, mix.m4a), the separated music stem and
16 kHz speech (Demucs is the slow step), the TTS lines, all JSON. Deleted: the full-rate audio
extract, the full-rate vocal stem, the unmixed voice track and the setup preview. A step that needs
one of them again regenerates it from what is kept (see pipeline.REBUILD)."""
from . import store
from .storage import get_store
from .workdir import job_prefix

PRUNABLE = ["audio.wav", "vocals.wav", "voice_raw.wav", "preview.mp4"]
# output_softsub.mp4 is kept: the user asked for it explicitly

def reclaimable(jid: str) -> int:
    sizes = store.object_sizes(jid)
    return sum(sizes.get(n, 0) for n in PRUNABLE)

def prune(jid: str) -> int:
    """Delete prunable intermediates of a job; returns bytes freed."""
    job = store.load(jid)
    sizes = store.object_sizes(jid)
    st = get_store()
    freed = 0
    for name in PRUNABLE:
        if name in sizes:
            st.delete(job_prefix(jid) + name)
            freed += sizes[name]
            if name not in job.pruned:
                job.pruned.append(name)
    store.save(job)
    return freed
