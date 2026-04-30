"""Integration-style tests for SheetsService using mocked gspread."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from config import CostConfig, SheetConfig
from models import LineItem, LineItemEntry, ProjectEstimate
from services.sheets import SheetsService


def _make_service() -> tuple[SheetsService, MagicMock]:
    """Construct a SheetsService whose internal client is a MagicMock."""
    cfg = SheetConfig(
        pricing_guide_sheet_id="pg",
        output_template_sheet_id="ot",
        estimates_sheet_id="es",
        pricing_guide_tab_name="Pricing",
        output_template_tab_name="Template",
    )
    svc = SheetsService(cfg)
    fake_client = MagicMock()
    svc._client = fake_client  # bypass real auth
    return svc, fake_client


class SheetsServiceLoadTests(unittest.TestCase):
    def test_load_pricing_guide_groups_by_category(self) -> None:
        svc, client = _make_service()

        ws = MagicMock()
        ws.get_all_values.return_value = [
            ["Name", "Cost", "Cost+Tax", "Retail", "Retail+Tax", "Notes", "Vendor", "Updated"],
            ["Plants", "", "", "", "", "", "", ""],
            ["Mulch", "1.00", "1.10", "2.00", "2.20", "per sf", "ACME", "2025-01-01"],
            ["Lumber", "", "", "", "", "", "", ""],
            ["2x4", "2.00", "2.20", "3.00", "3.30", "per LF", "ACME", "2025-01-01"],
            ["", "", "", "", "", "", "", ""],
        ]
        sheet = MagicMock()
        sheet.worksheet.return_value = ws
        client.open_by_key.return_value = sheet

        guide = svc.load_pricing_guide()
        self.assertIn("Plants", guide.categories)
        self.assertIn("Lumber", guide.categories)
        self.assertEqual(len(guide.categories["Plants"]), 1)
        self.assertEqual(guide.categories["Lumber"][0].unit_hint, "ft")

    def test_load_template_line_items_skips_header_rows(self) -> None:
        svc, client = _make_service()

        ws = MagicMock()
        ws.get_all_values.return_value = [
            ["header"],
            ["meta"],
            ["meta"],
            ["Cleanup"],
            ["Design"],
            ["Cleanup"],
            [""],
        ]
        sheet = MagicMock()
        sheet.worksheet.return_value = ws
        client.open_by_key.return_value = sheet

        names = svc.load_template_line_items()
        self.assertEqual(names, ["Cleanup", "Design"])


class SheetsServiceImportTests(unittest.TestCase):
    def test_import_estimate_reconstructs_sections_and_entries(self) -> None:
        svc, client = _make_service()

        ws = MagicMock()
        ws.get_all_values.return_value = [
            [],
            ["123 Main", "", "5000", "", "TRUE", "", "FALSE"],
            [],
            ["CLEANUP/PREP"],
            ["Cleanup", "notes A", "Mulch — desc", "20", "1.5", "", "", "30", "2", "", "", "", "1"],
            ["DESIGN"],
            ["Design", "notes B", "Plan", "", "", "1", "100", "100", "", "", "", "", "0.5"],
        ]
        sheet = MagicMock()
        sheet.worksheet.return_value = ws
        client.open_by_key.return_value = sheet

        est = svc.import_estimate_from_sheet("Estimate - Test", pricing_guide=None)
        self.assertEqual(est.address, "123 Main")
        self.assertEqual(est.project_budget, 5000)
        self.assertEqual(est.access_level, "Easy")
        self.assertEqual(est.sections, ["CLEANUP/PREP", "DESIGN"])
        self.assertEqual(len(est.line_items), 2)

        cleanup = est.line_items[0]
        self.assertEqual(cleanup.name, "Cleanup")
        self.assertEqual(cleanup.section, "CLEANUP/PREP")
        self.assertEqual(cleanup.notes, "notes A")
        self.assertEqual(cleanup.dump_runs, 2)
        self.assertEqual(len(cleanup.entries), 1)
        self.assertEqual(cleanup.entries[0].material_name, "Mulch")
        self.assertEqual(cleanup.entries[0].area_value, 20)
        self.assertEqual(cleanup.entries[0].price_per_area, 1.5)
        self.assertFalse(cleanup.entries[0].use_dynamic_pricing)

        design = est.line_items[1]
        self.assertEqual(design.section, "DESIGN")
        self.assertEqual(design.entries[0].quantity, 1)
        self.assertEqual(design.entries[0].cost_per_unit, 100)

    def test_import_estimate_raises_when_too_few_rows(self) -> None:
        svc, client = _make_service()
        ws = MagicMock()
        ws.get_all_values.return_value = [["only one row"]]
        sheet = MagicMock()
        sheet.worksheet.return_value = ws
        client.open_by_key.return_value = sheet

        with self.assertRaises(ValueError):
            svc.import_estimate_from_sheet("Estimate - Bad", pricing_guide=None)


class SheetsServiceExportTests(unittest.TestCase):
    def _build_estimate(self) -> ProjectEstimate:
        return ProjectEstimate(
            address="123 Main",
            project_budget=5000,
            access_level="Medium",
            sections=["CLEANUP/PREP", "DESIGN"],
            line_items=[
                LineItem(
                    name="Cleanup",
                    section="CLEANUP/PREP",
                    notes="prep notes",
                    dump_runs=2,
                    entries=[
                        LineItemEntry(
                            material_name="Mulch",
                            area_value=20,
                            price_per_area=1.5,
                            unit_hint="sf",
                        ),
                    ],
                ),
                LineItem(
                    name="Design",
                    section="DESIGN",
                    entries=[
                        LineItemEntry(
                            material_name="Plan",
                            quantity=1,
                            cost_per_unit=100,
                        ),
                    ],
                ),
            ],
        )

    def test_export_writes_header_section_rows_and_grand_total(self) -> None:
        svc, client = _make_service()
        sheet = MagicMock()
        client.open_by_key.return_value = sheet

        template_ws = MagicMock()
        template_ws.id = 111
        new_ws = MagicMock()
        new_ws.id = 222

        sheet.worksheet.return_value = template_ws
        sheet.worksheets.return_value = []
        sheet.duplicate_sheet.return_value = new_ws
        sheet.url = "https://docs.google.com/spreadsheets/d/test"

        url = svc.export_estimate_to_sheet(
            tab_title="Estimate - Test",
            estimate=self._build_estimate(),
            cost_config=CostConfig(),
        )

        self.assertTrue(new_ws.batch_update.called)
        updates = new_ws.batch_update.call_args[0][0]
        ranges = {u["range"]: u["values"] for u in updates}

        self.assertEqual(ranges["A2"], [["123 Main"]])
        self.assertEqual(ranges["C2"], [[5000]])
        self.assertEqual(ranges["E2"], [[False]])
        self.assertEqual(ranges["G2"], [[True]])

        section_rows = [u for u in updates if u.get("values") == [["CLEANUP/PREP"]]]
        self.assertTrue(section_rows)

        self.assertTrue(url.endswith(f"#gid={new_ws.id}"))
        self.assertTrue(new_ws.update_title.called)


if __name__ == "__main__":
    unittest.main()
