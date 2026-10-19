from autosub.models import (Episode, FilmCharacter, FilmInfo, Notebook, NotebookCharacter, NotebookEntry, PartInfo,
                            Script, ScriptBlock)
from autosub.review.notebook import apply_user_edit, is_stale, range_label, record_part, rev_before, used_hooks
from tests.fakes import FakeLLM, review_llm_hook

SCRIPT = Script(blocks=[ScriptBlock(id=1, kind="hook", text="Câu hook?"), ScriptBlock(id=2, kind="than", text="Thân.")])

def rec(nb, job, index, llm=None):
    return record_part(llm or FakeLLM(review_llm_hook), nb, job_id=job, index=index, range_label="r", script=SCRIPT,
                       film_characters=[FilmCharacter(name="Tiểu Minh")])

def test_rev_flow_matches_spec():
    nb = rec(Notebook(), "p1", 1)
    part2 = PartInfo(film_job="f", index=2, start=0, end=1, notebook_rev=rev_before(nb, 2))
    assert not is_stale(nb, part2)
    nb = rec(nb, "p2", 2)
    assert not is_stale(nb, part2)
    nb = rec(nb, "p1", 1)
    assert is_stale(nb, part2) and [e.job for e in nb.entries] == ["p1", "p2"]
    assert nb.rev == 3 and nb.entries[0].hooks == ["Câu hook?"]

def test_record_part_does_not_mutate_and_sorts():
    old = rec(Notebook(), "p2", 2)
    snap = old.model_copy(deep=True)
    nb = rec(old, "p1", 1)
    assert old == snap and [e.index for e in nb.entries] == [1, 2]

def test_user_character_edit_makes_later_parts_stale():
    nb = rec(Notebook(), "p1", 1)
    part2 = PartInfo(film_job="f", index=2, start=0, end=1, notebook_rev=rev_before(nb, 2))
    new = nb.model_copy(deep=True)
    new.characters[0].name = "Tiểu Long"
    out = apply_user_edit(nb, new)
    assert out.rev == nb.rev + 1 and out.shared_rev == out.rev and is_stale(out, part2)

def test_user_entry_edit_bumps_only_that_entry():
    nb = rec(rec(Notebook(), "p1", 1), "p2", 2)
    new = nb.model_copy(deep=True)
    new.entries[0].summary = "khác"
    out = apply_user_edit(nb, new)
    assert out.entries[0].rev == out.rev and out.entries[1].rev == nb.entries[1].rev and out.shared_rev == nb.shared_rev

def test_used_hooks_from_entries():
    nb = rec(rec(Notebook(), "p1", 1), "p2", 2)
    assert used_hooks(nb) == ["Câu hook?", "Câu hook?"]

def test_range_label():
    assert range_label(PartInfo(film_job="f", index=1, start=5530, end=8100), None) == "01:32:10–02:15:00"
    f = FilmInfo(episode=Episode(name="Tập 3", slug="s", embed="e"), episode_index=2)
    assert range_label(PartInfo(film_job="f", index=1, start=0, end=1350), f) == "Tập 3 · 00:00–22:30"
    f = FilmInfo(episode=Episode(name="Full", slug="s", embed="e"), episode_index=4)
    assert range_label(PartInfo(film_job="f", index=1, start=0, end=60), f).startswith("Tập 5 · ")
