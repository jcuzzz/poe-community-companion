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

Output schema (contract with ``app/strategies/scarabs.py``)::

    {"version": "<label>",
     "scarabs": {"<name>": {"icon": "<https://web.poecdn.com/...>",
                            "group": "<family>"}}}

``group`` is the scarab family: the word immediately before "Scarab", since every
name is ``"<Family> Scarab"`` or ``"<Family> Scarab of <Suffix>"``. The nine
family-less ones ("Scarab of Adversaries", ...) land in the "Scarab" group.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

API = "https://poe.ninja/poe1/api/economy/exchange/current/overview"
LEAGUES_API = "https://poe.ninja/poe1/api/economy/leagues"
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


def build(catalogues: list[list[dict]], version: str) -> dict:
    scarabs: dict[str, dict] = {}
    for catalogue in catalogues:
        for entry in catalogue:
            name = (entry.get("name") or "").strip()
            icon = icon_url(entry.get("image") or "")
            if not name or "Scarab" not in name.split() or not icon:
                continue
            # First league wins; later ones only fill gaps.
            scarabs.setdefault(name, {"icon": icon, "group": family_of(name)})
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

    data = build(catalogues, version)
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

    out = Path(args.out)
    out.write_text(
        json.dumps(data, separators=(",", ":"), ensure_ascii=False), encoding="utf-8"
    )
    groups = {s["group"] for s in data["scarabs"].values()}
    print(
        f"{out}: {out.stat().st_size / 1024:.0f} KB, {count} scarabs, "
        f"{len(groups)} families, version {data['version']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
