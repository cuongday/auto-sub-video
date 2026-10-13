import os
import pytest
from autosub import browse, config

@pytest.fixture
def root(tmp_path, monkeypatch):
    r = tmp_path / "host"
    (r / "Videos" / "sub").mkdir(parents=True)
    (r / "Videos" / "a.mp4").write_bytes(b"x" * 10)
    (r / "Videos" / "b.MKV").write_bytes(b"y")
    (r / "Videos" / "notes.txt").write_text("n")
    (r / "Videos" / ".hidden.mp4").write_bytes(b"h")
    (r / ".ssh").mkdir(); (r / ".ssh" / "id_rsa").write_text("secret")
    (r / "Downloads").mkdir()
    (tmp_path / "outside.mp4").write_bytes(b"o")
    monkeypatch.setattr(config, "HOST_ROOT", r)
    return r

def test_list_root_hides_dotdirs(root):
    out = browse.list_dir("")
    assert [d["name"] for d in out["dirs"]] == ["Downloads", "Videos"]
    assert out["files"] == [] and out["path"] == "" and out["parent"] is None

def test_list_shows_only_videos(root):
    out = browse.list_dir("Videos")
    assert [d["name"] for d in out["dirs"]] == ["sub"]
    assert [(f["name"], f["size"]) for f in out["files"]] == [("a.mp4", 10), ("b.MKV", 1)]
    assert out["parent"] == "" and out["files"][0]["path"] == "Videos/a.mp4"
    assert browse.list_dir("Videos/sub")["parent"] == "Videos"

@pytest.mark.parametrize("bad", ["..", "../", "Videos/../..", "/etc", ".ssh", "Videos/.hidden.mp4", "../outside.mp4"])
def test_rejects_escape_and_hidden(root, bad):
    with pytest.raises(browse.BrowseError):
        browse.resolve(bad)

def test_rejects_symlink_escape(root, tmp_path):
    os.symlink(tmp_path, root / "Videos" / "link")
    with pytest.raises(browse.BrowseError):
        browse.list_dir("Videos/link")
    os.symlink(tmp_path / "outside.mp4", root / "Videos" / "evil.mp4")
    assert "evil.mp4" not in [f["name"] for f in browse.list_dir("Videos")["files"]]
    with pytest.raises(browse.BrowseError):
        browse.video_file("Videos/evil.mp4")

def test_video_file(root):
    assert browse.video_file("Videos/a.mp4") == (root / "Videos" / "a.mp4").resolve()
    with pytest.raises(browse.BrowseError):
        browse.video_file("Videos/notes.txt")
    with pytest.raises(browse.BrowseError):
        browse.video_file("Videos")

def test_no_root(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "HOST_ROOT", tmp_path / "nope")
    assert browse.available() is False
    with pytest.raises(browse.BrowseError):
        browse.list_dir("")
