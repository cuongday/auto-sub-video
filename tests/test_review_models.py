from autosub import projects, store
from autosub.models import PartInfo, MovieMeta
from autosub.projects import ReviewProject
from autosub.review import templates
from autosub.storage import get_store, write_json

def test_job_with_part_roundtrips():
    j = store.create("p", kind="review"); j.part = PartInfo(film_job="f", index=1, start=0, end=60)
    store.save(j); assert store.load(j.id).part.end == 60

def test_review_project_roundtrip():
    p = projects.create("Phim", "vsmov:x", kind="review", review=ReviewProject(source="vsmov", movie=MovieMeta(name="X")))
    assert projects.get(p.id).review.settings.aspect == "9:16"
    assert projects.music_key(p.id, ".mp3") == f"projects/{p.id}/music.mp3"

def test_old_projects_json_is_sub():
    write_json(get_store(), projects.KEY, {"a": {"id": "a", "name": "Cũ", "created": 1}})
    assert projects.list_projects()[0].kind == "sub"

def test_templates_have_spec_labels():
    assert [t["label"] for t in templates.load()["styles"]] == ["Kịch tính", "Hài hước", "Nghiêm túc / phân tích", "Kể chuyện nhẹ nhàng"]
    assert templates.label("hooks", "ban_co_biet") == '"Bạn có biết…"'
    assert templates.prompt("openings", "vao_thang")
    assert templates.ad_patterns()[0].search("xem tai http://x.com")
    assert "vietsub" in templates.edge_keywords()

def test_unknown_template_id_falls_back_to_first():
    assert templates.prompt("hooks", "nope") == templates.load()["hooks"][0]["prompt"]
