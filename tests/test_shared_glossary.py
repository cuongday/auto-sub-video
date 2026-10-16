from autosub import glossary, store
from autosub.models import Character, GlossaryItem, TranslationContext
from tests.test_pipeline import Rig

def test_crud():
    assert glossary.load() == {"terms": [], "characters": []}
    glossary.save({"terms": [{"source": "苹果", "vi": "Apple"}], "characters": [{"name": "小明", "vi_name": "Tiểu Minh", "addressing": "em"}]})
    g = glossary.load()
    assert g["terms"][0]["vi"] == "Apple" and g["characters"][0]["vi_name"] == "Tiểu Minh"

def test_merge_shared_wins_over_auto_context():
    glossary.save({"terms": [{"source": "绝区零", "vi": "Zenless Zone Zero"}],
                   "characters": [{"name": "小明", "vi_name": "Minh", "addressing": "tớ/cậu"}]})
    ctx = TranslationContext(characters=[Character(name="小明", vi_name="Tiểu Minh", addressing="em")],
                             glossary=[GlossaryItem(source="绝区零", vi="Tuyệt Khu Linh"), GlossaryItem(source="手柄", vi="tay cầm")])
    out = glossary.merge(ctx)
    assert {g.source: g.vi for g in out.glossary} == {"绝区零": "Zenless Zone Zero", "手柄": "tay cầm"}
    assert [(c.vi_name, c.addressing) for c in out.characters] == [("Minh", "tớ/cậu")]

def test_promote_from_job_context():
    ctx = TranslationContext(glossary=[GlossaryItem(source="铰链", vi="bản lề")],
                             characters=[Character(name="Kaiann", vi_name="Kaiann", addressing="bà")])
    glossary.add_from(ctx)
    glossary.add_from(ctx)                      # idempotent
    g = glossary.load()
    assert g["terms"] == [{"source": "铰链", "vi": "bản lề"}] and len(g["characters"]) == 1

def test_translation_prompt_uses_shared_terms(tmp_path):
    glossary.save({"terms": [{"source": "公园", "vi": "CÔNG-VIÊN-CHUNG"}], "characters": []})
    rig = Rig(tmp_path)
    rig.run(mode="review")
    assert any("CÔNG-VIÊN-CHUNG" in p for p in rig.llm.prompts if "<<<ITEMS" in p)
    assert {g.source: g.vi for g in store.load_context(rig.job.id).glossary}["公园"] == "CÔNG-VIÊN-CHUNG"
