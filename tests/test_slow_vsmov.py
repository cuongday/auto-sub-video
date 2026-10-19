"""Live vsmov site (network). make test-slow"""
import pytest
from autosub import media, vsmov

pytestmark = pytest.mark.slow

def test_live_first_segment(tmp_path):
    d = vsmov.movie("avengers-4-hoi-ket-178544376755563")
    embed_url = next(s for s in d.servers if s.name == d.default_server).episodes[0].embed
    e = vsmov.parse_embed(vsmov._fetch(embed_url).decode())
    hdr = {"Referer": embed_url, "Origin": e.base_url}
    text = vsmov._fetch(e.master_url, hdr).decode()
    pl = vsmov.pick_variant(text, e.master_url)
    if pl != e.master_url:
        text = vsmov._fetch(pl, hdr).decode()
    first = vsmov.segment_urls(text, pl)[0]
    seg = tmp_path / "seg.ts"
    seg.write_bytes(vsmov.strip_png(vsmov._fetch(first, hdr)))
    assert media.probe(seg).width > 0
    assert e.subtitles and vsmov.fetch_subtitle(e.subtitles[0].url, embed_url).lstrip().startswith("WEBVTT")
