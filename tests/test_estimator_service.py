"""Unit tests for estimator service behavior."""

from __future__ import annotations

import unittest

from config import CostConfig
from models import LineItem, LineItemEntry, Material, PricingGuide, ProjectEstimate
from services.estimator import EstimatorService


class EstimatorServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pricing = PricingGuide(
            categories={
                "Plants": [Material(name="Mulch", category="Plants", retail_with_tax=2.0)],
                "Lumber": [Material(name="2x4", category="Lumber", retail_with_tax=3.0)],
                "Misc": [Material(name="Stake", category="Misc", retail_with_tax=4.0)],
            }
        )
        self.cfg = CostConfig(plant_delivery_pct=0.1)
        self.service = EstimatorService(self.cfg, self.pricing)

    def test_recalculate_entry_respects_locked_price(self) -> None:
        entry = LineItemEntry(
            material_name="Mulch",
            quantity=1,
            cost_per_unit=99.0,
            use_dynamic_pricing=False,
        )
        out = self.service.recalculate_entry(entry)
        self.assertEqual(out.cost_per_unit, 99.0)

    def test_recalculate_entry_updates_area_price_when_area_based(self) -> None:
        entry = LineItemEntry(
            material_name="Mulch",
            area_value=10,
            price_per_area=1.0,
            use_dynamic_pricing=True,
        )
        out = self.service.recalculate_entry(entry)
        self.assertEqual(out.price_per_area, 2.0)

    def test_recalculate_line_item_aggregates_quantity_if_zero(self) -> None:
        li = LineItem(
            name="Test",
            quantity=0,
            entries=[LineItemEntry(quantity=2), LineItemEntry(quantity=3)],
        )
        out = self.service.recalculate_line_item(li)
        self.assertEqual(out.quantity, 5)

    def test_apply_plant_delivery_replaces_existing_delivery_entry(self) -> None:
        plants = LineItem(
            name="Plants",
            entries=[
                LineItemEntry(material_name="Mulch", quantity=10, cost_per_unit=2.0),
                LineItemEntry(material_name="Plant Delivery", quantity=1, cost_per_unit=999),
            ],
        )
        estimate = ProjectEstimate(line_items=[plants])
        out = self.service.apply_plant_delivery(estimate)
        delivery_entries = [e for e in out.line_items[0].entries if e.material_name == "Plant Delivery"]
        self.assertEqual(len(delivery_entries), 1)
        # Current behavior computes delivery from pre-cleanup materials subtotal.
        self.assertEqual(delivery_entries[0].cost_per_unit, 101.9)

    def test_build_estimate_from_llm_handles_unknown_category_and_bad_labor(self) -> None:
        llm_items = [
            {
                "line_item": "Unknown Bucket",
                "material_name": "Unknown Material",
                "quantity": 2,
                "labor_hours": "bad",
                "dump_runs": 1,
            }
        ]
        estimate = self.service.build_estimate_from_llm(
            llm_items=llm_items,
            line_item_names=["Cleanup", "Misc"],
        )
        # unknown category should end up in Misc when present
        misc = next(li for li in estimate.line_items if li.name == "Misc")
        self.assertEqual(len(misc.entries), 1)
        self.assertEqual(misc.entries[0].material_name, "Unknown Material")
        self.assertEqual(misc.entries[0].cost_per_unit, 0.0)
        self.assertEqual(misc.entries[0].labor_hours, 0.0)
        self.assertEqual(misc.dump_runs, 1)


if __name__ == "__main__":
    unittest.main()
