"""Owner/visitor access helpers."""
from __future__ import annotations


def owner_key_matches(owner_key: str | None, supplied_owner: str | None) -> bool:
    """Return whether a visitor should be treated as owner.

    Empty OWNER_KEY means unrestricted local/single-user mode. When set, only an
    exact URL query value match unlocks quota/token/training actions.
    """
    key = (owner_key or "").strip()
    if not key:
        return True
    return supplied_owner == key
