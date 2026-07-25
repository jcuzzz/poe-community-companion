"""Played-time parsing and image validation."""

import io

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings
from PIL import Image

from tracker.models import format_played
from tracker.utils import parse_played, strip_metadata, validate_proof_image


def make_image(fmt="PNG", size=(40, 30), color=(200, 40, 40)):
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format=fmt)
    buffer.seek(0)
    return buffer


class ParsePlayedTests(SimpleTestCase):
    def test_full_format(self):
        self.assertEqual(parse_played("1d 7h 24m"), 86400 + 7 * 3600 + 24 * 60)

    def test_no_spaces(self):
        self.assertEqual(parse_played("18h42m"), 18 * 3600 + 42 * 60)

    def test_case_and_seconds(self):
        self.assertEqual(parse_played("2H 5M 30S"), 2 * 3600 + 5 * 60 + 30)

    def test_clock_format(self):
        self.assertEqual(parse_played("3:15"), 3 * 3600 + 15 * 60)
        self.assertEqual(parse_played("3:15:09"), 3 * 3600 + 15 * 60 + 9)

    def test_bare_small_number_is_hours(self):
        self.assertEqual(parse_played("18"), 18 * 3600)

    def test_bare_large_number_is_seconds(self):
        self.assertEqual(parse_played("100000"), 100000)

    def test_rejects_junk(self):
        for bad in ["", "   ", "soon", "1d 7x", "1h 2h", "yesterday 4h"]:
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                parse_played(bad)

    def test_roundtrip_with_format_played(self):
        for text in ["1d 7h 24m", "18h 42m", "5m"]:
            with self.subTest(text=text):
                self.assertEqual(format_played(parse_played(text)), text)


class FormatPlayedTests(SimpleTestCase):
    def test_minutes_only(self):
        self.assertEqual(format_played(59 * 60), "59m")

    def test_hours(self):
        self.assertEqual(format_played(18 * 3600 + 42 * 60), "18h 42m")

    def test_days(self):
        self.assertEqual(format_played(86400 + 7 * 3600 + 24 * 60), "1d 7h 24m")

    def test_zero(self):
        self.assertEqual(format_played(0), "0m")

    def test_sorts_by_seconds(self):
        values = [parse_played("1d 2h"), parse_played("23h"), parse_played("2d")]
        self.assertEqual(sorted(values), [parse_played("23h"), parse_played("1d 2h"), parse_played("2d")])


class ImageValidationTests(SimpleTestCase):
    def test_accepts_png(self):
        upload = SimpleUploadedFile("proof.png", make_image("PNG").read(), "image/png")
        validate_proof_image(upload)

    def test_accepts_jpeg_and_webp(self):
        for fmt, ext in [("JPEG", "jpg"), ("WEBP", "webp")]:
            upload = SimpleUploadedFile(f"proof.{ext}", make_image(fmt).read(), "image/*")
            with self.subTest(fmt=fmt):
                validate_proof_image(upload)

    def test_rejects_non_image(self):
        upload = SimpleUploadedFile("proof.png", b"definitely not an image", "image/png")
        with self.assertRaises(ValidationError):
            validate_proof_image(upload)

    def test_rejects_disallowed_format(self):
        upload = SimpleUploadedFile("proof.gif", make_image("GIF").read(), "image/gif")
        with self.assertRaises(ValidationError):
            validate_proof_image(upload)

    @override_settings(MAX_UPLOAD_BYTES=100)
    def test_rejects_oversized(self):
        upload = SimpleUploadedFile("proof.png", make_image("PNG", (400, 400)).read(), "image/png")
        with self.assertRaises(ValidationError):
            validate_proof_image(upload)

    def test_strip_metadata_drops_exif(self):
        buffer = io.BytesIO()
        img = Image.new("RGB", (24, 24), (10, 20, 30))
        exif = img.getexif()
        exif[271] = "SecretCamera"
        img.save(buffer, format="JPEG", exif=exif)
        buffer.seek(0)
        upload = SimpleUploadedFile("shot.jpg", buffer.read(), "image/jpeg")

        cleaned = strip_metadata(upload)
        with Image.open(cleaned) as reopened:
            self.assertEqual(dict(reopened.getexif()), {})
            self.assertEqual(reopened.size, (24, 24))
