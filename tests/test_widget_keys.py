"""Regression tests for stable widget identity models."""

from __future__ import annotations

import unittest

from models import LineItem, ProjectEstimate


class WidgetKeyModelTests(unittest.TestCase):
    def test_line_item_generates_ui_key(self) -> None:
        li = LineItem(name="Cleanup", section="CLEANUP/PREP")
        self.assertTrue(li.ui_key)
        self.assertIsInstance(li.ui_key, str)

    def test_line_item_ui_keys_are_unique(self) -> None:
        li1 = LineItem(name="Cleanup")
        li2 = LineItem(name="Design")
        self.assertNotEqual(li1.ui_key, li2.ui_key)

    def test_legacy_payload_without_ui_key_is_backfilled(self) -> None:
        legacy_payload = {
            "sections": ["CLEANUP/PREP"],
            "line_items": [
                {
                    "name": "Cleanup",
                    "section": "CLEANUP/PREP",
                    "notes": "",
                    "element_notes": "",
                    "entries": [],
                }
            ],
        }
        estimate = ProjectEstimate.model_validate(legacy_payload)
        self.assertEqual(len(estimate.line_items), 1)
        self.assertTrue(estimate.line_items[0].ui_key)

    def test_existing_ui_key_is_preserved(self) -> None:
        payload = {
            "sections": ["DESIGN"],
            "line_items": [
                {
                    "ui_key": "known-key",
                    "name": "Design",
                    "section": "DESIGN",
                    "entries": [],
                }
            ],
        }
        estimate = ProjectEstimate.model_validate(payload)
        self.assertEqual(estimate.line_items[0].ui_key, "known-key")


if __name__ == "__main__":
    unittest.main()
