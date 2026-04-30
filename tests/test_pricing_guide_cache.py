"""Unit tests for PricingGuide lookup caches.

The interactive estimator calls get_material_by_name once per entry on every
rerun. These tests pin the contract that the lookup is O(1) after first use
and that the caches survive serialization round-trips.
"""

from __future__ import annotations

import unittest

from models import Material, PricingGuide


class PricingGuideLookupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.guide = PricingGuide(
            categories={
                "Plants": [
                    Material(name="Mulch", category="Plants", retail_with_tax=2.0),
                    Material(name="Stake", category="Plants", retail_with_tax=4.0),
                ],
                "Lumber": [
                    Material(name="2x4", category="Lumber", retail_with_tax=3.0),
                ],
            }
        )

    def test_get_material_by_name_is_case_insensitive(self) -> None:
        self.assertEqual(self.guide.get_material_by_name("MULCH").name, "Mulch")
        self.assertEqual(self.guide.get_material_by_name("  2x4 ").name, "2x4")

    def test_get_material_by_name_returns_none_for_unknown(self) -> None:
        self.assertIsNone(self.guide.get_material_by_name("Nonexistent"))

    def test_lookup_cache_is_reused(self) -> None:
        first = self.guide._name_lookup()
        second = self.guide._name_lookup()
        self.assertIs(first, second)

    def test_all_materials_cache_is_reused(self) -> None:
        first = self.guide.all_materials
        second = self.guide.all_materials
        self.assertIs(first, second)

    def test_caches_survive_model_validate_roundtrip(self) -> None:
        roundtripped = PricingGuide.model_validate(self.guide.model_dump())
        # Lookup still finds materials; cache rebuilds lazily on first call.
        self.assertEqual(roundtripped.get_material_by_name("Mulch").name, "Mulch")
        self.assertEqual(len(roundtripped.all_materials), 3)


if __name__ == "__main__":
    unittest.main()
