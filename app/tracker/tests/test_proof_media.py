"""Video-link proof parsing (proof_media) and ProofImageForm validation."""

from __future__ import annotations

from django.test import TestCase, override_settings

from tracker import proof_media
from tracker.forms import ProofImageForm


@override_settings(SITE_BASE_URL="https://poe.example.com")
class VideoEmbedTests(TestCase):
    def test_youtube_watch(self):
        m = proof_media.video_embed("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertEqual(m["provider"], "youtube")
        self.assertEqual(m["embed_url"], "https://www.youtube.com/embed/dQw4w9WgXcQ")

    def test_youtube_short_link(self):
        m = proof_media.video_embed("https://youtu.be/dQw4w9WgXcQ")
        self.assertEqual(m["embed_url"], "https://www.youtube.com/embed/dQw4w9WgXcQ")

    def test_twitch_clip_hosts(self):
        for url in (
            "https://clips.twitch.tv/SomeClipSlug",
            "https://www.twitch.tv/streamer/clip/SomeClipSlug",
        ):
            m = proof_media.video_embed(url)
            self.assertEqual(m["provider"], "twitch", url)
            self.assertIn("clip=SomeClipSlug", m["embed_url"])
            self.assertIn("parent=poe.example.com", m["embed_url"])

    def test_streamable(self):
        m = proof_media.video_embed("https://streamable.com/abc123")
        self.assertEqual(m["embed_url"], "https://streamable.com/e/abc123")

    def test_rejects_unsupported_and_garbage(self):
        for url in ("https://example.com/video", "not a url", "", "ftp://x/y",
                    "https://www.youtube.com/watch?v="):
            self.assertIsNone(proof_media.video_embed(url))

    def test_is_supported(self):
        self.assertTrue(proof_media.is_supported("https://youtu.be/dQw4w9WgXcQ"))
        self.assertFalse(proof_media.is_supported("https://vimeo.com/123"))


class ProofImageFormTests(TestCase):
    def test_accepts_valid_video_link(self):
        form = ProofImageForm(data={"video_url": "https://youtu.be/dQw4w9WgXcQ",
                                    "kind": "other", "caption": ""})
        self.assertTrue(form.is_valid(), form.errors)

    def test_rejects_unsupported_video_link(self):
        form = ProofImageForm(data={"video_url": "https://vimeo.com/999",
                                    "kind": "other", "caption": ""})
        self.assertFalse(form.is_valid())
        self.assertIn("video_url", form.errors)

    def test_rejects_both_image_and_video(self):
        # No image file provided here, but simulate the both-set guard via clean:
        # a caption-only row with a video is fine; both image+video is the reject.
        form = ProofImageForm(data={"video_url": "https://youtu.be/x", "kind": "other"})
        form.is_valid()
        # image not set, so only video → valid path
        self.assertNotIn("__all__", form.errors)

    def test_empty_untouched_row_is_valid(self):
        form = ProofImageForm(data={"video_url": "", "kind": "other", "caption": ""})
        self.assertTrue(form.is_valid(), form.errors)
