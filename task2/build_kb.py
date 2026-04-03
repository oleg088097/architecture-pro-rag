#!/usr/bin/env python3
"""
Fetch Pokémon Fandom wiki pages via MediaWiki API, strip HTML to plain text,
apply terms_map.json + species_map.json, then residual Poké* / pokemon cleanup.

Source: https://pokemon.fandom.com — parseable HTML via api.php (Cloudflare-safe).
"""

from __future__ import annotations

import html as html_module
import json
import re
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
KB_DIR = ROOT / "knowledge_base"
TERMS_PATH = ROOT / "terms_map.json"
SPECIES_PATH = ROOT / "species_map.json"

API = "https://pokemon.fandom.com/api.php"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; rv:109.0) Gecko/20100101 Firefox/115.0 "
    "(KnowledgeBaseBuilder/1.0; +local RAG task)"
)

# 30+ entity pages (characters, regions, items, mechanics, types).
WIKI_PAGES: list[str] = [
    "Pikachu",
    "Charizard",
    "Mewtwo",
    "Ash Ketchum",
    "Team Rocket",
    "Kanto",
    "Johto",
    "Hoenn",
    "Poke Ball",
    "Indigo League",
    "Professor Oak",
    "Gym Leader",
    "Eevee",
    "Snorlax",
    "Bulbasaur",
    "Squirtle",
    "Giovanni",
    "Elite Four",
    "Pallet Town",
    "Cerulean City",
    "Electric type",
    "Fire type",
    "Water type",
    "Pokémon Trainer",
    "Galar",
    "Legendary Pokémon",
    "Mythical Pokémon",
    "Pokémon Center",
    "Master Ball",
    "Meowth",
    "Jessie",
    "James",
    "Misty",
    "Brock",
    "Great Ball",
    "Ultra Ball",
    "Pokédex",
    "Gym Badge",
]


def api_parse(page_title: str) -> dict:
    """
    MediaWiki parse response (success): top-level keys include "parse" with
    "title", "pageid", optional "redirects", and "text": {"*": "<html>…"}.
    Errors return {"error": {...}} (no "parse").
    """
    q = urlencode(
        {
            "action": "parse",
            "page": page_title,
            "prop": "text",
            "format": "json",
            "redirects": "1",
        }
    )
    url = f"{API}?{q}"
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


class _WikiPlainTextExtractor(HTMLParser):
    """
    Emit visible text only; drop wiki tables, <aside> (infobox / Information),
    portable-infobox trees, citation/reference lists, [edit] spans, <sup>
    reference markers, the table of contents (#toc), <figure>/<figcaption>,
    and Fandom image galleries (div.wikia-gallery and nested slideshow/caption UI).
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._table_depth = 0
        self._aside_depth = 0
        self._infobox_div_depth = 0
        self._reflist_div_depth = 0
        self._toc_div_depth = 0
        self._gallery_div_depth = 0
        self._figure_depth = 0
        self._figcaption_depth = 0
        self._ref_ol_depth = 0
        self._sup_ref_depth = 0
        self._editsection_depth = 0

    @staticmethod
    def _class_attr(attrs: list[tuple[str, str | None]]) -> str:
        for k, v in attrs:
            if k == "class" and v:
                return v
        return ""

    @staticmethod
    def _id_attr(attrs: list[tuple[str, str | None]]) -> str:
        for k, v in attrs:
            if k == "id" and v:
                return v
        return ""

    def _skip(self) -> bool:
        return (
            self._table_depth > 0
            or self._aside_depth > 0
            or self._infobox_div_depth > 0
            or self._reflist_div_depth > 0
            or self._toc_div_depth > 0
            or self._gallery_div_depth > 0
            or self._figure_depth > 0
            or self._figcaption_depth > 0
            or self._ref_ol_depth > 0
            or self._sup_ref_depth > 0
            or self._editsection_depth > 0
        )

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        cls = self._class_attr(attrs)
        if tag == "figure":
            self._figure_depth += 1
            return
        if tag == "figcaption":
            self._figcaption_depth += 1
            return
        if tag == "table":
            self._table_depth += 1
            return
        if tag == "aside":
            self._aside_depth += 1
            return
        if tag == "div":
            div_id = self._id_attr(attrs)
            if self._toc_div_depth > 0:
                self._toc_div_depth += 1
            elif div_id == "toc" or div_id == "fandom-toc":
                self._toc_div_depth += 1
            elif self._reflist_div_depth > 0:
                self._reflist_div_depth += 1
            elif "reflist" in cls or cls.strip() == "references":
                self._reflist_div_depth += 1
            elif self._infobox_div_depth > 0:
                self._infobox_div_depth += 1
            elif self._gallery_div_depth > 0:
                self._gallery_div_depth += 1
            elif "wikia-gallery" in cls:
                self._gallery_div_depth += 1
            elif "portable-infobox" in cls:
                self._infobox_div_depth += 1
            return
        if tag == "ol" and "references" in cls:
            self._ref_ol_depth += 1
            return
        if tag == "sup":
            if "reference" in cls or "mw-ref" in cls:
                self._sup_ref_depth += 1
            return  # do not treat <sup> as block boundary
        if tag == "span" and "mw-editsection" in cls:
            self._editsection_depth += 1
            return
        if self._skip():
            return
        if tag == "br":
            self._chunks.append("\n")
        elif tag in ("p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr"):
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "figure" and self._figure_depth > 0:
            self._figure_depth -= 1
            return
        if tag == "figcaption" and self._figcaption_depth > 0:
            self._figcaption_depth -= 1
            return
        if tag == "table" and self._table_depth > 0:
            self._table_depth -= 1
            return
        if tag == "aside" and self._aside_depth > 0:
            self._aside_depth -= 1
            return
        if tag == "div" and self._toc_div_depth > 0:
            self._toc_div_depth -= 1
            return
        if tag == "div" and self._gallery_div_depth > 0:
            self._gallery_div_depth -= 1
            return
        if tag == "div" and self._reflist_div_depth > 0:
            self._reflist_div_depth -= 1
            return
        if tag == "div" and self._infobox_div_depth > 0:
            self._infobox_div_depth -= 1
            return
        if tag == "ol" and self._ref_ol_depth > 0:
            self._ref_ol_depth -= 1
            return
        if tag == "sup" and self._sup_ref_depth > 0:
            self._sup_ref_depth -= 1
            return
        if tag == "span" and self._editsection_depth > 0:
            self._editsection_depth -= 1
            return
        if not self._skip() and tag in ("p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6"):
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip():
            return
        self._chunks.append(data)

    def text(self) -> str:
        raw = "".join(self._chunks)
        raw = html_module.unescape(raw)
        raw = re.sub(r"[ \t\r\f\v]+", " ", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def _strip_repeated_section(
    text: str,
    heading: str,
    terminators: tuple[str, ...],
    *,
    allow_optional_brackets_after_terminator: bool,
) -> str:
    """
    Remove one or more blocks that start with a line ``heading`` (optional ``[]``)
    and run until a line that matches one of ``terminators`` or EOF.
    If allow_optional_brackets_after_terminator is True, terminators may be
    followed by ``[]`` (wiki edit noise on headings).
    """
    alt = "|".join(re.escape(t) for t in terminators)
    tail = rf"(?:{alt})(?:\[\])?" if allow_optional_brackets_after_terminator else rf"(?:{alt})"
    pat = re.compile(
        rf"(?ms)^\s*{re.escape(heading)}(?:\[\])?\s*\n.*?(?=^\s*{tail}\s*$|\Z)"
    )
    prev = None
    while prev != text:
        prev = text
        text = pat.sub("\n", text, count=1)
    return text


def _strip_other_appearances_sections(text: str) -> str:
    """Remove 'Other appearances' blocks until the next common wiki section heading."""
    return _strip_repeated_section(
        text,
        "Other appearances",
        (
            "Quotes",
            "Sprites",
            "Vesperkin",
            "Spinoffs",
            "Achievements",
            "Gallery",
            "Voice actors",
            "Trivia",
            "On hand",
            "In the manga",
            "In the anime",
            "Movies",
            "Main series",
            "References",
            "See also",
            "External links",
            "Artwork",
            "Merchandise",
            "Etymology",
            "Names",
            "Design",
            "Origin",
            "Biography",
            "Crossover",
        ),
        allow_optional_brackets_after_terminator=False,
    )


def _strip_trivia_section(text: str) -> str:
    """Remove Trivia section until the next common heading or EOF (species: before Origin, etc.)."""
    return _strip_repeated_section(
        text,
        "Trivia",
        (
            "Origin",
            "Etymology",
            "Names",
            "Name origin",
            "Design",
            "Biology",
            "Behavior",
            "Habitat",
            "Game data",
            "Base stats",
            "Stats",
            "Learnset",
            "Sprites",
            "Quotes",
            "Gallery",
            "Artwork",
            "References",
            "See also",
            "External links",
            "Merchandise",
            "In other languages",
            "TCG",
            "Movies",
            "Anime",
            "Manga",
            "Biography",
            "Crossover",
            "Description",
            "Appearance",
            "Overview",
            "In the anime",
            "In the manga",
            "In the games",
            "Core series",
            "Spinoffs",
            "Vesperkin",
            "Characters",
            "Profiles",
            "Websites",
            "Achievements",
            "Voice actors",
        ),
        allow_optional_brackets_after_terminator=True,
    )


def _strip_post_biography_tail(text: str) -> str:
    """
    Remove typical tail sections on character pages: party lists (On hand / …),
    Achievements, Voice actors, Gallery, Trivia. Safe when Achievements exists for team strip.
    """
    has_ach = bool(re.search(r"(?m)^\s*Achievements(?:\[\])?\s*$", text))
    if has_ach:
        while True:
            new = re.sub(
                r"(?ms)^\s*(?:On hand|In rotation|Traveling with)(?:\[\])?\s*\n.*?(?=^\s*Achievements(?:\[\])?\s*$)",
                "\n",
                text,
                count=1,
            )
            if new == text:
                break
            text = new
    text = re.sub(
        r"(?ms)^\s*Achievements(?:\[\])?\s*\n.*?(?=^\s*(?:Voice actors|Trivia|Gallery)(?:\[\])?\s*$|\Z)",
        "\n",
        text,
    )
    text = re.sub(
        r"(?ms)^\s*Voice actors(?:\[\])?\s*\n.*?(?=^\s*(?:Trivia|Gallery)(?:\[\])?\s*$|\Z)",
        "\n",
        text,
    )
    text = re.sub(
        r"(?ms)^\s*Gallery(?:\[\])?\s*\n.*\Z",
        "\n",
        text,
    )
    text = _strip_trivia_section(text)
    return text


def post_clean_wiki_text(text: str) -> str:
    """
    Remove Fandom FAQ blocks, wiki nav sections (By series, Other appearances,
    References, Sources, See also), post-biography blocks (party list, Achievements,
    Voice actors, Gallery, Trivia), table-of-contents leftovers, gallery counters
    and glued image filenames, and bracket noise ([], [edit], [1], ^ cite lines).
    """
    # Plain-text TOC if it leaked (numbered outline after "Contents")
    text = re.sub(
        r"(?ms)^\s*Contents\s*\n(?:\s*\n|^\s*\d+(?:\.\d+)*\s+[^\n]+\s*\n)*",
        "\n",
        text,
    )
    # Fandom "Quick Answers" widget (before first Appearance section)
    text = re.sub(
        r"(?ms)^\s*Quick Answers\s*\n.*?(?=^\s*Appearance(?:\[\])?\s*$)",
        "\n",
        text,
    )
    # Biography → Anime: list-only "By series" block
    text = re.sub(
        r"(?ms)^\s*By series(?:\[\])?\s*\n.*?(?=^\s*Other appearances(?:\[\])?\s*$)",
        "\n",
        text,
    )
    # "Other appearances" (anime/games/manga one-liners) → next real section
    text = _strip_other_appearances_sections(text)
    # Party list, badges/tournaments, cast list, image captions (character + species pages)
    text = _strip_post_biography_tail(text)
    # Sources (if present before References / See also)
    text = re.sub(
        r"(?ms)^\s*Sources(?:\[\])?\s*\n.*?(?=^\s*(?:References|See also)(?:\[\])?\s*$|\Z)",
        "\n",
        text,
    )
    # References block
    text = re.sub(
        r"(?ms)^\s*References(?:\[\])?\s*\n.*?(?=^\s*See also(?:\[\])?\s*$|\Z)",
        "\n",
        text,
    )
    # Wiki link-out section at end
    text = re.sub(r"(?ms)^\s*See also(?:\[\])?\s*\n.*\Z", "\n", text)
    # Brackets: empty, edit links, numeric footnotes
    text = re.sub(r"\[\]", "", text)
    text = re.sub(r"\[edit\]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\[\d+\]", "", text)
    # Residual cite lines (episode codes)
    text = re.sub(r"(?m)^\s*\^\s+.+$", "", text)
    # Gallery UI: page counter (e.g. "1/4") on its own line
    text = re.sub(r"(?m)^\s*\d+/\d+\s*$", "", text)
    # Filename glued to caption with no space (e.g. "Foo.pngCaption text")
    text = re.sub(
        r"(?mi)^(\s*).+?\.(?:png|jpe?g|gif|webp|svg)(?=\S)",
        r"\1",
        text,
    )
    text = re.sub(r"(?m)^[ \t]+$", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def html_to_text(html: str) -> str:
    """Strip structure; exclude tables, asides, infoboxes, refs, edit links."""
    html = re.sub(r"(?is)<script[^>]*>.*?</script>", "", html)
    html = re.sub(r"(?is)<style[^>]*>.*?</style>", "", html)
    html = re.sub(r"(?is)<noscript[^>]*>.*?</noscript>", "", html)
    parser = _WikiPlainTextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        text = re.sub(r"<[^>]+>", " ", html)
        text = html_module.unescape(text)
        text = re.sub(r"[ \t\r\f\v]+", " ", text)
        return post_clean_wiki_text(text.strip())
    return post_clean_wiki_text(parser.text())


def load_json_dict(path: Path) -> dict[str, str]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} must be a JSON object")
    return {str(k): str(v) for k, v in data.items()}


def apply_substring_longest_first(text: str, mapping: dict[str, str]) -> str:
    """Case-sensitive replacement (wiki / UI strings match exact spelling)."""
    keys = sorted(mapping.keys(), key=len, reverse=True)
    out = text
    for k in keys:
        out = out.replace(k, mapping[k])
    return out


def apply_case_insensitive_literal(text: str, mapping: dict[str, str]) -> str:
    """Replace literal keys ignoring case (species names in tables, ALL CAPS, etc.)."""
    keys = sorted(mapping.keys(), key=len, reverse=True)
    out = text
    for k in keys:
        v = mapping[k]
        out = re.sub(re.escape(k), v, out, flags=re.IGNORECASE)
    return out


def strip_remaining_poke_prefix(text: str) -> str:
    """Any leftover 'Poké' + Latin suffix -> neutral brand (after explicit maps)."""
    text = re.sub(r"Poké([A-Za-z]+)", r"Aether\1", text)
    text = re.sub(r"Poké-", "Aether-", text)
    text = re.sub(r"\bPoké\b", "Aether", text)
    return text


def strip_loose_pokemon_word(text: str) -> str:
    return re.sub(r"\bpokemon\b", "vesperkin", text, flags=re.IGNORECASE)


def residual_trainer_ash(text: str) -> str:
    """Standalone 'Ash' (not already part of other tokens)."""
    return re.sub(r"\bAsh\b", "Ralen", text)


def strip_urls(text: str) -> str:
    text = re.sub(r"https?://[^\s\]\)]+", "", text)
    return re.sub(r" +", " ", text)


def obfuscate(text: str, terms: dict[str, str], species: dict[str, str]) -> str:
    text = apply_substring_longest_first(text, terms)
    text = apply_case_insensitive_literal(text, species)
    text = strip_remaining_poke_prefix(text)
    text = strip_loose_pokemon_word(text)
    text = residual_trainer_ash(text)
    return text


def slugify(title: str) -> str:
    s = title.lower().replace("é", "e").replace("è", "e")
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_") or "page"


def main() -> None:
    terms = load_json_dict(TERMS_PATH)
    species = load_json_dict(SPECIES_PATH)
    KB_DIR.mkdir(parents=True, exist_ok=True)

    manifest: list[dict] = []
    for i, title in enumerate(WIKI_PAGES):
        if i:
            time.sleep(0.35)
        data = api_parse(title)
        if "error" in data:
            raise RuntimeError(f"API error for {title!r}: {data['error']}")
        html = data["parse"]["text"]["*"]
        raw_text = html_to_text(html)
        obfuscated = strip_urls(obfuscate(raw_text, terms, species))
        heading = strip_urls(obfuscate(data["parse"]["title"], terms, species))

        slug = slugify(title)
        md_path = KB_DIR / f"{slug}.md"
        md_path.write_text(
            f"# {heading}\n\n{obfuscated}\n",
            encoding="utf-8",
        )

        manifest.append(
            {
                "id": slug,
                "source_wiki": "pokemon.fandom.com",
                "source_title": data["parse"]["title"],
                "output_file": str(md_path.relative_to(ROOT)),
                "char_count": len(obfuscated),
            }
        )
        print(f"Wrote {md_path.name} ({len(obfuscated)} chars)")

    jsonl_path = KB_DIR / "manifest.jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as jf:
        for row in manifest:
            jf.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"Done: {len(manifest)} documents, manifest at {jsonl_path}")


if __name__ == "__main__":
    main()
