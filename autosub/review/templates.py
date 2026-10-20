import json
import re
from functools import cache
from pathlib import Path

@cache
def load() -> dict:
    return json.loads((Path(__file__).parent / "templates.json").read_text(encoding="utf-8"))

def _item(group: str, tid: str) -> dict:
    """Unknown id (template removed or renamed): the group's first one, so a saved setting never breaks a step."""
    items = load()[group]
    return next((t for t in items if t["id"] == tid), items[0])

def prompt(group: str, tid: str) -> str:
    return _item(group, tid)["prompt"]

def label(group: str, tid: str) -> str:
    return _item(group, tid)["label"]

def ad_patterns() -> list[re.Pattern]:
    return [re.compile(p, re.I) for p in load()["ads"]]

def edge_keywords() -> list[str]:
    return load()["edge_keywords"]
