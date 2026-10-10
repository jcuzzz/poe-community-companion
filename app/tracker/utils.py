"""Small shared helpers."""

from __future__ import annotations

import io
import re
from typing import TYPE_CHECKING, cast

from django.conf import settings
from django.core.exceptions import ValidationError
from django.http import HttpRequest

if TYPE_CHECKING:
    from .models import User


def current_user(request: HttpRequest) -> User:
    """The signed-in user. Only call from views behind ``login_required``; the stubs
    type ``request.user`` as ``User | AnonymousUser``."""
    return cast("User", request.user)


_PLAYED_TOKEN = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>[dhms])", re.IGNORECASE)
_UNIT_SECONDS = {"d": 86400, "h": 3600, "m": 60, "s": 1}
_CLOCK = re.compile(r"^(\d+):([0-5]?\d)(?::([0-5]?\d))?$")


def parse_played(value: str) -> int:
    """Parse '1d 7h 24m', '18h42m', '3:15' or a bare second count into seconds.

    Raises ValidationError on anything it cannot read confidently.
    """
    if value is None:
        raise ValidationError("Enter a played time.")
    text = str(value).strip().lower()
    if not text:
        raise ValidationError("Enter a played time.")

    if text.isdigit():
        # Bare number is ambiguous; treat as hours only if small, else seconds.
        return int(text) * 3600 if int(text) <= 999 else int(text)

    clock = _CLOCK.match(text)
    if clock:
        hours, minutes, seconds = clock.groups()
        return int(hours) * 3600 + int(minutes) * 60 + int(seconds or 0)

    matches = list(_PLAYED_TOKEN.finditer(text))
    if not matches:
        raise ValidationError("Use a format like '1d 7h 24m' or '18h 42m'.")
    if _PLAYED_TOKEN.sub("", text).strip(" ,"):
        raise ValidationError("Use a format like '1d 7h 24m' or '18h 42m'.")

    total = 0.0
    seen = set()
    for match in matches:
        unit = match.group("unit").lower()
        if unit in seen:
            raise ValidationError(f"Duplicate '{unit}' unit in played time.")
        seen.add(unit)
        total += float(match.group("value")) * _UNIT_SECONDS[unit]
    return int(total)


# Pillow format name -> file extension we are willing to store.
_FORMAT_EXTENSIONS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "GIF": "gif"}


def image_extension(file) -> str:
    """Extension derived from the image's detected format, never the client's name.
    Falls back to a non-servable ``bin`` if the content is not a known image."""
    from PIL import Image

    try:
        file.seek(0)
        with Image.open(file) as img:
            fmt = (img.format or "").upper()
    except Exception:  # noqa: BLE001 - undecodable content gets the inert fallback
        fmt = ""
    finally:
        try:
            file.seek(0)
        except Exception:  # noqa: BLE001
            pass
    return _FORMAT_EXTENSIONS.get(fmt, "bin")


def validate_proof_image(uploaded) -> None:
    """Size, real format and decode-bomb checks. Raises ValidationError."""
    from PIL import Image

    max_bytes = settings.MAX_UPLOAD_BYTES
    if uploaded.size > max_bytes:
        raise ValidationError(
            f"{uploaded.name} is {uploaded.size // 1024 // 1024} MB. "
            f"Limit is {max_bytes // 1024 // 1024} MB."
        )
    try:
        uploaded.seek(0)
        with Image.open(uploaded) as img:
            img.verify()
            fmt = (img.format or "").upper()
    except Exception as exc:  # noqa: BLE001 - any decode failure is a rejection
        raise ValidationError(f"{uploaded.name} is not a readable image.") from exc
    finally:
        uploaded.seek(0)

    if fmt not in settings.ALLOWED_IMAGE_FORMATS:
        raise ValidationError(
            f"{uploaded.name} is {fmt or 'unknown'}. Only JPEG, PNG and WebP are accepted."
        )


def strip_metadata(uploaded):
    """Re-encode an image without EXIF/metadata. Returns a Django File.

    Screenshots can carry location and device data; the group does not need it.
    """
    from django.core.files.base import ContentFile
    from PIL import Image

    uploaded.seek(0)
    with Image.open(uploaded) as img:
        fmt = (img.format or "PNG").upper()
        if fmt == "JPEG":
            clean = Image.new("RGB", img.size)
            clean.paste(img.convert("RGB"))
            save_kwargs = {"format": "JPEG", "quality": 88, "optimize": True}
            ext = "jpg"
        elif fmt == "WEBP":
            clean = Image.new(img.mode if img.mode in {"RGB", "RGBA"} else "RGB", img.size)
            clean.paste(img)
            save_kwargs = {"format": "WEBP", "quality": 88, "method": 4}
            ext = "webp"
        else:
            mode = img.mode if img.mode in {"RGB", "RGBA", "L"} else "RGB"
            clean = Image.new(mode, img.size)
            clean.paste(img.convert(mode))
            save_kwargs = {"format": "PNG", "optimize": True}
            ext = "png"

        buffer = io.BytesIO()
        clean.save(buffer, **save_kwargs)
        clean.close()

    base = (uploaded.name or "proof").rsplit(".", 1)[0][:40] or "proof"
    return ContentFile(buffer.getvalue(), name=f"{base}.{ext}")
