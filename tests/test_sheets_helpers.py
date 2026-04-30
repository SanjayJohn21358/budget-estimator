"""Unit tests for Sheets parsing helper functions."""

from __future__ import annotations

import unittest

from services.sheets import (
    _build_entry_from_columns,
    _detect_unit_hint,
    _parse_element_text,
    _parse_price_range,
)


class SheetsHelperTests(unittest.TestCase):
    def test_parse_price_range_single_value(self) -> None:
        default, lo, hi = _parse_price_range("$12.50")
        self.assertEqual(default, 12.5)
        self.assertIsNone(lo)
        self.assertIsNone(hi)

    def test_parse_price_range_hyphen_range(self) -> None:
        default, lo, hi = _parse_price_range("10-20")
        self.assertEqual(default, 15.0)
        self.assertEqual(lo, 10.0)
        self.assertEqual(hi, 20.0)

    def test_parse_price_range_en_dash_and_reversed(self) -> None:
        default, lo, hi = _parse_price_range("20–10")
        self.assertEqual(default, 15.0)
        self.assertEqual(lo, 10.0)
        self.assertEqual(hi, 20.0)

    def test_detect_unit_hint_variants(self) -> None:
        self.assertEqual(_detect_unit_hint("apply at 50 sf"), "sf")
        self.assertEqual(_detect_unit_hint("sold per sq ft"), "sf")
        self.assertEqual(_detect_unit_hint("price is per LF"), "ft")
        self.assertEqual(_detect_unit_hint("needs 2 cu yd"), "cuyd")
        self.assertEqual(_detect_unit_hint("needs 3 cu ft"), "cuft")

    def test_parse_element_text_full_format(self) -> None:
        mat, notes, desc = _parse_element_text("Mulch (front yard) — spread in beds")
        self.assertEqual(mat, "Mulch")
        self.assertEqual(notes, "front yard")
        self.assertEqual(desc, "spread in beds")

    def test_parse_element_text_material_only(self) -> None:
        mat, notes, desc = _parse_element_text("Stake")
        self.assertEqual((mat, notes, desc), ("Stake", "", ""))

    def test_build_entry_from_columns_linear(self) -> None:
        entry = _build_entry_from_columns(
            mat_name="2x4",
            category="Lumber",
            entry_notes="",
            area_val=8.0,
            area_price=3.0,
            qty_val=5.0,
            pc_price=0.0,
            hint="ft",
            labor_hours=1.5,
        )
        self.assertEqual(entry.length_feet, 8.0)
        self.assertEqual(entry.quantity, 5.0)
        self.assertEqual(entry.cost_per_unit, 3.0)
        self.assertFalse(entry.use_dynamic_pricing)

    def test_build_entry_from_columns_area(self) -> None:
        entry = _build_entry_from_columns(
            mat_name="Mulch",
            category="Plants",
            entry_notes="",
            area_val=20.0,
            area_price=2.5,
            qty_val=0.0,
            pc_price=0.0,
            hint="sf",
            labor_hours=0.0,
        )
        self.assertEqual(entry.area_value, 20.0)
        self.assertEqual(entry.price_per_area, 2.5)
        self.assertFalse(entry.use_dynamic_pricing)

    def test_build_entry_from_columns_piece(self) -> None:
        entry = _build_entry_from_columns(
            mat_name="Stake",
            category="Supplies",
            entry_notes="",
            area_val=0.0,
            area_price=0.0,
            qty_val=3.0,
            pc_price=4.0,
            hint="",
            labor_hours=0.0,
        )
        self.assertEqual(entry.quantity, 3.0)
        self.assertEqual(entry.cost_per_unit, 4.0)
        self.assertIsNone(entry.length_feet)


if __name__ == "__main__":
    unittest.main()
