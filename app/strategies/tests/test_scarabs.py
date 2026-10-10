"""Scarab catalogue: shape of the generated JSON, loader API and template tags.

Plain ``unittest`` / ``SimpleTestCase`` (no DB needed) but discoverable by
``manage.py test``.
"""

from __future__ import annotations

import unittest

from django.template import Context, Template
from django.template.library import InvalidTemplateLibrary
from django.test import SimpleTestCase

from strategies import scarabs


class BundleShapeTests(unittest.TestCase):
    def setUp(self):
        self.data = scarabs.load()

    def test_parses_with_version(self):
        self.assertIsInstance(self.data, dict)
        self.assertTrue(self.data.get("version"))
        self.assertIsInstance(self.data.get("scarabs"), dict)

    def test_has_the_full_scarab_set(self):
        self.assertGreaterEqual(len(self.data["scarabs"]), 80)

    def test_every_entry_has_a_cdn_icon_and_group(self):
        for name, entry in self.data["scarabs"].items():
            with self.subTest(scarab=name):
                self.assertIn("Scarab", name.split())
                self.assertTrue(entry["icon"].startswith("https://web.poecdn.com/"))
                self.assertTrue(entry["group"])

    def test_every_entry_has_an_in_game_description(self):
        empty = sorted(n for n, e in self.data["scarabs"].items() if not e.get("desc"))
        total = len(self.data["scarabs"])
        self.assertGreaterEqual(
            total - len(empty),
            110,
            f"{len(empty)} of {total} scarabs have no description: {empty}",
        )

    def test_descriptions_carry_no_markup(self):
        for name, entry in self.data["scarabs"].items():
            with self.subTest(scarab=name):
                desc = entry.get("desc", "")
                self.assertNotIn("<", desc)
                self.assertNotIn("&lt;", desc)
                self.assertNotIn("[[", desc)
                self.assertEqual(desc, desc.strip())

    def test_group_is_the_word_before_scarab(self):
        for name, entry in self.data["scarabs"].items():
            with self.subTest(scarab=name):
                words = name.split()
                index = words.index("Scarab")
                expected = words[index - 1] if index else "Scarab"
                self.assertEqual(entry["group"], expected)


class LoaderApiTests(unittest.TestCase):
    def test_all_scarabs_shape_and_sort(self):
        entries = scarabs.all_scarabs()
        self.assertEqual(len(entries), len(scarabs.load()["scarabs"]))
        for entry in entries:
            self.assertEqual(set(entry), {"name", "icon", "group", "desc"})
        keys = [(e["group"], e["name"]) for e in entries]
        self.assertEqual(keys, sorted(keys))

    def test_icon_for_exact_match(self):
        sample = scarabs.all_scarabs()[0]
        self.assertEqual(scarabs.icon_for(sample["name"]), sample["icon"])

    def test_icon_for_is_case_insensitive(self):
        sample = scarabs.all_scarabs()[0]
        self.assertEqual(scarabs.icon_for(sample["name"].upper()), sample["icon"])
        self.assertEqual(scarabs.icon_for(sample["name"].lower()), sample["icon"])

    def test_icon_for_strips_legacy_quantity_suffix(self):
        from strategies import scarabs

        known = scarabs.all_scarabs()[0]["name"]
        self.assertEqual(scarabs.icon_for(f"{known} x2"), scarabs.icon_for(known))
        self.assertEqual(scarabs.icon_for(f"{known} X13"), scarabs.icon_for(known))
        self.assertNotEqual(scarabs.icon_for(f"{known} x2"), "")

    def test_icon_for_unknown_is_empty(self):
        self.assertEqual(scarabs.icon_for("Not A Scarab"), "")
        self.assertEqual(scarabs.icon_for(""), "")

    def test_description_for_exact_match(self):
        sample = scarabs.all_scarabs()[0]
        self.assertEqual(scarabs.description_for(sample["name"]), sample["desc"])
        self.assertTrue(sample["desc"])

    def test_description_for_is_case_insensitive(self):
        sample = scarabs.all_scarabs()[0]
        self.assertEqual(scarabs.description_for(sample["name"].upper()), sample["desc"])
        self.assertEqual(scarabs.description_for(sample["name"].lower()), sample["desc"])

    def test_description_for_strips_legacy_quantity_suffix(self):
        known = scarabs.all_scarabs()[0]["name"]
        self.assertEqual(
            scarabs.description_for(f"{known} x2"), scarabs.description_for(known)
        )
        self.assertEqual(
            scarabs.description_for(f"{known} X13"), scarabs.description_for(known)
        )

    def test_description_for_unknown_is_empty(self):
        self.assertEqual(scarabs.description_for("Not A Scarab"), "")
        self.assertEqual(scarabs.description_for(""), "")

    def test_groups(self):
        families = scarabs.groups()
        self.assertEqual(families, sorted(set(families)))
        self.assertIn("Titanic", families)
        self.assertIn("Horned", families)
        self.assertEqual(families, sorted({e["group"] for e in scarabs.all_scarabs()}))


class TemplateTagTests(SimpleTestCase):
    def test_library_registers_filter_and_tags(self):
        try:
            Template("{% load scarab_tags %}")
        except InvalidTemplateLibrary as exc:  # pragma: no cover - failure path
            self.fail(f"scarab_tags is not loadable: {exc}")

    def test_scarab_icon_filter_resolves(self):
        sample = scarabs.all_scarabs()[0]
        rendered = Template(
            "{% load scarab_tags %}{{ name|scarab_icon }}"
        ).render(Context({"name": sample["name"]}))
        self.assertEqual(rendered, sample["icon"])

    def test_scarab_icon_filter_unknown_is_empty(self):
        rendered = Template(
            "{% load scarab_tags %}[{{ name|scarab_icon }}]"
        ).render(Context({"name": "Nonexistent Scarab of Nothing"}))
        self.assertEqual(rendered, "[]")

    def test_scarab_desc_filter_resolves(self):
        sample = scarabs.all_scarabs()[0]
        rendered = Template(
            "{% load scarab_tags %}{{ name|scarab_desc }}"
        ).render(Context({"name": sample["name"]}))
        self.assertEqual(rendered, sample["desc"])

    def test_scarab_desc_filter_unknown_is_empty(self):
        rendered = Template(
            "{% load scarab_tags %}[{{ name|scarab_desc }}]"
        ).render(Context({"name": "Nonexistent Scarab of Nothing"}))
        self.assertEqual(rendered, "[]")

    def test_scarab_list_entries_carry_desc(self):
        rendered = Template(
            "{% load scarab_tags %}{% scarab_list as items %}"
            "{% for item in items %}{{ item.desc|length }},{% endfor %}"
        ).render(Context({}))
        lengths = [int(part) for part in rendered.split(",") if part]
        self.assertEqual(len(lengths), len(scarabs.all_scarabs()))
        self.assertTrue(all(lengths))

    def test_scarab_list_tag_returns_python_list(self):
        rendered = Template(
            "{% load scarab_tags %}{% scarab_list as items %}{{ items|length }}"
        ).render(Context({}))
        self.assertEqual(rendered, str(len(scarabs.all_scarabs())))

    def test_scarab_list_json_scriptable(self):
        sample = scarabs.all_scarabs()[0]
        rendered = Template(
            "{% load scarab_tags %}{% scarab_list as items %}"
            '{{ items|json_script:"scarab-data" }}'
        ).render(Context({}))
        self.assertIn('id="scarab-data"', rendered)
        self.assertIn(sample["name"], rendered)

    def test_scarab_groups_tag(self):
        rendered = Template(
            "{% load scarab_tags %}{% scarab_groups as families %}{{ families|length }}"
        ).render(Context({}))
        self.assertEqual(rendered, str(len(scarabs.groups())))
