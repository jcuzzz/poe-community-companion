"""Atlas share-link codec: format detection, decoding, encoding, hardening."""

from __future__ import annotations

import base64
import struct

from django.test import SimpleTestCase

from .atlas_codec import GGG_TREE_URL_PREFIX, decode_atlas_url, encode_ggg_url

POEPLANNER_URL = (
    "https://poeplanner.com/atlas-tree/"
    "BQAcAAAKADD6EICL4Z87TdeWjEU61WJvtZm5FAAfiwgAAAAAAAADAwAAAAAAAAAAAA=="
)
GGG_URL = (
    "https://www.pathofexile.com/fullscreen-atlas-skill-tree/"
    "AAAABgAACvowgBDhizuf102MljpFYtW1b7mZAAA="
)
EXPECTED = sorted(
    [64048, 32784, 57739, 15263, 55117, 35990, 14917, 25301, 46447, 47513]
)


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii")


class DecodeVectorTests(SimpleTestCase):
    def test_poeplanner_vector(self):
        self.assertEqual(decode_atlas_url(POEPLANNER_URL), EXPECTED)

    def test_ggg_vector(self):
        self.assertEqual(decode_atlas_url(GGG_URL), EXPECTED)

    def test_both_formats_agree(self):
        self.assertEqual(
            decode_atlas_url(POEPLANNER_URL), decode_atlas_url(GGG_URL)
        )

    def test_bare_payload_autodetects(self):
        for url in (POEPLANNER_URL, GGG_URL):
            with self.subTest(url=url):
                payload = url.rsplit("/", 1)[-1]
                self.assertEqual(decode_atlas_url(payload), EXPECTED)

    def test_whitespace_and_trailing_slash_and_query(self):
        messy = "  " + GGG_URL + "/?foo=bar  \n"
        self.assertEqual(decode_atlas_url(messy), EXPECTED)

    def test_internal_whitespace_from_wrapped_paste(self):
        head, tail = GGG_URL[:40], GGG_URL[40:]
        self.assertEqual(decode_atlas_url(head + "\n " + tail), EXPECTED)

    def test_results_are_sorted_and_deduped(self):
        raw = struct.pack(">IBBB", 6, 0, 0, 4)
        raw += struct.pack(">HHHH", 500, 100, 500, 300)
        raw += b"\x00\x00"
        self.assertEqual(decode_atlas_url(_b64(raw)), [100, 300, 500])

    def test_empty_node_list_is_allowed(self):
        raw = struct.pack(">IBBB", 6, 0, 0, 0) + b"\x00\x00"
        self.assertEqual(decode_atlas_url(_b64(raw)), [])


class GggFormatTests(SimpleTestCase):
    def test_version_4_flat_ids(self):
        raw = struct.pack(">IBB", 4, 3, 0) + struct.pack(">HHH", 11, 22, 33)
        self.assertEqual(decode_atlas_url(_b64(raw)), [11, 22, 33])

    def test_version_4_odd_length_is_rejected(self):
        raw = struct.pack(">IBB", 4, 3, 0) + b"\x00\x0b\x00"
        with self.assertRaises(ValueError):
            decode_atlas_url(_b64(raw))

    def test_cluster_and_mastery_data_is_dropped(self):
        raw = struct.pack(">IBBB", 6, 0, 0, 2) + struct.pack(">HH", 7, 9)
        raw += b"\x01" + struct.pack(">H", 40)  # cluster node -> 65576
        raw += b"\x01" + struct.pack(">HH", 12, 7)  # mastery effect
        self.assertEqual(decode_atlas_url(_b64(raw)), [7, 9])

    def test_unsupported_version_rejected(self):
        raw = struct.pack(">IBBB", 9, 0, 0, 0) + b"\x00\x00"
        with self.assertRaisesMessage(ValueError, "version 9"):
            decode_atlas_url(_b64(raw))

    def test_truncated_node_array(self):
        raw = struct.pack(">IBBB", 6, 0, 0, 5) + struct.pack(">HH", 7, 9)
        with self.assertRaises(ValueError):
            decode_atlas_url(_b64(raw))


class PoePlannerFormatTests(SimpleTestCase):
    @classmethod
    def _payload(cls, **kwargs):
        return _b64(cls._raw(**kwargs))

    @staticmethod
    def _raw(*, version=5, is_poe2=False, ids=(1, 2), notes=b""):
        raw = struct.pack("<HH", version, 28)
        if version >= 5:
            raw += bytes([1 if is_poe2 else 0])
        raw += struct.pack("<H", len(ids))
        raw += struct.pack("<" + "H" * len(ids), *ids)
        if version >= 4:
            raw += struct.pack("<H", len(notes)) + notes
        return raw

    def test_poe2_links_rejected(self):
        with self.assertRaisesMessage(ValueError, "Path of Exile 2"):
            decode_atlas_url(self._payload(is_poe2=True))

    def test_version_4_without_game_flag(self):
        self.assertEqual(decode_atlas_url(self._payload(version=4)), [1, 2])

    def test_old_version_rejected(self):
        with self.assertRaises(ValueError):
            decode_atlas_url(self._payload(version=3))

    def test_trailing_bytes_rejected(self):
        with self.assertRaisesMessage(ValueError, "trailing"):
            decode_atlas_url(_b64(self._raw() + b"\xff\xff\xff"))

    def test_truncated_notes_rejected(self):
        raw = struct.pack("<HH", 5, 28) + b"\x00" + struct.pack("<HH", 1, 42)
        raw += struct.pack("<H", 50)  # claims 50 bytes of notes, provides none
        with self.assertRaises(ValueError):
            decode_atlas_url(_b64(raw))

    def test_host_overrides_sniff(self):
        # All-zero leading bytes would sniff as GGG; the host says otherwise.
        raw = struct.pack("<HH", 5, 0) + b"\x00" + struct.pack("<H", 0)
        raw += struct.pack("<H", 0)
        url = "https://poeplanner.com/atlas-tree/" + _b64(raw)
        self.assertEqual(decode_atlas_url(url), [])


class HardeningTests(SimpleTestCase):
    def test_garbage_raises_value_error(self):
        for bad in ("not base64!!!", "@@@@", "hello world$$"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    decode_atlas_url(bad)

    def test_empty_input_raises(self):
        for bad in ("", "   ", "https://www.pathofexile.com/"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    decode_atlas_url(bad)

    def test_non_string_raises_value_error(self):
        with self.assertRaises(ValueError):
            decode_atlas_url(None)  # type: ignore[arg-type]

    def test_oversize_payload_rejected(self):
        with self.assertRaisesMessage(ValueError, "too long"):
            decode_atlas_url("A" * 5000)

    def test_absurd_node_count_rejected(self):
        raw = struct.pack("<HH", 5, 28) + b"\x00" + struct.pack("<H", 60000)
        with self.assertRaises(ValueError):
            decode_atlas_url(_b64(raw))

    def test_too_short_payload_rejected(self):
        with self.assertRaises(ValueError):
            decode_atlas_url(_b64(b"\x01\x02"))


class EncodeTests(SimpleTestCase):
    def test_payload_layout_is_canonical(self):
        # The known-good GGG vector stores ids in the planner's authoring
        # order; we always emit them ascending, so compare structure.
        payload = encode_ggg_url(EXPECTED)[len(GGG_TREE_URL_PREFIX):]
        raw = base64.urlsafe_b64decode(payload)
        self.assertEqual(raw[:7], struct.pack(">IBBB", 6, 0, 0, 10))
        self.assertEqual(
            list(struct.unpack(">" + "H" * 10, raw[7:27])), EXPECTED
        )
        self.assertEqual(raw[27:], b"\x00\x00")
        self.assertEqual(len(raw), len(base64.urlsafe_b64decode(
            GGG_URL[len(GGG_TREE_URL_PREFIX):])))

    def test_padding_is_retained(self):
        # We keep '=' padding, matching links GGG and poe.ninja hand out.
        self.assertTrue(encode_ggg_url(EXPECTED).endswith("="))

    def test_round_trip(self):
        url = encode_ggg_url(EXPECTED)
        self.assertTrue(url.startswith(GGG_TREE_URL_PREFIX))
        self.assertEqual(decode_atlas_url(url), EXPECTED)

    def test_round_trip_from_poeplanner_link(self):
        ids = decode_atlas_url(POEPLANNER_URL)
        self.assertEqual(decode_atlas_url(encode_ggg_url(ids)), ids)

    def test_sorts_and_dedupes_input(self):
        self.assertEqual(encode_ggg_url([5, 1, 5, 3]), encode_ggg_url([1, 3, 5]))

    def test_empty_round_trip(self):
        self.assertEqual(decode_atlas_url(encode_ggg_url([])), [])

    def test_out_of_range_id_rejected(self):
        for bad in ([70000], [-1]):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    encode_ggg_url(bad)

    def test_non_integer_id_rejected(self):
        with self.assertRaises(ValueError):
            encode_ggg_url(["nope"])

    def test_too_many_nodes_rejected(self):
        with self.assertRaises(ValueError):
            encode_ggg_url(range(300))
