"""The project notebook: what earlier parts told, read when writing the next script."""
from ..models import Notebook

def rev_before(nb: Notebook, index: int) -> int:
    """Notebook version a part's script depends on: the shared section and the entries of earlier parts."""
    return max([nb.shared_rev, *(e.rev for e in nb.entries if e.index < index)], default=0)

def used_hooks(nb: Notebook) -> list[str]:
    return [h for e in nb.entries for h in e.hooks]
