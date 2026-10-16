"""Glossary shared by every job (names, terms, forms of address), stored in MinIO as glossary.json.

When a job's translation context is analyzed, shared entries override what the LLM proposed for the same
source text, so a channel's recurring names and terms stay consistent across videos."""
from .models import Character, GlossaryItem, TranslationContext
from .storage import get_store, read_json, write_json

KEY = "glossary.json"

def load() -> dict:
    d = read_json(get_store(), KEY, default={}) or {}
    return {"terms": d.get("terms", []), "characters": d.get("characters", [])}

def save(data: dict) -> dict:
    terms = [{"source": t["source"].strip(), "vi": t["vi"].strip()} for t in data.get("terms", [])
             if t.get("source", "").strip() and t.get("vi", "").strip()]
    chars = [{"name": c["name"].strip(), "vi_name": c.get("vi_name", "").strip(), "addressing": c.get("addressing", "").strip()}
             for c in data.get("characters", []) if c.get("name", "").strip()]
    write_json(get_store(), KEY, {"terms": terms, "characters": chars})
    return load()

def merge(ctx: TranslationContext) -> TranslationContext:
    g = load()
    terms = {t["source"]: t["vi"] for t in g["terms"]}
    chars = {c["name"]: c for c in g["characters"]}
    out = ctx.model_copy(deep=True)
    seen = set()
    out.glossary = []
    for item in ctx.glossary:
        out.glossary.append(GlossaryItem(source=item.source, vi=terms.get(item.source, item.vi)))
        seen.add(item.source)
    out.glossary += [GlossaryItem(source=s, vi=v) for s, v in terms.items() if s not in seen]
    names = set()
    out.characters = []
    for c in ctx.characters:
        shared = chars.get(c.name)
        out.characters.append(Character(**shared) if shared else c)
        names.add(c.name)
    out.characters += [Character(**c) for n, c in chars.items() if n not in names]
    return out

def add_from(ctx: TranslationContext) -> dict:
    """Copy a job's context entries into the shared glossary (existing shared entries win)."""
    g = load()
    have_t = {t["source"] for t in g["terms"]}
    have_c = {c["name"] for c in g["characters"]}
    g["terms"] += [{"source": t.source, "vi": t.vi} for t in ctx.glossary if t.source not in have_t]
    g["characters"] += [c.model_dump() for c in ctx.characters if c.name not in have_c]
    return save(g)
