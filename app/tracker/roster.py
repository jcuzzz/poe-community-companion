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


def parse_pob_code(code: str) -> dict:
    """Parse a Path of Building export code into a small summary dict.

    PoB codes are URL-safe base64 of zlib-compressed XML whose <Build> element
    carries level / className / ascendClassName. Raises ValueError on anything we
    can't read, so the caller can show a friendly message.
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
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise ValueError("Could not read the build data in that code.") from exc

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
        if exc.code in (403, 404):
            raise ValueError(
                "Couldn't read that account. Is your profile public and the account "
                "name (with #discriminator) correct?"
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
            "raw": code.strip()[:8000],
        },
    )
    return snapshot, ""
