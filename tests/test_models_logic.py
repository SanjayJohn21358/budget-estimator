"""Unit tests for pricing and summary model behavior."""

from __future__ import annotations

import unittest

from config import CostConfig
from models import LineItem, LineItemEntry, ProjectEstimate


class ModelLogicTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = CostConfig(dump_run_cost=100, labor_rate_per_hour=50, crew_size=2)

    def test_line_item_entry_linear_total_cost(self) -> None:
        entry = LineItemEntry(cost_per_unit=3.0, quantity=4.0, length_feet=8.0)
        self.assertEqual(entry.total_cost, 96.0)

    def test_line_item_entry_area_piece_total_rounding(self) -> None:
        entry = LineItemEntry(
            area_value=12.5,
            price_per_area=2.345,
            quantity=3,
            cost_per_unit=1.234,
        )
        # 12.5*2.345 + 3*1.234 = 33.0145 -> 33.01
        self.assertEqual(entry.total_cost, 33.01)

    def test_line_item_totals_include_material_labor_dump(self) -> None:
        li = LineItem(
            name="Cleanup",
            dump_runs=2,
            labor_hours=1.5,
            entries=[
                LineItemEntry(cost_per_unit=10, quantity=3, labor_hours=2),
                LineItemEntry(area_value=20, price_per_area=1.5, labor_hours=1),
            ],
        )
        self.assertEqual(li.materials_total(self.cfg), 60.0)
        self.assertEqual(li.dump_cost(self.cfg), 200.0)
        # labor hours = 1.5 + 2 + 1 = 4.5; *50*2 = 450
        self.assertEqual(li.labor_cost(self.cfg), 450.0)
        self.assertEqual(li.total_element_price(self.cfg), 710.0)

    def test_project_budget_delta_sign(self) -> None:
        estimate = ProjectEstimate(
            project_budget=1000,
            line_items=[LineItem(name="A", entries=[LineItemEntry(cost_per_unit=200, quantity=2)])],
        )
        self.assertEqual(estimate.budget_delta(self.cfg), 600.0)

    def test_to_summary_dataframe_routes_linear_area_piece_columns(self) -> None:
        li = LineItem(
            name="Mixed",
            section="DESIGN",
            element_notes="Main description",
            entries=[
                LineItemEntry(
                    material_name="Lumber",
                    unit_hint="ft",
                    quantity=4,
                    length_feet=8,
                    cost_per_unit=3.0,
                ),
                LineItemEntry(
                    material_name="Mulch",
                    unit_hint="sf",
                    area_value=40,
                    price_per_area=2.0,
                ),
                LineItemEntry(
                    material_name="Stake",
                    quantity=5,
                    cost_per_unit=4.0,
                ),
            ],
        )
        df = ProjectEstimate(line_items=[li]).to_summary_dataframe(self.cfg)
        self.assertEqual(len(df), 3)
        # Linear row
        self.assertEqual(df.iloc[0]["Sq Ft / LF / CY"], 8)
        self.assertEqual(df.iloc[0]["Quantity"], 4)
        self.assertTrue(df.iloc[0]["Element w/ Notes"].endswith("Main description"))
        # Area row
        self.assertEqual(df.iloc[1]["Sq Ft / LF / CY"], 40)
        self.assertEqual(df.iloc[1]["$/sf"], 2.0)
        # Piece row
        self.assertEqual(df.iloc[2]["Quantity"], 5)
        self.assertEqual(df.iloc[2]["$/pc"], 4.0)

    def test_empty_summary_dataframe(self) -> None:
        df = ProjectEstimate().to_summary_dataframe(self.cfg)
        self.assertTrue(df.empty)


if __name__ == "__main__":
    unittest.main()
