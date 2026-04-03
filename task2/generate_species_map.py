#!/usr/bin/env python3
"""
Build species_map.json: English species names -> deterministic fictional names.
Uses PokeAPI CSV (English, language id 9). Curated overrides keep key aliases
aligned with terms_map / story names.

Run: python3 generate_species_map.py
Requires network once; commit species_map.json for offline builds.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "species_map.json"
CSV_URL = (
    "https://raw.githubusercontent.com/PokeAPI/pokeapi/master/data/v2/csv/"
    "pokemon_species_names.csv"
)

# Manual names (must match obfuscation style used in the course KB).
CURATED: dict[str, str] = {
    "Pikachu": "Zepkiru",
    "Raichu": "Voltriarch",
    "Charizard": "Pyrothyr",
    "Mewtwo": "Orphic Null",
    "Eevee": "Auron",
    "Snorlax": "Slumbark",
    "Bulbasaur": "Sprigthorn",
    "Squirtle": "Droplet",
    "Meowth": "Whiskalk",
    "Pichu": "Pyxie",
    "Arbok": "Coilfang",
}

SYL = (
    "kor",
    "vel",
    "thyn",
    "rax",
    "mira",
    "sel",
    "dor",
    "fen",
    "quor",
    "lex",
    "jin",
    "yel",
    "wren",
    "vax",
    "gol",
    "helm",
    "nia",
    "styr",
    "trel",
    "phor",
    "bryn",
    "cair",
    "dros",
    "myre",
)


def synth_name(canonical: str) -> str:
    h = hashlib.sha256(canonical.lower().encode()).digest()
    a = SYL[h[0] % len(SYL)]
    b = SYL[h[1] % len(SYL)]
    c = SYL[h[2] % len(SYL)]
    return (a + b + c).capitalize()


def fetch_rows() -> list[dict[str, str]]:
    with urlopen(CSV_URL, timeout=120) as r:
        text = r.read().decode("utf-8")
    rows = list(csv.DictReader(text.splitlines()))
    return [row for row in rows if row.get("local_language_id") == "9"]


def main() -> None:
    rows = fetch_rows()
    out: dict[str, str] = {}
    for row in rows:
        name = row["name"].strip()
        if not name:
            continue
        if name in CURATED:
            out[name] = CURATED[name]
        else:
            out[name] = synth_name(name)
    # Curated entries not in National Dex (should not happen)
    for k, v in CURATED.items():
        out[k] = v
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(out)} species -> {OUT}")


if __name__ == "__main__":
    main()
