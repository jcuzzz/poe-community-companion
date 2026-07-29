"""Official GGG OAuth 2.0 integration — live character data.

Dormant until an OAuth client is configured (POE_OAUTH_CLIENT_ID). When enabled,
a member links their PoE account once (authorisation-code flow with PKCE), and we
pull their live characters on demand with the ``account:characters`` scope —
gear, socketed gems and the allocated passive tree — mapping the response into
the SAME dict shape ``roster.parse_pob_build`` produces, so the character page
renders identically whether the data came from a PoB paste or from GGG directly.

No live-testing is possible without a client_id, so this is written against
GGG's documented OAuth + API contract and covered by tests with mocked HTTP.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .models import CharacterSnapshot, PoeConnection


# --- Config / enablement --------------------------------------------------

def is_enabled() -> bool:
    """OAuth lights up only once GGG has issued us a client."""
    return bool(
        getattr(settings, "POE_OAUTH_CLIENT_ID", "")
        and getattr(settings, "POE_OAUTH_CLIENT_SECRET", "")
        and getattr(settings, "POE_OAUTH_REDIRECT_URI", "")
    )


def _ua() -> str:
    return getattr(settings, "POE_USER_AGENT", "poe-community-companion/1.0 (self-hosted)")


def _timeout() -> float:
    return float(getattr(settings, "POE_API_TIMEOUT", 8))


# --- PKCE + authorise -----------------------------------------------------

def make_pkce() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for PKCE S256."""
    verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def make_state() -> str:
    return secrets.token_urlsafe(24)


def authorize_url(state: str, code_challenge: str) -> str:
    params = {
        "client_id": settings.POE_OAUTH_CLIENT_ID,
        "response_type": "code",
        "scope": settings.POE_OAUTH_SCOPES,
        "state": state,
        "redirect_uri": settings.POE_OAUTH_REDIRECT_URI,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{settings.POE_OAUTH_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


# --- Token endpoint -------------------------------------------------------

def _post_form(url: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode("ascii")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "User-Agent": _ua(),
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_timeout()) as resp:  # noqa: S310 - fixed host
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ValueError("PoE rejected the authorisation. Try connecting again.") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        raise ValueError("Couldn't reach PoE to complete the connection.") from exc


def exchange_code(code: str, code_verifier: str) -> dict:
    return _post_form(
        settings.POE_OAUTH_TOKEN_URL,
        {
            "client_id": settings.POE_OAUTH_CLIENT_ID,
            "client_secret": settings.POE_OAUTH_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.POE_OAUTH_REDIRECT_URI,
            "code_verifier": code_verifier,
            "scope": settings.POE_OAUTH_SCOPES,
        },
    )


def _refresh(conn: PoeConnection) -> None:
    if not conn.refresh_token:
        raise ValueError("Your PoE connection expired — reconnect your account.")
    token = _post_form(
        settings.POE_OAUTH_TOKEN_URL,
        {
            "client_id": settings.POE_OAUTH_CLIENT_ID,
            "client_secret": settings.POE_OAUTH_CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": conn.refresh_token,
            "scope": settings.POE_OAUTH_SCOPES,
        },
    )
    store_tokens(conn.user, token)


def store_tokens(user, token: dict, account_name: str | None = None) -> PoeConnection:
    """Persist an OAuth token response onto the user's connection."""
    conn, _ = PoeConnection.objects.get_or_create(user=user)
    conn.access_token = token.get("access_token", "") or conn.access_token
    if token.get("refresh_token"):
        conn.refresh_token = token["refresh_token"]
    if token.get("scope"):
        conn.scope = token["scope"][:200]
    expires_in = token.get("expires_in")
    if expires_in:
        try:
            conn.token_expires_at = timezone.now() + timedelta(seconds=int(expires_in))
        except (TypeError, ValueError):
            conn.token_expires_at = None
    if account_name is not None:
        conn.account_name = account_name[:60]
    conn.save()
    return conn


def valid_access_token(conn: PoeConnection) -> str:
    """Return a usable access token, refreshing first if it's expired."""
    if conn.is_expired:
        _refresh(conn)
        conn.refresh_from_db()
    return conn.access_token


# --- Resource API ---------------------------------------------------------

def _api_get(token: str, path: str) -> dict:
    url = f"{settings.POE_OAUTH_API_BASE.rstrip('/')}/{path.lstrip('/')}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": _ua(),
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_timeout()) as resp:  # noqa: S310 - fixed host
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise ValueError("PoE denied access — try reconnecting your account.") from exc
        raise ValueError("PoE character lookup is unavailable right now.") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        raise ValueError("PoE character lookup is unavailable right now.") from exc


def fetch_profile(token: str) -> dict:
    return _api_get(token, "profile")


def fetch_characters(token: str) -> list[dict]:
    data = _api_get(token, "character")
    chars = data.get("characters") if isinstance(data, dict) else None
    return chars or []


def fetch_character(token: str, name: str) -> dict:
    data = _api_get(token, f"character/{urllib.parse.quote(name)}")
    return data.get("character", data) if isinstance(data, dict) else {}


# --- Map GGG character JSON → parse_pob_build shape -----------------------

_FRAME_RARITY = {0: "normal", 1: "magic", 2: "rare", 3: "unique"}

# GGG inventory slot id → our display slot label (matches roster._GEAR_SLOTS).
_SLOT_MAP = {
    "Weapon": "Weapon 1",
    "Weapon2": "Weapon 2",
    "Offhand": "Weapon 2",
    "Helm": "Helmet",
    "BodyArmour": "Body Armour",
    "Gloves": "Gloves",
    "Boots": "Boots",
    "Amulet": "Amulet",
    "Ring": "Ring 1",
    "Ring2": "Ring 2",
    "Belt": "Belt",
}


def _item_to_gear(item: dict) -> dict:
    from .itemart import art_url

    name = item.get("name") or ""
    base = item.get("typeLine") or item.get("baseType") or ""
    rarity = _FRAME_RARITY.get(item.get("frameType"), "rare")
    mods = []
    for key in ("implicitMods", "explicitMods", "craftedMods", "fracturedMods"):
        for line in item.get(key) or []:
            mods.append(line)
    flags = []
    if item.get("corrupted"):
        flags.append("Corrupted")
    display_name = name or base
    return {
        "name": display_name,
        "base": base if name else "",
        "rarity": rarity,
        "mods": mods,
        "flags": flags,
        "icon": art_url(name, base),
    }


def _gems_from_item(item: dict) -> list[dict]:
    from .itemart import art_url

    gems = []
    for sub in item.get("socketedItems") or []:
        # Skill gems have a 'support' boolean in their properties; GGG marks
        # support gems with "support": true on the socketed item.
        nm = sub.get("typeLine") or sub.get("baseType") or ""
        if not nm:
            continue
        is_support = bool(sub.get("support")) or "Support" in nm
        level = quality = ""
        for prop in sub.get("properties") or []:
            pname = prop.get("name")
            vals = prop.get("values") or []
            if pname == "Level" and vals:
                level = str(vals[0][0])
            elif pname == "Quality" and vals:
                quality = str(vals[0][0]).strip("+%")
        gems.append({
            "name": nm.replace(" Support", ""),
            "level": level,
            "quality": quality or "0",
            "support": is_support,
            "enabled": True,
            "icon": art_url(nm),
        })
    return gems


def build_from_ggg_character(char: dict) -> dict:
    """Map a GGG /character response into the dict roster.parse_pob_build returns."""
    class_name = char.get("class") or ""
    level = char.get("level")
    equipment = char.get("equipment") or char.get("items") or []

    gear = []
    skill_groups = []
    for item in equipment:
        slot_id = item.get("inventoryId") or ""
        label = _SLOT_MAP.get(slot_id)
        if label:
            gear.append({"slot": label, **_item_to_gear(item)})
        gems = _gems_from_item(item)
        if gems:
            actives = [g for g in gems if not g["support"]]
            skill_groups.append({
                "label": (actives[0]["name"] if actives else gems[0]["name"]),
                "gems": gems,
                "is_main": False,
            })

    # Order gear by our canonical slot order for a stable layout.
    from .roster import _GEAR_SLOTS

    order = {s: i for i, s in enumerate(_GEAR_SLOTS)}
    gear.sort(key=lambda g: order.get(g["slot"], 99))

    passives = char.get("passives") or {}
    hashes = passives.get("hashes") or []
    node_ids = [str(h) for h in hashes]
    tree = None
    if node_ids:
        tree = {"points": len(node_ids), "node_ids": node_ids, "url": "", "version": ""}

    return {
        "class_name": class_name,
        "ascendancy": "",  # GGG returns the ascendancy as `class` once ascended
        "level": level,
        "main_skill": skill_groups[0]["label"] if skill_groups else "",
        "stat_groups": [],  # GGG's API doesn't compute DPS/EHP; PoB paste still does
        "gear": gear,
        "flasks": [],
        "jewels": 0,
        "tree": tree,
        "skill_groups": skill_groups,
    }


# --- Sync orchestration ---------------------------------------------------

def _pick_character(chars: list[dict], preferred: str, league) -> dict | None:
    if not chars:
        return None
    if preferred:
        for c in chars:
            if (c.get("name") or "").lower() == preferred.lower():
                return c
    league_text = (getattr(league, "ggg_id", "") or (league.name if league else "")) if league else ""
    if league_text:
        in_league = [c for c in chars if (c.get("league") or "") == league_text]
        if in_league:
            return max(in_league, key=lambda c: c.get("level", 0))
    return max(chars, key=lambda c: c.get("level", 0))


def sync_snapshot(user, league) -> tuple[CharacterSnapshot | None, str]:
    """Pull the member's live character via OAuth and store a snapshot."""
    conn = getattr(user, "poe_connection", None)
    if conn is None or not conn.refresh_token:
        return None, "Connect your PoE account first."
    if league is None:
        return None, "No active league."
    try:
        token = valid_access_token(conn)
        chars = fetch_characters(token)
    except ValueError as exc:
        return CharacterSnapshot.objects.filter(user=user, league=league).first(), str(exc)
    preferred = getattr(getattr(user, "member_profile", None), "main_character_name", "") or ""
    chosen = _pick_character(chars, preferred, league)
    if chosen is None:
        return None, "No characters found on your PoE account."
    try:
        full = fetch_character(token, chosen.get("name", ""))
    except ValueError as exc:
        return None, str(exc)
    snapshot, _ = CharacterSnapshot.objects.update_or_create(
        user=user,
        league=league,
        defaults={
            "character_name": full.get("name") or chosen.get("name", ""),
            "class_name": full.get("class") or chosen.get("class", ""),
            "ascendancy": "",
            "level": full.get("level") or chosen.get("level"),
            "league_text": chosen.get("league", "") or (league.name if league else ""),
            "source": CharacterSnapshot.Source.OAUTH,
            "raw": json.dumps(full)[:200000],
            "pob_url": "",
        },
    )
    return snapshot, ""
