"""Character lookup service for the roster / character showcase.

Two paths, both best-effort and fail-safe — a lookup failure must never 500 or
corrupt the roster (see docs/specs/roster.md):

- **Auto lookup (PoE 1 only):** read-only calls to GGG's unofficial character-window
  API. Requires the member's profile to be public. PoE 2 has NO anonymous public
  lookup, so auto is gated to PoE 1 (docs/research/character-lookup-poe2.md).
- **PoB-code paste (both games):** decode + parse a Path of Building export code
  locally. Zero API fragility; the reliable floor and the PoE 2 default.

Nothing here raises to the view layer: callers get a `(snapshot, error)` result.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zlib

from django.conf import settings
from django.utils import timezone

from .models import CharacterSnapshot, League

logger = logging.getLogger(__name__)


# --- PoB export code parsing ---------------------------------------------


def _pob_root(code: str) -> "ET.Element":
    """Decode a PoB export code (or pobb.in URL) into its parsed XML root.

    Raises ValueError with a friendly message on anything we can't read.
    """
    if not code or not code.strip():
        raise ValueError("Paste a Path of Building export code.")
    raw = code.strip()
    # Tolerate a full pobb.in / pastebin URL by taking the last path segment.
    if "/" in raw:
        raw = raw.rstrip("/").rsplit("/", 1)[-1]
    # Normalise to standard base64 with padding.
    raw = raw.replace("-", "+").replace("_", "/")
    raw += "=" * (-len(raw) % 4)
    try:
        compressed = base64.b64decode(raw)
        xml_bytes = zlib.decompress(compressed)
    except Exception as exc:  # noqa: BLE001 - any decode failure is a bad code
        raise ValueError("That doesn't look like a valid Path of Building code.") from exc
    try:
        return ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise ValueError("Could not read the build data in that code.") from exc


def parse_pob_code(code: str) -> dict:
    """Parse a Path of Building export code into a small summary dict.

    PoB codes are URL-safe base64 of zlib-compressed XML whose <Build> element
    carries level / className / ascendClassName. Raises ValueError on anything we
    can't read, so the caller can show a friendly message.
    """
    root = _pob_root(code)
    build = root.find("Build")
    if build is None:
        raise ValueError("That code has no build data.")

    level = build.get("level") or ""
    class_name = (build.get("className") or "").strip()
    ascend = (build.get("ascendClassName") or "").strip()
    # PoB uses "None" for an un-ascended character.
    if ascend.lower() == "none":
        ascend = ""

    main_skill = ""
    # mainSocketGroup is 1-indexed into the <Skills>/<Skill> groups; best-effort.
    try:
        groups = root.findall("./Skills/Skill") or root.findall("./Skills/SkillSet/Skill")
        idx = int(build.get("mainSocketGroup") or 0) - 1
        if 0 <= idx < len(groups):
            gems = [g.get("nameSpec") for g in groups[idx].findall("Gem") if g.get("nameSpec")]
            main_skill = next((g for g in gems if g), "")
    except Exception:  # noqa: BLE001 - main skill is optional flavour
        main_skill = ""

    return {
        "class_name": class_name,
        "ascendancy": ascend,
        "level": int(level) if str(level).isdigit() else None,
        "main_skill": main_skill,
    }


# --- Rich PoB parse for the character-detail page ------------------------

# Curated stat groups: (PoB PlayerStat key, label, format). We only render what
# the code actually carries, so missing stats simply drop out. PoB computes and
# embeds these, so we show real numbers without our own calc engine.
_STAT_FMT_INT = "int"
_STAT_FMT_PCT = "pct"
_STAT_FMT_DPS = "dps"
_STAT_FMT_X = "mult"

_STAT_GROUPS = [
    ("Offence", [
        ("FullDPS", "Full DPS", _STAT_FMT_DPS),
        ("CombinedDPS", "Combined DPS", _STAT_FMT_DPS),
        ("TotalDPS", "Skill DPS", _STAT_FMT_DPS),
        ("AverageDamage", "Average hit", _STAT_FMT_DPS),
        ("Speed", "Attacks/casts", _STAT_FMT_X),
        ("CritChance", "Crit chance", _STAT_FMT_PCT),
        ("CritMultiplier", "Crit multi", _STAT_FMT_X),
    ]),
    ("Defence", [
        ("Life", "Life", _STAT_FMT_INT),
        ("EnergyShield", "Energy shield", _STAT_FMT_INT),
        ("Mana", "Mana", _STAT_FMT_INT),
        ("Ward", "Ward", _STAT_FMT_INT),
        ("TotalEHP", "Effective HP", _STAT_FMT_DPS),
        ("Armour", "Armour", _STAT_FMT_INT),
        ("Evasion", "Evasion", _STAT_FMT_INT),
        ("BlockChance", "Block", _STAT_FMT_PCT),
        ("SpellBlockChance", "Spell block", _STAT_FMT_PCT),
        ("SpellSuppressionChance", "Suppression", _STAT_FMT_PCT),
    ]),
    ("Resistances", [
        ("FireResist", "Fire", _STAT_FMT_PCT),
        ("ColdResist", "Cold", _STAT_FMT_PCT),
        ("LightningResist", "Lightning", _STAT_FMT_PCT),
        ("ChaosResist", "Chaos", _STAT_FMT_PCT),
    ]),
    ("Attributes", [
        ("Str", "Strength", _STAT_FMT_INT),
        ("Dex", "Dexterity", _STAT_FMT_INT),
        ("Int", "Intelligence", _STAT_FMT_INT),
    ]),
]

# Standard gear slots in display order (PoB <Slot name="..."> values).
_GEAR_SLOTS = [
    "Weapon 1", "Weapon 2", "Helmet", "Body Armour", "Gloves",
    "Boots", "Amulet", "Ring 1", "Ring 2", "Belt",
]


def _fmt_stat(value: float, fmt: str) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if fmt == _STAT_FMT_PCT:
        return f"{v:.0f}%"
    if fmt == _STAT_FMT_X:
        return f"{v:.2f}"
    if fmt == _STAT_FMT_DPS:
        if v >= 1_000_000:
            return f"{v / 1_000_000:.2f}M"
        if v >= 10_000:
            return f"{v / 1000:.1f}k"
        return f"{v:,.0f}"
    return f"{v:,.0f}"


def _parse_item_text(text: str) -> dict:
    """Pull a display name + rarity from a PoB <Item> blob."""
    lines = [ln.strip() for ln in (text or "").strip().splitlines() if ln.strip()]
    rarity = "NORMAL"
    name = ""
    base = ""
    body = []
    for ln in lines:
        if ln.lower().startswith("rarity:"):
            rarity = ln.split(":", 1)[1].strip().upper()
            continue
        body.append(ln)
    if body:
        name = body[0]
        # Rare/unique items carry a distinct name then base; magic/normal don't.
        if rarity in {"RARE", "UNIQUE"} and len(body) > 1:
            base = body[1]
    return {"name": name, "base": base, "rarity": rarity.capitalize()}


def parse_pob_build(code: str) -> dict:
    """Full parse for the character-detail page: header, stats, gear, skills, tree.

    Best-effort and defensive — any section that can't be read is simply omitted;
    only a fundamentally invalid code raises ValueError.
    """
    root = _pob_root(code)
    summary = {"class_name": "", "ascendancy": "", "level": None, "main_skill": ""}
    build = root.find("Build")
    if build is not None:
        try:
            summary = parse_pob_code(code)
        except ValueError:
            pass

    # --- Stats (from <PlayerStat>) ---
    raw_stats = {}
    if build is not None:
        for ps in build.findall("PlayerStat"):
            key = ps.get("stat")
            val = ps.get("value")
            if key and val is not None:
                raw_stats[key] = val
    stat_groups = []
    for title, specs in _STAT_GROUPS:
        rows = []
        for key, label, fmt in specs:
            if key in raw_stats:
                rows.append({"label": label, "value": _fmt_stat(raw_stats[key], fmt)})
        if rows:
            stat_groups.append({"title": title, "rows": rows})

    # --- Gear (active item set → slots → items) ---
    items_el = root.find("Items")
    gear = []
    jewels = 0
    flasks = []
    if items_el is not None:
        by_id = {}
        for item in items_el.findall("Item"):
            iid = item.get("id")
            if iid:
                by_id[iid] = _parse_item_text(item.text or "")
        active = items_el.get("activeItemSet")
        itemset = None
        for s in items_el.findall("ItemSet"):
            if active and s.get("id") == active:
                itemset = s
                break
        if itemset is None:
            itemset = items_el.find("ItemSet") or items_el
        slot_map = {}
        for slot in itemset.findall("Slot"):
            sname = slot.get("name") or ""
            iid = slot.get("itemId")
            if iid and iid != "0" and iid in by_id:
                slot_map[sname] = by_id[iid]
                if "Jewel" in sname or "Socket" in sname:
                    jewels += 1
                elif sname.startswith("Flask"):
                    flasks.append(by_id[iid])
        from .itemart import art_url
        for sname in _GEAR_SLOTS:
            if sname in slot_map:
                it = slot_map[sname]
                # Unique art wins (match by unique name), else base-type art.
                it["icon"] = art_url(it.get("name", ""), it.get("base", ""))
                gear.append({"slot": sname, **it})

    # --- Skills (gem groups) ---
    main_group = 0
    if build is not None:
        try:
            main_group = int(build.get("mainSocketGroup") or 0)
        except (TypeError, ValueError):
            main_group = 0
    groups = root.findall("./Skills/SkillSet/Skill") or root.findall("./Skills/Skill")
    skill_groups = []
    for i, g in enumerate(groups, start=1):
        gems = []
        from .itemart import art_url as _art_url
        for gem in g.findall("Gem"):
            nm = gem.get("nameSpec") or ""
            if not nm:
                continue
            gems.append({
                "name": nm,
                "level": gem.get("level") or "",
                "quality": gem.get("quality") or "0",
                "support": (gem.get("skillId") or "").startswith("Support")
                or "Support" in (gem.get("gemId") or ""),
                "enabled": (gem.get("enabled") or "true") != "false",
                "icon": _art_url(nm),
            })
        if not gems:
            continue
        actives = [x for x in gems if not x["support"]]
        label = actives[0]["name"] if actives else gems[0]["name"]
        skill_groups.append({
            "label": label,
            "gems": gems,
            "is_main": i == main_group,
        })
    skill_groups.sort(key=lambda x: (not x["is_main"],))

    # --- Passive tree ---
    tree = None
    spec = root.find("./Tree/Spec") or root.find("./Tree/ActiveSpec")
    if spec is not None:
        nodes = (spec.get("nodes") or "").strip()
        node_count = len([n for n in nodes.split(",") if n]) if nodes else 0
        url = ""
        url_el = spec.find("URL")
        if url_el is not None and url_el.text:
            url = url_el.text.strip()
        elif spec.text and "passive-skill-tree" in (spec.text or ""):
            url = spec.text.strip()
        tree = {
            "points": node_count,
            "url": url,
            "version": spec.get("treeVersion") or "",
        }

    return {
        **summary,
        "stat_groups": stat_groups,
        "gear": gear,
        "flasks": flasks,
        "jewels": jewels,
        "skill_groups": skill_groups,
        "tree": tree,
    }


# --- GGG character-window API (PoE 1) ------------------------------------


def _api_base() -> str:
    return getattr(settings, "POE_API_BASE", "https://www.pathofexile.com").rstrip("/")


def _http_get_json(url: str) -> list | dict:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": getattr(
                settings, "POE_USER_AGENT", "poe-community-companion/1.0 (self-hosted)"
            ),
            "Accept": "application/json",
        },
    )
    timeout = float(getattr(settings, "POE_API_TIMEOUT", 8))
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed host
        return json.loads(resp.read().decode("utf-8"))


def fetch_poe1_characters(account_name: str) -> list[dict]:
    """Return the public character list for an account, or raise ValueError.

    Uses the unofficial get-characters endpoint. Requires a public profile.
    """
    if not account_name:
        raise ValueError("No account name set.")
    url = f"{_api_base()}/character-window/get-characters?" + urllib.parse.urlencode(
        {"accountName": account_name}
    )
    try:
        data = _http_get_json(url)
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            # GGG's Cloudflare 403s non-browser (server-side) clients regardless of
            # headers/IP — this is not a profile-privacy problem. See
            # docs/research/character-lookup-poe2.md.
            raise ValueError(
                "PoE blocks automated character lookups from servers, so auto-lookup "
                "can't fetch your character. Paste a Path of Building code instead."
            ) from exc
        if exc.code == 404:
            raise ValueError(
                "That account/character wasn't found. Check the account name "
                "(include the #discriminator)."
            ) from exc
        raise ValueError("PoE lookup is unavailable right now. Try again later.") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        raise ValueError("PoE lookup is unavailable right now. Try again later.") from exc
    if not isinstance(data, list):
        raise ValueError("Unexpected response from PoE.")
    return data


def _pick_character(characters: list[dict], preferred_name: str, league: League | None) -> dict | None:
    """Choose which character to feature: the named one, else the highest level in
    the league, else the highest level overall."""
    if not characters:
        return None
    if preferred_name:
        for c in characters:
            if (c.get("name") or "").lower() == preferred_name.lower():
                return c
    league_text = league.ggg_id or (league.name if league else "")
    if league_text:
        in_league = [c for c in characters if (c.get("league") or "") == league_text]
        if in_league:
            return max(in_league, key=lambda c: c.get("level", 0))
    return max(characters, key=lambda c: c.get("level", 0))


# --- Snapshot orchestration ----------------------------------------------


def _throttle_ok(user, league) -> bool:
    """Rate-limit refreshes to the configured TTL so we never hammer GGG."""
    ttl = int(getattr(settings, "POE_SNAPSHOT_TTL_SECONDS", 600))
    snap = CharacterSnapshot.objects.filter(user=user, league=league).first()
    if snap is None:
        return True
    age = (timezone.now() - snap.fetched_at).total_seconds()
    return age >= ttl


def refresh_auto_snapshot(user, league: League, *, force: bool = False) -> tuple[CharacterSnapshot | None, str]:
    """Refresh a member's snapshot via auto lookup. Returns (snapshot, error_msg)."""
    profile = getattr(user, "member_profile", None)
    if profile is None or not profile.account_name:
        return None, "Set your PoE account name in account settings first."
    if league is None:
        return None, "No active league."
    if not league.supports_auto_lookup:
        return None, "Auto lookup isn't available for PoE 2 — paste a Path of Building code instead."
    if not profile.profile_public:
        return None, "Mark your profile public in account settings (and unhide your characters on pathofexile.com)."
    if not force and not _throttle_ok(user, league):
        existing = CharacterSnapshot.objects.filter(user=user, league=league).first()
        return existing, "Snapshot is fresh — try again in a few minutes."

    try:
        characters = fetch_poe1_characters(profile.account_name)
    except ValueError as exc:
        return CharacterSnapshot.objects.filter(user=user, league=league).first(), str(exc)

    chosen = _pick_character(characters, profile.main_character_name, league)
    if chosen is None:
        return None, "No characters found on that account."

    snapshot, _ = CharacterSnapshot.objects.update_or_create(
        user=user,
        league=league,
        defaults={
            "character_name": chosen.get("name", ""),
            # get-characters returns "class" as the ascendancy name once ascended
            # (e.g. "Necromancer"); store it as the class we display.
            "class_name": chosen.get("class", ""),
            "ascendancy": "",
            "level": chosen.get("level"),
            "league_text": chosen.get("league", ""),
            "source": CharacterSnapshot.Source.API,
            "raw": json.dumps(chosen)[:5000],
        },
    )
    return snapshot, ""


def save_pob_snapshot(user, league: League, code: str) -> tuple[CharacterSnapshot | None, str]:
    """Parse a PoB code and store it as this member's snapshot. Returns (snapshot, error)."""
    try:
        parsed = parse_pob_code(code)
    except ValueError as exc:
        return None, str(exc)
    snapshot, _ = CharacterSnapshot.objects.update_or_create(
        user=user,
        league=league,
        defaults={
            "character_name": parsed.get("main_skill", "") or "PoB build",
            "class_name": parsed.get("class_name", ""),
            "ascendancy": parsed.get("ascendancy", ""),
            "level": parsed.get("level"),
            "league_text": league.name if league else "",
            "source": CharacterSnapshot.Source.POB,
            # Store the full code (TextField, unlimited) so the character-detail
            # page can re-parse items/skills/stats. Cap generously to bound abuse.
            "raw": code.strip()[:200000],
        },
    )
    return snapshot, ""
