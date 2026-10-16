from autosub import store
from autosub.models import JobSettings, Segment, Word
from autosub.segmenter import build_segments
from autosub.speakers import assign_speakers, speakers_of, voice_for
from tests.test_pipeline import Rig

def w(t, a, b, spk=None): return Word(text=t, start=a, end=b, speaker=spk)

def test_segment_speaker_is_majority_of_its_words():
    words = [w("你", 0, .2, 0), w("好", .2, .4, 0), w("。", .4, .5, 0), w("对", 1.5, 1.7, 1), w("不", 1.7, 1.9, 1),
             w("起", 1.9, 2.1, 1), w("。", 2.1, 2.2, 1)]
    segs = assign_speakers(build_segments(words, "zh"), words)
    assert [s.speaker for s in segs] == [0, 1]

def test_split_on_speaker_change_without_pause():
    words = [w("你", 0, .2, 0), w("好", .2, .4, 0), w("对", .45, .6, 1), w("不", .6, .8, 1), w("起", .8, 1.0, 1)]
    segs = build_segments(words, "zh", min_dur=0.1)
    assert [s.source for s in segs] == ["你好", "对不起"]

def test_voice_for_speaker():
    st = JobSettings(tts_voice="A", speaker_voices={"1": "B"})
    assert voice_for(st, Segment(id=1, start=0, end=1, source="", speaker=1)) == "B"
    assert voice_for(st, Segment(id=1, start=0, end=1, source="", speaker=0)) == "A"
    assert voice_for(st, Segment(id=1, start=0, end=1, source="", speaker=None)) == "A"

def test_speakers_of():
    segs = [Segment(id=i, start=i, end=i + 1, source="x", speaker=s) for i, s in enumerate([0, 1, 0, None, 2])]
    assert speakers_of(segs) == {0: 2, 1: 1, 2: 1}

def test_pipeline_uses_per_speaker_voice(tmp_path):
    rig = Rig(tmp_path)
    rig.asr.speakers = True                   # fake ASR alternates speakers per sentence
    job = store.load(rig.job.id)
    job.settings.tts_voice = "main"; job.settings.speaker_voices = {"1": "second"}
    store.save(job)
    rig.run(mode="auto")
    segs = store.load_segments(rig.job.id)
    assert {s.speaker for s in segs} == {0, 1}
    assert {(t, v) for t, _, v in rig.tts.calls if v} >= {(segs[0].vi, "main"), (segs[1].vi, "second")}

def test_funasr_aligns_each_sentence_with_its_own_timestamps(monkeypatch):
    from autosub.asr import funasr_zh
    class M:
        def generate(self, **kw):
            return [{"text": "我下次出门。好的，", "timestamp": [[0, 100]] * 7, "sentence_info": [
                {"spk": 2, "text": "我下次出门。", "timestamp": [[7530, 7750], [7750, 7910], [7910, 8109], [8109, 8210], [8210, 8330]]},
                {"spk": 0, "text": "好的，", "timestamp": [[10630, 10750], [10750, 10990]]}]}]
    asr = funasr_zh.FunASRZH(diarize=True)
    monkeypatch.setattr(asr, "_load", lambda: M())
    words = asr.transcribe("x.wav")
    assert [(w.text, w.speaker, w.start) for w in words[-2:]] == [("好", 0, 10.63), ("的，", 0, 10.75)]

def test_turn_start_glued_to_previous_sentence_moves_to_next_speaker():
    from autosub.asr.funasr_zh import _fix_turn_starts
    ws = [w("出", 8.49, 8.63, 2), w("门。", 8.63, 8.73, 2), w("好", 8.73, 8.97, 2), w("的，", 10.71, 10.95, 2),
          w("我", 11.25, 11.37, 0), w("们", 11.37, 11.47, 0)]
    _fix_turn_starts(ws)
    assert [x.speaker for x in ws] == [2, 2, 0, 0, 0, 0]       # "好" after the full stop goes with "的，"

def test_pause_without_turn_keeps_speaker():
    from autosub.asr.funasr_zh import _fix_turn_starts
    ws = [w("你", 0, .2, 1), w("好", 1.5, 1.7, 1), w("吗", 1.7, 1.9, 1)]
    _fix_turn_starts(ws)
    assert [x.speaker for x in ws] == [1, 1, 1]
