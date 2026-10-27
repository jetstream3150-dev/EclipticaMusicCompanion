"""Boss element information sourced from the MIT-licensed EclipticaHUD-C table.

This is an independent reader for the unmodified table; values are estimates,
may become stale, and must not be treated as game state or guaranteed damage.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

ELEMENTS = {
    "physical": "物", "fire": "火", "frost": "氷", "electric": "電",
    "luminous": "光", "shadow": "闇", "poison": "毒", "others": "その他",
}
# Internal object names differ from the display names in the source table.
ALIASES = {
    "flylord": "beelzebub", "queenbug": "vesra", "gravetender": "thegravetender",
    "blacklily": "theblacklily", "jackedpumpkin": "jackedolantern",
    "antking": "khepri", "jimbringer": "jimcbringer", "stagebringer": "jimcbringer",
    "manalyteancient": "abaddon", "queenvolt": "zaveah",
}


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.casefold())


def _table_name(name: str) -> tuple[str, int | None]:
    name = re.sub(r"\(clone\)\s*$", "", str(name), flags=re.I).strip()
    m = re.search(r"(?:phase\s*(\d+)|\(p\s*(\d+)\))\s*$", name, re.I)
    phase = int(m.group(1) or m.group(2)) if m else None
    if m:
        name = name[:m.start()].strip()
    base = _key(name)
    return ALIASES.get(base, base), phase


def parse_table(text: str) -> dict[tuple[str, int | None], dict]:
    table = {}
    for section in re.split(r"(?m)^\s*---\s*$", text):
        lines = [line.strip() for line in section.splitlines() if line.strip()]
        if not lines:
            continue
        name = lines[0]
        elements, notes = [], []
        for line in lines[1:]:
            key, sep, value = line.partition(":")
            if not sep:
                continue
            value = value.strip()
            if key.casefold() == "ja":
                notes.append(value)
            elif key.casefold() in ELEMENTS:
                # Keep symbolic values (e.g. 1+x) instead of guessing a number.
                kind = "neutral"
                number = re.match(r"^(\d+(?:\.\d+)?)([+-]?)x", value, re.I)
                if number:
                    n, suffix = float(number.group(1)), number.group(2)
                    kind = "weak" if suffix == "+" or (not suffix and n > 1) else "resist" if suffix == "-" or n < 1 else "neutral"
                elements.append({"name": ELEMENTS[key.casefold()], "value": value, "kind": kind})
        table[_table_name(name)] = {"name": name, "elements": elements, "notes": notes}
    return table


@lru_cache(maxsize=1)
def load_table(path: str) -> dict:
    try:
        return parse_table(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        return {}


def lookup(name: str, data_path: str) -> dict:
    """Only choose an explicitly matched phase; never substitute phase 1 for phase 2."""
    table = load_table(data_path)
    base, phase = _table_name(name)
    if not base:
        return {"available": False, "name": "", "elements": [], "notes": []}
    entry = table.get((base, phase))
    if entry is None and phase is None:
        entry = table.get((base, 1))
    if entry is None and phase is not None and (base, None) in table:
        entry = table[(base, None)]
    if entry is None:
        return {"available": False, "name": str(name)[:90], "elements": [], "notes": []}
    return {"available": True, **entry}
