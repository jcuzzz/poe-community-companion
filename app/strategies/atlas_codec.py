"""Atlas passive tree share-link codecs (GGG + poeplanner).

Pure stdlib. All malformed input raises ValueError with a human-readable
message -- callers paste these links from untrusted sources.

Formats implemented from empirical verification against poeplanner's own JS
encoder and Path of Building's PassiveSpec.lua:

GGG (big-endian, base64url):
    u32 version | u8 classId | u8 ascendancy
    ver>=5: u8 nodeCount + nodeCount*u16 ids
            u8 clusterCount + clusterCount*u16 (ids offset by 65536)
    ver>=6: u16 masteryCount entries (u16 effectId + u16 nodeId)
    ver<5:  flat u16 ids to end of payload

poeplanner (little-endian, urlsafe base64):
    u16 serializationVersion | u16 treeVersion
    ver>=5: u8 isPoE2 (rejected when true)
    u16 nodeCount + nodeCount*u16 ids
    ver>=4: u16 notesLength + gzipped UTF-8 notes
"""

from __future__ import annotations

import base64
import struct
from typing import Iterable

__all__ = ["decode_atlas_url", "encode_ggg_url", "GGG_TREE_URL_PREFIX"]

GGG_TREE_URL_PREFIX = "https://www.pathofexile.com/fullscreen-atlas-skill-tree/"

MAX_PAYLOAD_BYTES = 4096
MAX_NODE_COUNT = 1024
CLUSTER_ID_OFFSET = 65536

GGG_SUPPORTED_VERSIONS = (4, 5, 6)
GGG_EMIT_VERSION = 6
POEPLANNER_MIN_VERSION = 4


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _extract_payload(url_or_code: str) -> tuple[str, str | None]:
    """Return (payload, forced_format) where forced_format is 'ggg',
    'poeplanner' or None (sniff)."""
    if not isinstance(url_or_code, str):
        raise ValueError("Atlas tree link must be a string.")

    text = "".join(url_or_code.split())
    if not text:
        raise ValueError("Atlas tree link is empty.")

    forced: str | None = None
    lowered = text.lower()
    if "pathofexile.com" in lowered:
        forced = "ggg"
    elif "poeplanner.com" in lowered:
        forced = "poeplanner"

    # drop query string / fragment
    for sep in ("?", "#"):
        if sep in text:
            text = text.split(sep, 1)[0]
    text = text.rstrip("/")
    if "/" in text:
        text = text.rsplit("/", 1)[-1]

    if not text:
        raise ValueError("Atlas tree link has no payload segment.")
    return text, forced


def _b64decode(payload: str) -> bytes:
    if len(payload) > MAX_PAYLOAD_BYTES:
        raise ValueError("Atlas tree link is too long to be a valid tree.")
    normalized = payload.replace("+", "-").replace("/", "_").rstrip("=")
    padded = normalized + "=" * (-len(normalized) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded)
    except Exception as exc:  # binascii.Error and friends
        raise ValueError("Atlas tree link is not valid base64.") from exc
    if not raw:
        raise ValueError("Atlas tree link decoded to an empty payload.")
    if len(raw) > MAX_PAYLOAD_BYTES:
        raise ValueError("Atlas tree link is too long to be a valid tree.")
    return raw


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    @property
    def remaining(self) -> int:
        return len(self.data) - self.pos

    def take(self, n: int, what: str) -> bytes:
        if n < 0 or self.remaining < n:
            raise ValueError(f"Atlas tree link is truncated (reading {what}).")
        chunk = self.data[self.pos:self.pos + n]
        self.pos += n
        return chunk

    def u8(self, what: str) -> int:
        return self.take(1, what)[0]

    def u16(self, what: str, little: bool = False) -> int:
        fmt = "<H" if little else ">H"
        return struct.unpack(fmt, self.take(2, what))[0]

    def u32be(self, what: str) -> int:
        return struct.unpack(">I", self.take(4, what))[0]

    def u16_array(self, count: int, what: str, little: bool = False) -> list[int]:
        fmt = ("<" if little else ">") + "H" * count
        return list(struct.unpack(fmt, self.take(2 * count, what)))


def _check_count(count: int, what: str) -> int:
    if count > MAX_NODE_COUNT:
        raise ValueError(
            f"Atlas tree link claims {count} {what}, which exceeds the "
            f"maximum of {MAX_NODE_COUNT}."
        )
    return count


# --------------------------------------------------------------------------
# decoders
# --------------------------------------------------------------------------

def _decode_ggg(raw: bytes) -> list[int]:
    r = _Reader(raw)
    version = r.u32be("version")
    if version not in GGG_SUPPORTED_VERSIONS:
        raise ValueError(
            f"Unsupported Path of Exile tree version {version}; "
            f"expected one of {', '.join(map(str, GGG_SUPPORTED_VERSIONS))}."
        )
    r.u8("class id")
    if version >= 4:
        r.u8("ascendancy id")

    if version < 5:
        if r.remaining % 2:
            raise ValueError("Atlas tree link is truncated (reading node ids).")
        count = _check_count(r.remaining // 2, "nodes")
        return r.u16_array(count, "node ids")

    count = _check_count(r.u8("node count"), "nodes")
    nodes = r.u16_array(count, "node ids")

    if r.remaining:
        cluster_count = _check_count(r.u8("cluster count"), "cluster nodes")
        # Cluster jewel nodes live above the u16 range; not meaningful for the
        # atlas tree, so read them for bounds-safety and drop them.
        r.u16_array(cluster_count, "cluster node ids")

    if version >= 6 and r.remaining:
        mastery_count = _check_count(r.u8("mastery count"), "masteries")
        r.take(4 * mastery_count, "mastery effects")

    return nodes


def _decode_poeplanner(raw: bytes) -> list[int]:
    r = _Reader(raw)
    version = r.u16("serialization version", little=True)
    if version < POEPLANNER_MIN_VERSION:
        raise ValueError(
            f"Unsupported poeplanner link version {version}; "
            f"expected {POEPLANNER_MIN_VERSION} or newer."
        )
    r.u16("tree version", little=True)

    if version >= 5:
        if r.u8("game flag"):
            raise ValueError(
                "This is a Path of Exile 2 poeplanner link; only Path of "
                "Exile 1 atlas trees are supported."
            )

    count = _check_count(r.u16("node count", little=True), "nodes")
    nodes = r.u16_array(count, "node ids", little=True)

    if version >= 4:
        notes_length = r.u16("notes length", little=True)
        r.take(notes_length, "notes")

    if r.remaining:
        raise ValueError(
            f"Atlas tree link has {r.remaining} unexpected trailing byte(s)."
        )
    return nodes


def decode_atlas_url(url_or_code: str) -> list[int]:
    """Decode a GGG or poeplanner atlas tree link (or bare payload).

    Returns sorted, de-duplicated node ids. Raises ValueError on any
    malformed input.
    """
    payload, forced = _extract_payload(url_or_code)
    raw = _b64decode(payload)

    if forced == "ggg":
        nodes = _decode_ggg(raw)
    elif forced == "poeplanner":
        nodes = _decode_poeplanner(raw)
    else:
        # poeplanner's own sniff: a GGG payload starts with a big-endian
        # version u32, so its first three bytes are all zero.
        if len(raw) < 3:
            raise ValueError("Atlas tree link is too short to be a valid tree.")
        if raw[0] + raw[1] + raw[2] == 0:
            nodes = _decode_ggg(raw)
        else:
            nodes = _decode_poeplanner(raw)

    return sorted({n for n in nodes if n < CLUSTER_ID_OFFSET})


# --------------------------------------------------------------------------
# encoder
# --------------------------------------------------------------------------

def encode_ggg_url(node_ids: Iterable[int]) -> str:
    """Build a canonical GGG atlas share link from node ids."""
    try:
        ids = sorted({int(n) for n in node_ids})
    except (TypeError, ValueError) as exc:
        raise ValueError("Atlas node ids must be integers.") from exc

    for node_id in ids:
        if not 0 <= node_id <= 0xFFFF:
            raise ValueError(f"Atlas node id {node_id} is out of range.")
    _check_count(len(ids), "nodes")
    if len(ids) > 255:
        raise ValueError("Atlas tree has too many nodes to encode (max 255).")

    body = struct.pack(">IBBB", GGG_EMIT_VERSION, 0, 0, len(ids))
    body += struct.pack(">" + "H" * len(ids), *ids)
    body += b"\x00"  # cluster count
    body += b"\x00"  # mastery count

    # Padding kept: GGG's own links (and poe.ninja's) carry '=' padding.
    payload = base64.urlsafe_b64encode(body).decode("ascii")
    return GGG_TREE_URL_PREFIX + payload
