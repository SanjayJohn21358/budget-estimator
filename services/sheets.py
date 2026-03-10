"""Google Sheets integration service."""

from __future__ import annotations

import json
from typing import Any

import gspread
import streamlit as st
from google.oauth2.service_account import Credentials

from config import CostConfig, SheetConfig
from models import Material, PricingGuide, ProjectEstimate


_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


class SheetsService:
    """Reads and writes Google Sheets for the estimator app."""

    def __init__(self, config: SheetConfig) -> None:
        self._config = config
        self._client: gspread.Client | None = None

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def _get_client(self) -> gspread.Client:
        """Return an authenticated gspread client (cached on instance)."""
        if self._client is not None:
            return self._client

        # Streamlit Community Cloud stores secrets as a dict-like object.
        # We expect the service-account JSON under st.secrets["gcp_service_account"].
        creds_info: dict[str, Any] = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(creds_info, scopes=_SCOPES)
        self._client = gspread.authorize(creds)
        return self._client

    # ------------------------------------------------------------------
    # Pricing guide
    # ------------------------------------------------------------------

    def load_pricing_guide(self) -> PricingGuide:
        """Read the pricing guide sheet and parse into a PricingGuide model.

        Category headers are detected as rows where only column A has a value
        and columns B-E are empty (or the text is bold / all-caps — we use
        the heuristic of non-numeric B column).
        """
        client = self._get_client()
        sheet = client.open_by_key(self._config.pricing_guide_sheet_id)
        worksheet = sheet.worksheet(self._config.pricing_guide_tab_name)
        rows: list[list[str]] = worksheet.get_all_values()

        if not rows:
            return PricingGuide()

        # Skip header row (row index 0)
        data_rows = rows[1:]

        categories: dict[str, list[Material]] = {}
        current_category = "Uncategorized"

        for row in data_rows:
            # Pad row to at least 8 columns
            while len(row) < 8:
                row.append("")

            name = row[0].strip()
            cost_raw = row[1].strip()
            cost_tax_raw = row[2].strip()
            retail_raw = row[3].strip()
            retail_tax_raw = row[4].strip()
            notes = row[5].strip()
            vendor = row[6].strip()
            price_updated = row[7].strip() if len(row) > 7 else ""

            # Skip completely empty rows
            if not name:
                continue

            # Detect category header: name present but cost columns are empty
            if not retail_tax_raw:
                current_category = name
                if current_category not in categories:
                    categories[current_category] = []
                continue

            # Parse numeric fields safely, supporting ranges like "10-20"
            (
                cost,
                cost_min,
                cost_max,
            ) = _parse_price_range(cost_raw)
            (
                cost_with_tax,
                cost_with_tax_min,
                cost_with_tax_max,
            ) = _parse_price_range(cost_tax_raw)
            (
                retail,
                retail_min,
                retail_max,
            ) = _parse_price_range(retail_raw)
            (
                retail_with_tax,
                retail_with_tax_min,
                retail_with_tax_max,
            ) = _parse_price_range(retail_tax_raw)

            # Derive a simple unit hint from the notes column so the UI can
            # expose the right input (feet vs square feet).
            unit_hint = ""
            notes_lower = notes.lower()
            if "1 ft" in notes_lower:
                unit_hint = "ft"
            elif "1 sf" in notes_lower:
                unit_hint = "sf"

            material = Material(
                name=name,
                category=current_category,
                cost=cost,
                cost_with_tax=cost_with_tax,
                retail=retail,
                retail_with_tax=retail_with_tax,
                cost_min=cost_min,
                cost_max=cost_max,
                cost_with_tax_min=cost_with_tax_min,
                cost_with_tax_max=cost_with_tax_max,
                retail_min=retail_min,
                retail_max=retail_max,
                retail_with_tax_min=retail_with_tax_min,
                retail_with_tax_max=retail_with_tax_max,
                unit_hint=unit_hint,
                notes=notes,
                vendor=vendor,
                price_updated_on=price_updated,
            )

            if current_category not in categories:
                categories[current_category] = []
            categories[current_category].append(material)

        return PricingGuide(categories=categories)

    # ------------------------------------------------------------------
    # Template structure
    # ------------------------------------------------------------------

    def load_template_line_items(self) -> list[str]:
        """Read the output template sheet and extract line item category names.

        Returns a list of non-empty line item names from column A,
        skipping the header rows (rows 1-3 in the sheet).
        """
        client = self._get_client()
        sheet = client.open_by_key(self._config.output_template_sheet_id)
        worksheet = sheet.worksheet(self._config.output_template_tab_name)
        rows: list[list[str]] = worksheet.get_all_values()

        # The first 3 rows are header / config rows
        data_rows = rows[3:] if len(rows) > 3 else []

        line_items: list[str] = []
        seen: set[str] = set()
        for row in data_rows:
            if not row:
                continue
            name = row[0].strip()
            if name and name not in seen:
                line_items.append(name)
                seen.add(name)

        return line_items

    # ------------------------------------------------------------------
    # Export: duplicate template + fill in data
    # ------------------------------------------------------------------

    def export_estimate_to_sheet(
        self,
        tab_title: str,
        estimate: ProjectEstimate,
        cost_config: CostConfig,
    ) -> str:
        """Duplicate the template tab and fill in estimate data.

        This preserves all template formatting, formulas, column widths,
        colors, checkboxes, and structure. Only the data cells that
        correspond to estimate values are overwritten.

        The template tab is looked up inside the target spreadsheet
        (``estimates_sheet_id`` if set, otherwise ``output_template_sheet_id``).

        Args:
            tab_title: Human-readable name for the new tab.
            estimate: The project estimate to export.
            cost_config: Cost configuration for calculations.

        Returns:
            URL pointing directly to the new tab.
        """
        client = self._get_client()

        # Decide which spreadsheet to write into
        target_id = (
            self._config.estimates_sheet_id
            or self._config.output_template_sheet_id
            or self._config.pricing_guide_sheet_id
        )
        spreadsheet = client.open_by_key(target_id)

        # ---- Find the template worksheet to duplicate ----
        template_tab_name = self._config.output_template_tab_name
        try:
            template_ws = spreadsheet.worksheet(template_tab_name)
        except gspread.exceptions.WorksheetNotFound:
            raise ValueError(
                f"Template tab '{template_tab_name}' not found in the "
                f"target spreadsheet. Make sure it exists."
            )

        # ---- Ensure unique tab name ----
        tab_title = tab_title[:100]
        existing_titles = {ws.title for ws in spreadsheet.worksheets()}
        if tab_title in existing_titles:
            suffix = 1
            while f"{tab_title} ({suffix})" in existing_titles:
                suffix += 1
            tab_title = f"{tab_title} ({suffix})"

        # ---- Duplicate the template (preserves formatting & formulas) ----
        new_ws = spreadsheet.duplicate_sheet(
            source_sheet_id=template_ws.id,
            new_sheet_name=tab_title,
        )

        # ---- Read column A to map line-item names → row numbers ----
        col_a_values = new_ws.col_values(1)  # 1-indexed list of strings
        line_item_row_map: dict[str, int] = {}
        for row_idx, cell_val in enumerate(col_a_values, start=1):
            name = cell_val.strip()
            # Skip header rows (1–3); only map data rows
            if name and row_idx > 3:
                line_item_row_map[name.lower()] = row_idx

        # ---- Build batch of cell updates ----
        updates: list[dict[str, Any]] = []

        # Project info in the header area (row 2)
        # Based on template layout: B1="Project Estimate", C1="Project Budget"
        # Values go in row 2 beneath the labels
        updates.append({"range": "B2", "values": [[estimate.grand_total(cost_config)]]})
        updates.append({"range": "C2", "values": [[estimate.project_budget]]})

        # Address — write next to the "Address" label in A1
        # Put the actual address value in A2
        updates.append({"range": "A2", "values": [[estimate.address]]})

        # Access level checkboxes: E2=Easy, G2=Medium, I2=Difficult
        # (template has checkboxes; we set TRUE/FALSE)
        updates.append({
            "range": "E2",
            "values": [[estimate.access_level == "Easy"]],
        })
        updates.append({
            "range": "G2",
            "values": [[estimate.access_level == "Medium"]],
        })

        # ---- Fill in line-item data (one row per material entry) ----
        # Collect matched line items with their template row numbers
        matched_items: list[tuple[int, "LineItem"]] = []
        for li in estimate.line_items:
            row_num = line_item_row_map.get(li.name.lower())
            if row_num is not None:
                matched_items.append((row_num, li))

        # Sort descending so bottom-up inserts don't shift rows above
        matched_items.sort(key=lambda x: x[0], reverse=True)

        # Insert extra rows for line items with multiple entries
        for original_row, li in matched_items:
            extra = len(li.entries) - 1
            if extra > 0:
                blank_rows = [[""] * 17 for _ in range(extra)]
                new_ws.insert_rows(blank_rows, row=original_row + 1)

        # Re-sort ascending and track cumulative offset from inserts
        matched_items.sort(key=lambda x: x[0])
        offset = 0

        for original_row, li in matched_items:
            actual_start = original_row + offset
            entries = li.entries
            num_rows = max(len(entries), 1)

            for i in range(num_rows):
                r = actual_start + i
                is_first = i == 0

                # Column C: material name + entry notes
                if entries:
                    entry = entries[i]
                    elem_text = entry.material_name
                    if entry.notes:
                        elem_text += f" ({entry.notes})"
                    # Append line-item element_notes on the first row
                    if is_first and li.element_notes:
                        elem_text += f" — {li.element_notes}"
                    entry_qty = entry.quantity or ""
                    entry_cost = entry.cost_per_unit or ""
                    entry_total = entry.total_cost or ""
                else:
                    elem_text = li.element_notes or ""
                    entry_qty = li.quantity or ""
                    entry_cost = li.price_per_pc or ""
                    entry_total = ""

                # Template columns:
                #   B = Notes           (first row only)
                #   C = Element w/ notes (per entry)
                #   D = Sq Ft / LF / CY (first row only)
                #   E = $/sf            (first row only)
                #   F = Quantity         (per entry)
                #   G = $/pc             (per entry)
                #   H = Total materials  (per entry)
                #   I = Dump Runs        (first row only)
                #   J = $/dump run       (first row only)
                #   K = Total dump       (first row only)
                #   L = (spacer)
                #   M = Labor Hours      (first row only)
                #   N = Total Labor Cost (first row only)
                #   O = Total element    (first row only)
                #   P = Total Mat Cost   (first row only)
                #   Q = Total Labor Cost (first row only)
                row_values = [
                    li.notes if is_first else "",                        # B
                    elem_text,                                           # C
                    (li.sq_ft or "") if is_first else "",                # D
                    (li.price_per_sf or "") if is_first else "",         # E
                    entry_qty,                                           # F
                    entry_cost,                                          # G
                    entry_total,                                         # H
                    (li.dump_runs or "") if is_first else "",            # I
                    li.dump_cost(cost_config) if is_first else "",       # J
                    li.dump_cost(cost_config) if is_first else "",       # K
                    "",                                                  # L
                    (li.labor_hours or "") if is_first else "",          # M
                    li.labor_cost(cost_config) if is_first else "",      # N
                    li.total_element_price(cost_config) if is_first else "",  # O
                    li.materials_total(cost_config) if is_first else "",      # P
                    li.labor_cost(cost_config) if is_first else "",           # Q
                ]

                updates.append({
                    "range": f"B{r}:Q{r}",
                    "values": [row_values],
                })

            offset += num_rows - 1

        # ---- Apply all updates in one batch call ----
        if updates:
            new_ws.batch_update(updates, value_input_option="USER_ENTERED")

        return f"{spreadsheet.url}#gid={new_ws.id}"


def _parse_float(value: str) -> float:
    """Safely parse a string to float, returning 0.0 on failure."""
    try:
        cleaned = value.replace("$", "").replace(",", "").strip()
        return float(cleaned) if cleaned else 0.0
    except (ValueError, TypeError):
        return 0.0


def _parse_price_range(value: str) -> tuple[float, float | None, float | None]:
    """Parse a price cell that may contain a range like '10-20'.

    Returns:
        (default_value, min_value, max_value)
        - default_value: single numeric value used as the default unit price.
          For ranges, this is the midpoint between min and max.
        - min_value / max_value: None if the cell is not a range.
    """
    if not value:
        return 0.0, None, None

    # Normalize common formatting
    cleaned = (
        value.replace("$", "")
        .replace(",", "")
        .replace("–", "-")  # en dash → hyphen
        .strip()
    )

    # Attempt to detect a range "min-max"
    if "-" in cleaned:
        parts = [p.strip() for p in cleaned.split("-") if p.strip()]
        if len(parts) >= 2:
            try:
                v1 = float(parts[0])
                v2 = float(parts[1])
            except (ValueError, TypeError):
                # Fall back to best-effort single float
                single = _parse_float(cleaned)
                return single, None, None

            lo, hi = sorted((v1, v2))
            midpoint = (lo + hi) / 2.0
            return midpoint, lo, hi

    # Not a range; parse as a single float
    single_val = _parse_float(cleaned)
    return single_val, None, None

