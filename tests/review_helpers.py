"""A review project with one prepared-able film job and fake engines (shared by the review-phim tests)."""
import shutil
import pytest
from autosub import media, pipeline, projects, store, workdir
from autosub.models import FilmInfo, MovieMeta
from autosub.projects import ReviewProject
from autosub.storage import get_store
from tests.fakes import FakeASR, FakeLLM, FakeTTS, fake_separate, review_llm_hook
from tests.fixtures import make_video

VTT_20S = """WEBVTT

00:00:01.000 --> 00:00:03.000
Anh đi đâu vậy?

00:00:04.000 --> 00:00:06.500
Tôi về làng tìm Tiểu Minh.

00:00:09.000 --> 00:00:11.000
Xem phim miễn phí tại phimhay.xyz

00:00:12.000 --> 00:00:15.000
Đừng đi, ngoài kia nguy hiểm lắm!

00:00:16.000 --> 00:00:18.500
Tôi đã hứa với cậu ấy rồi.
"""

class ReviewRig:
    def __init__(self, tmp_path, seconds=20, subtitles: str | None = VTT_20S):
        self.src = make_video(tmp_path / "film.mp4", seconds=seconds)
        self.subtitles = subtitles
        self.sep_calls = []
        self.asr, self.llm, self.tts = FakeASR(), FakeLLM(review_llm_hook), FakeTTS()
        self.engines = pipeline.Engines(separate=fake_separate(self.sep_calls), asr=lambda lang, model, **kw: self.asr,
                                        llm=lambda p, m: self.llm, tts=lambda name: self.tts)
        movie = MovieMeta(name="Phim thử", origin_name="Test Film", actors=["Diễn viên A"])
        self.project = projects.create("Phim thử", "vsmov:phim-thu", kind="review",
                                       review=ReviewProject(source="vsmov", movie=movie))
        self.film = self.add_film()

    def add_film(self, episode_index: int = 0):
        job = store.create(f"Phim thử · Tập {episode_index + 1}", "source.mp4", uploaded=True, kind="film")
        w = workdir.WorkDir(job.id)
        shutil.copyfile(self.src, w.local(job.source))
        w.push(job.source)
        job.info = media.probe(self.src)
        job.project = self.project.id
        job.film = FilmInfo(episode_index=episode_index, subtitle="vie" if self.subtitles is not None else None)
        if self.subtitles is not None:
            get_store().put_bytes(store.key(job.id, "subs/vie.vtt"), self.subtitles.encode())
        store.save(job)
        return job

    def run(self, jid, **kw):
        return pipeline.run(jid, engines=self.engines, **kw)

    def film_done(self):
        return self.run(self.film.id, mode="auto")

    def part(self, index=1, start=0, end=20):
        """One review part of the film covering [start, end] (needs parts.py)."""
        from autosub.review import parts
        film = store.load(self.film.id)
        cuts = [c for c in (start, end) if 0 < c < film.info.duration]  # interior boundaries
        jobs = parts.create_parts(film, cuts)
        return next(j for j in jobs if j.part.index == index)

@pytest.fixture
def review_rig(tmp_path):
    return ReviewRig(tmp_path)
