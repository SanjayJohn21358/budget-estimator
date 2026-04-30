"""Unit tests for additive merge behavior in text mode."""

from __future__ import annotations

import unittest

from models import LineItem, LineItemEntry, ProjectEstimate
from ui.text_mode import _merge_into_existing


class TextModeMergeTests(unittest.TestCase):
    def test_merge_extends_existing_line_item_case_insensitive(self) -> None:
        existing = ProjectEstimate(
            sections=["GENERAL"],
            line_items=[
                LineItem(
                    name="Fence",
                    section="GENERAL",
                    entries=[LineItemEntry(material_name="Post", quantity=1)],
                    labor_hours=1.0,
                    dump_runs=1,
                    sq_ft=10,
                )
            ],
        )
        generated = ProjectEstimate(
            line_items=[
                LineItem(
                    name="fence",
                    entries=[LineItemEntry(material_name="Rail", quantity=2)],
                    labor_hours=2.0,
                    dump_runs=2,
                    sq_ft=15,
                )
            ]
        )
        out = _merge_into_existing(existing, generated)
        self.assertEqual(len(out.line_items), 1)
        li = out.line_items[0]
        self.assertEqual(len(li.entries), 2)
        self.assertEqual(li.labor_hours, 3.0)
        self.assertEqual(li.dump_runs, 3)
        self.assertEqual(li.sq_ft, 25)

    def test_merge_adds_new_line_item_with_default_section(self) -> None:
        existing = ProjectEstimate(sections=["CLEANUP"], line_items=[])
        generated = ProjectEstimate(
            line_items=[LineItem(name="Design", entries=[LineItemEntry(material_name="Plan", quantity=1)])]
        )
        out = _merge_into_existing(existing, generated)
        self.assertEqual(len(out.line_items), 1)
        self.assertEqual(out.line_items[0].section, "CLEANUP")


if __name__ == "__main__":
    unittest.main()
