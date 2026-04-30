"""Regression tests for line-item ordering and movement rules."""

from __future__ import annotations

import unittest

from models import LineItem, ProjectEstimate
from ui.interactive import _line_item_insert_index, _move_line_item_within_section


class LineItemOrderingTests(unittest.TestCase):
    def test_insert_index_keeps_section_blocks_grouped(self) -> None:
        estimate = ProjectEstimate(
            sections=["CLEANUP/PREP", "DESIGN", "INSTALL"],
            line_items=[
                LineItem(name="Cleanup A", section="CLEANUP/PREP"),
                LineItem(name="Cleanup B", section="CLEANUP/PREP"),
                LineItem(name="Design A", section="DESIGN"),
                LineItem(name="Install A", section="INSTALL"),
            ],
        )

        idx = _line_item_insert_index(estimate, "CLEANUP/PREP")
        self.assertEqual(idx, 2)

    def test_insert_index_for_middle_section(self) -> None:
        estimate = ProjectEstimate(
            sections=["CLEANUP/PREP", "DESIGN", "INSTALL"],
            line_items=[
                LineItem(name="Cleanup A", section="CLEANUP/PREP"),
                LineItem(name="Install A", section="INSTALL"),
            ],
        )

        idx = _line_item_insert_index(estimate, "DESIGN")
        self.assertEqual(idx, 1)

    def test_move_within_same_section_allowed(self) -> None:
        estimate = ProjectEstimate(
            sections=["CLEANUP/PREP", "DESIGN"],
            line_items=[
                LineItem(name="Cleanup A", section="CLEANUP/PREP"),
                LineItem(name="Cleanup B", section="CLEANUP/PREP"),
                LineItem(name="Design A", section="DESIGN"),
            ],
        )

        moved = _move_line_item_within_section(estimate, 1, direction=-1)
        self.assertTrue(moved)
        self.assertEqual(estimate.line_items[0].name, "Cleanup B")
        self.assertEqual(estimate.line_items[1].name, "Cleanup A")

    def test_move_across_section_boundary_blocked(self) -> None:
        estimate = ProjectEstimate(
            sections=["CLEANUP/PREP", "DESIGN"],
            line_items=[
                LineItem(name="Cleanup A", section="CLEANUP/PREP"),
                LineItem(name="Design A", section="DESIGN"),
            ],
        )

        moved = _move_line_item_within_section(estimate, 0, direction=1)
        self.assertFalse(moved)
        self.assertEqual(estimate.line_items[0].name, "Cleanup A")
        self.assertEqual(estimate.line_items[1].name, "Design A")


if __name__ == "__main__":
    unittest.main()
