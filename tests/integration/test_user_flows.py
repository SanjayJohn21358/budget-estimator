"""End-to-end-ish flow tests covering common user actions on an estimate.

These exercise the real model + helper logic without spinning up Streamlit.
They simulate the sequence the original bug report described:
- create line items in multiple sections
- insert a new line item into an earlier section
- edit description text on existing items
- reorder/delete entries
- ensure stable IDs are preserved across operations
"""

from __future__ import annotations

import unittest

from config import CostConfig
from models import LineItem, LineItemEntry, ProjectEstimate
from ui.interactive import (
    _ensure_sections,
    _line_item_insert_index,
    _move_line_item_within_section,
)
from ui.text_mode import _merge_into_existing


def _make_estimate() -> ProjectEstimate:
    return ProjectEstimate(
        sections=["CLEANUP/PREP", "DESIGN", "INSTALL"],
        line_items=[
            LineItem(name="Cleanup A", section="CLEANUP/PREP", element_notes="Clear yard"),
            LineItem(name="Design A", section="DESIGN", element_notes="Plan deck layout"),
            LineItem(name="Install A", section="INSTALL", element_notes="Build deck"),
        ],
    )


class UserFlowTests(unittest.TestCase):
    def test_insert_into_earlier_section_preserves_descriptions_and_ids(self) -> None:
        est = _make_estimate()

        original_keys = {li.name: li.ui_key for li in est.line_items}
        original_descs = {li.name: li.element_notes for li in est.line_items}

        new_li = LineItem(
            name="Cleanup B",
            section="CLEANUP/PREP",
            element_notes="Pull weeds",
        )
        idx = _line_item_insert_index(est, "CLEANUP/PREP")
        est.line_items.insert(idx, new_li)

        for name, key in original_keys.items():
            li = next(li for li in est.line_items if li.name == name)
            self.assertEqual(li.ui_key, key, f"{name} ui_key changed unexpectedly")
            self.assertEqual(li.element_notes, original_descs[name])

        names = [li.name for li in est.line_items]
        self.assertEqual(
            names,
            ["Cleanup A", "Cleanup B", "Design A", "Install A"],
        )

    def test_move_line_item_within_section_keeps_ids_with_items(self) -> None:
        est = ProjectEstimate(
            sections=["CLEANUP/PREP"],
            line_items=[
                LineItem(name="First", section="CLEANUP/PREP", element_notes="First desc"),
                LineItem(name="Second", section="CLEANUP/PREP", element_notes="Second desc"),
            ],
        )
        first_key = est.line_items[0].ui_key
        second_key = est.line_items[1].ui_key

        moved = _move_line_item_within_section(est, 0, direction=1)
        self.assertTrue(moved)

        first = next(li for li in est.line_items if li.name == "First")
        second = next(li for li in est.line_items if li.name == "Second")
        self.assertEqual(first.ui_key, first_key)
        self.assertEqual(first.element_notes, "First desc")
        self.assertEqual(second.ui_key, second_key)
        self.assertEqual(second.element_notes, "Second desc")
        self.assertEqual([li.name for li in est.line_items], ["Second", "First"])

    def test_entry_reorder_and_delete_preserves_keys(self) -> None:
        li = LineItem(
            name="Cleanup",
            section="CLEANUP/PREP",
            entries=[
                LineItemEntry(material_name="Mulch", quantity=2),
                LineItemEntry(material_name="Stake", quantity=5),
                LineItemEntry(material_name="Gravel", quantity=1),
            ],
        )
        keys_before = [e.ui_key for e in li.entries]

        li.entries[0], li.entries[1] = li.entries[1], li.entries[0]
        self.assertEqual(li.entries[0].material_name, "Stake")
        self.assertEqual(li.entries[1].material_name, "Mulch")
        self.assertEqual(li.entries[0].ui_key, keys_before[1])
        self.assertEqual(li.entries[1].ui_key, keys_before[0])

        del li.entries[1]
        self.assertEqual([e.material_name for e in li.entries], ["Stake", "Gravel"])
        self.assertNotIn(keys_before[0], [e.ui_key for e in li.entries])
        self.assertIn(keys_before[2], [e.ui_key for e in li.entries])

    def test_ensure_sections_migrates_orphans_into_general(self) -> None:
        est = ProjectEstimate(
            sections=[],
            line_items=[LineItem(name="Cleanup", section="")],
        )
        _ensure_sections(est)
        self.assertEqual(est.line_items[0].section, "GENERAL")
        self.assertIn("GENERAL", est.sections)

    def test_text_mode_merge_keeps_existing_keys_and_adds_new_section(self) -> None:
        existing = ProjectEstimate(
            sections=["CLEANUP"],
            line_items=[
                LineItem(
                    name="Fence",
                    section="CLEANUP",
                    entries=[LineItemEntry(material_name="Post", quantity=1)],
                ),
            ],
        )
        existing_key = existing.line_items[0].ui_key

        generated = ProjectEstimate(
            line_items=[
                LineItem(
                    name="fence",
                    entries=[LineItemEntry(material_name="Rail", quantity=2)],
                    labor_hours=2,
                ),
                LineItem(
                    name="Plants",
                    entries=[LineItemEntry(material_name="Mulch", quantity=10)],
                ),
            ]
        )
        merged = _merge_into_existing(existing, generated)

        fence = next(li for li in merged.line_items if li.name.lower() == "fence")
        self.assertEqual(fence.ui_key, existing_key)
        self.assertEqual(len(fence.entries), 2)
        self.assertEqual(fence.labor_hours, 2)

        plants = next(li for li in merged.line_items if li.name == "Plants")
        self.assertEqual(plants.section, "CLEANUP")

    def test_grand_total_after_user_flow_matches_components(self) -> None:
        cfg = CostConfig(
            dump_run_cost=100,
            labor_rate_per_hour=50,
            crew_size=2,
        )
        est = _make_estimate()
        cleanup = est.line_items[0]
        cleanup.entries.append(LineItemEntry(material_name="Mulch", quantity=10, cost_per_unit=2))
        cleanup.dump_runs = 1
        cleanup.labor_hours = 1.5

        design = est.line_items[1]
        design.entries.append(LineItemEntry(material_name="Plan", quantity=1, cost_per_unit=200))

        materials = est.total_materials_cost(cfg)
        labor = est.total_labor_cost(cfg)
        dump = est.total_dump_cost(cfg)
        total = est.grand_total(cfg)

        self.assertEqual(materials, 220.0)
        self.assertEqual(dump, 100.0)
        self.assertEqual(labor, 1.5 * 50 * 2)
        self.assertEqual(total, materials + labor + dump)


if __name__ == "__main__":
    unittest.main()
