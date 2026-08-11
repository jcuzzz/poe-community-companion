#!/usr/bin/env python3
"""Build the scarab name/icon bundle consumed by ``app/strategies/scarabs.py``.

Run manually once per PoE patch (or whenever GGG adds scarabs)::

    python scripts/build_scarab_data.py                        # Standard
    python scripts/build_scarab_data.py --league Allflame      # current league
    python scripts/build_scarab_data.py --league Allflame,Standard --version "3.29 Allflame"

Source is poe.ninja's economy API. The legacy ``/api/data/itemoverview`` endpoint
is gone (it 404s as of 2026); the current one is::

    GET https://poe.ninja/poe1/api/economy/exchange/current/overview?league=<L>&type=Scarab

which returns ``{core, lines, items}`` where ``items`` is the catalogue
(``{id, name, image, category, detailsId}``) and ``lines`` carries the prices.
We keep only the catalogue: ``image`` is a root-relative ``/gen/image/...`` path
that resolves against ``web.poecdn.com``, i.e. the same hotlinkable item art we
use elsewhere. Prices are deliberately dropped — phase 5 fetches those live from
``lines`` (the ``id`` there matches the item ``id``, i.e. the slugified name).

Note the API only lists scarabs that actually traded in the given league, so a
dead league yields nothing and a quiet one yields a few less than the full set.
Passing several leagues merges their catalogues, which is the cheap way to get
complete coverage.

Descriptions (the in-game tooltip mod lines) come from a second source, the
poewiki cargo API::

    GET https://www.poewiki.net/w/api.php?action=cargoquery&tables=items
        &fields=items.name,items.description
        &where=items.class_id="MapFragment" AND items.name LIKE "%Scarab%"

``items.description`` is the explicit mod text ("Area contains an additional
Abyss"); ``items.explicit_stat_text`` is null for scarabs, which is why we read
``description``. The text arrives HTML-escaped with ``<span class="keyword">``
wrappers and ``<br>`` line breaks — :func:`clean_description` undoes all that.
There is no usable stack/"Limit:" field in the cargo schema (``stack_size``,
``max_stack_size`` and ``limit`` all error), so the bundle carries mod lines
only. The wiki lists a few retired scarabs too; extras are simply ignored.

If the wiki call fails the build still succeeds: descriptions already present in
the existing bundle are preserved and a warning goes to stderr.

Output schema (contract with ``app/strategies/scarabs.py``)::

    {"version": "<label>",
     "scarabs": {"<name>": {"icon": "<https://web.poecdn.com/...>",
                            "group": "<family>",
                            "desc": "<mod lines, \\n-joined>"}}}

``group`` is the scarab family: the word immediately before "Scarab", since every
name is ``"<Family> Scarab"`` or ``"<Family> Scarab of <Suffix>"``. The nine
family-less ones ("Scarab of Adversaries", ...) land in the "Scarab" group.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

API = "https://poe.ninja/poe1/api/economy/exchange/current/overview"
LEAGUES_API = "https://poe.ninja/poe1/api/economy/leagues"
WIKI_API = "https://www.poewiki.net/w/api.php"
CDN = "https://web.poecdn.com"
USER_AGENT = "poe-community-companion/1.0 (self-hosted)"

DEFAULT_LEAGUE = "Standard"
OUT_PATH = Path(__file__).resolve().parent.parent / "app" / "strategies" / "scarab_data.json"


def fetch(url: str) -> object:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - fixed https host
        return json.loads(response.read().decode("utf-8"))


def known_leagues() -> list[str]:
    """League ids poe.ninja currently indexes, for the error message on a typo."""
    try:
        return [str(entry.get("id")) for entry in fetch(LEAGUES_API) or []]
    except (OSError, ValueError):
        return []


def fetch_catalogue(league: str) -> list[dict]:
    url = f"{API}?{urllib.parse.urlencode({'league': league, 'type': 'Scarab'})}"
    payload = fetch(url)
    return list((payload or {}).get("items") or [])


_BREAK = re.compile(r"<br\s*/?>|</?p>", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
_WIKI_LINK = re.compile(r"\[\[(?:[^\]|]*\|)?([^\]|]*)\]\]")


def clean_description(raw: str) -> str:
    """Wiki description -> plain in-game text, newline-joined mod lines."""
    if not raw:
        return ""
    text = html.unescape(str(raw))
    text = html.unescape(text)  # the API double-escapes the span markup
    text = _BREAK.sub("\n", text)
    text = _WIKI_LINK.sub(r"\1", text)
    text = _TAG.sub("", text)
    lines = [" ".join(line.split()) for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


def fetch_descriptions() -> dict[str, str]:
    """``{scarab name: description}`` from the poewiki cargo API."""
    params = {
        "action": "cargoquery",
        "format": "json",
        "tables": "items",
        "fields": "items.name,items.description",
        "where": 'items.class_id="MapFragment" AND items.name LIKE "%Scarab%"',
        "limit": "500",
    }
    payload = fetch(f"{WIKI_API}?{urllib.parse.urlencode(params)}")
    rows = (payload or {}).get("cargoquery")
    if not rows:
        error = (payload or {}).get("error") or {}
        raise ValueError(f"cargoquery returned no rows: {error.get('info') or payload}")
    descriptions = {}
    for row in rows:
        title = row.get("title") or {}
        name = (title.get("name") or "").strip()
        text = clean_description(title.get("description") or "")
        if name and text:
            descriptions[name] = text
    return descriptions


def existing_descriptions(path: Path) -> dict[str, str]:
    """Descriptions in the bundle we are about to overwrite (fallback source)."""
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return {
        name: entry.get("desc", "")
        for name, entry in (data.get("scarabs") or {}).items()
        if entry.get("desc")
    }


def family_of(name: str) -> str:
    """Family = the word before "Scarab" ("Titanic Scarab of Legend" -> "Titanic").

    A handful of scarabs are family-less ("Scarab of Adversaries"); they are
    grouped under the literal "Scarab" so every entry has a non-empty family.
    """
    words = name.split()
    try:
        index = words.index("Scarab")
    except ValueError:
        return ""
    return words[index - 1] if index > 0 else "Scarab"


def icon_url(image: str) -> str:
    if not image:
        return ""
    if image.startswith(("http://", "https://")):
        return image
    return CDN + ("" if image.startswith("/") else "/") + image


def build(
    catalogues: list[list[dict]],
    version: str,
    descriptions: dict[str, str] | None = None,
) -> dict:
    descriptions = descriptions or {}
    scarabs: dict[str, dict] = {}
    for catalogue in catalogues:
        for entry in catalogue:
            name = (entry.get("name") or "").strip()
            icon = icon_url(entry.get("image") or "")
            if not name or "Scarab" not in name.split() or not icon:
                continue
            # First league wins; later ones only fill gaps.
            scarabs.setdefault(
                name,
                {
                    "icon": icon,
                    "group": family_of(name),
                    "desc": descriptions.get(name, ""),
                },
            )
    return {"version": version, "scarabs": dict(sorted(scarabs.items()))}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--league",
        default=DEFAULT_LEAGUE,
        help="poe.ninja league id, or several comma-separated to merge catalogues",
    )
    parser.add_argument("--version", default=None, help="label stored in output")
    parser.add_argument("--out", default=str(OUT_PATH), help="output json path")
    parser.add_argument(
        "--force",
        action="store_true",
        help="write the bundle even when the catalogue looks suspiciously small",
    )
    args = parser.parse_args(argv)

    leagues = [part.strip() for part in args.league.split(",") if part.strip()]
    version = args.version or f"{'+'.join(leagues)} {date.today().isoformat()}"

    catalogues = []
    for league in leagues:
        try:
            catalogues.append(fetch_catalogue(league))
        except (OSError, ValueError) as exc:  # ValueError: HTML/garbage response
            valid = ", ".join(known_leagues()) or "<leagues endpoint unavailable>"
            print(f"{league}: {exc} (known leagues: {valid})", file=sys.stderr)
            return 1

    out = Path(args.out)
    # Merge-preserve: the wiki is a nice-to-have, never a build blocker.
    descriptions = existing_descriptions(out)
    try:
        descriptions.update(fetch_descriptions())
    except (OSError, ValueError) as exc:
        print(
            f"warning: poewiki descriptions unavailable ({exc}); "
            f"keeping {len(descriptions)} existing description(s)",
            file=sys.stderr,
        )

    data = build(catalogues, version, descriptions)
    count = len(data["scarabs"])
    if count < 80 and not args.force:
        # Refuse rather than clobber a good bundle with a near-empty one
        # (a dead league lists only what actually traded).
        print(
            f"refusing to write: only {count} scarabs — 3.29 has ~115; a quiet "
            "league lists fewer, try --league Allflame,Standard (or --force)",
            file=sys.stderr,
        )
        return 1

    out.write_text(
        json.dumps(data, separators=(",", ":"), ensure_ascii=False), encoding="utf-8"
    )
    groups = {s["group"] for s in data["scarabs"].values()}
    missing = sorted(n for n, s in data["scarabs"].items() if not s["desc"])
    if missing:
        print(
            f"warning: {len(missing)} scarab(s) without a description: "
            + ", ".join(missing),
            file=sys.stderr,
        )
    print(
        f"{out}: {out.stat().st_size / 1024:.0f} KB, {count} scarabs, "
        f"{len(groups)} families, {count - len(missing)} described, "
        f"version {data['version']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
