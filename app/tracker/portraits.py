"""Map a character's class/ascendancy string to a bundled class-portrait image.

The available set is discovered from the files actually present in
`static/img/classes/` at import time, so it self-adapts to whatever art is bundled
(no hardcoded list that could reference a missing file and break manifest storage).
Bundled art is PoE class iconography; see docs/specs/ux-pass.md.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings

_CLASSES_DIR = Path(settings.BASE_DIR) / "static" / "img" / "classes"


def _slugify_class(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def _discover() -> dict[str, str]:
    """slug -> static-relative path, for every image in static/img/classes/."""
    out: dict[str, str] = {}
    if _CLASSES_DIR.is_dir():
        for f in _CLASSES_DIR.iterdir():
            if f.suffix.lower() in {".png", ".webp", ".jpg", ".jpeg", ".svg"}:
                out[f.stem.lower()] = f"img/classes/{f.name}"
    return out


AVAILABLE = _discover()

# The seven base (core) classes ship as small square avatar headshots, whereas
# ascendancies ship as wide landscape banners. They need different focal-point
# cropping, so callers can ask which kind a resolved portrait is.
_BASE_CLASSES = {
    "marauder", "ranger", "witch", "duelist", "templar", "shadow", "scion",
}


def portrait_path(class_str: str) -> str:
    """Static-relative path to the class portrait, or '' if none is bundled."""
    return AVAILABLE.get(_slugify_class(class_str), "")


def is_base_avatar(class_str: str) -> bool:
    """True when the resolved portrait is a base-class square avatar (not a
    wide ascendancy banner) — used to pick the right CSS crop."""
    slug = _slugify_class(class_str)
    return slug in _BASE_CLASSES and slug in AVAILABLE
