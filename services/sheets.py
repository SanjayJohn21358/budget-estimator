"""Google Sheets integration service."""

from __future__ import annotations

import re
from typing import Any

import gspread
import streamlit as st
from google.oauth2.service_account import Credentials

from config import CostConfig, SheetConfig
from models import (
    AREA_HINTS,
    LINEAR_HINTS,
    LineItem,
    LineItemEntry,
    Material,
    PricingGuide,
    ProjectEstimate,
)


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

            unit_hint = _detect_unit_hint(notes)

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
    # Import: list & load previously saved estimates
    # ------------------------------------------------------------------

    _ESTIMATE_TAB_PREFIX = "Estimate - "

    def list_saved_estimates(self) -> list[dict[str, Any]]:
        """Return tabs in the estimates workbook that look like exported estimates.

        Only tabs whose title starts with ``"Estimate - "`` are included
        (matching the naming convention used by ``export_estimate_to_sheet``).
        Results are sorted most-recent-first (reverse alphabetical, since
        titles end with a date).
        """
        target_id = (
            self._config.estimates_sheet_id
            or self._config.output_template_sheet_id
        )
        if not target_id:
            return []

        client = self._get_client()
        spreadsheet = client.open_by_key(target_id)

        results: list[dict[str, Any]] = []
        for ws in spreadsheet.worksheets():
            if ws.title.startswith(self._ESTIMATE_TAB_PREFIX):
                results.append({"title": ws.title, "gid": ws.id})

        results.sort(key=lambda d: d["title"], reverse=True)
        return results

    def import_estimate_from_sheet(
        self,
        tab_title: str,
        pricing_guide: PricingGuide | None = None,
    ) -> ProjectEstimate:
        """Read a previously exported estimate tab and reconstruct a ProjectEstimate.

        Args:
            tab_title: Name of the worksheet tab to import.
            pricing_guide: If provided, used to resolve ``unit_hint`` for
                materials so area/linear entries are reconstructed accurately.

        Returns:
            A fully populated ``ProjectEstimate`` with
            ``use_dynamic_pricing=False`` on every entry (prices are preserved
            from the sheet).
        """
        target_id = (
            self._config.estimates_sheet_id
            or self._config.output_template_sheet_id
        )
        if not target_id:
            raise ValueError("No estimates sheet ID configured.")

        client = self._get_client()
        spreadsheet = client.open_by_key(target_id)
        ws = spreadsheet.worksheet(tab_title)
        all_rows: list[list[str]] = ws.get_all_values()

        if len(all_rows) < 4:
            raise ValueError(
                f"Tab '{tab_title}' has fewer than 4 rows — "
                "it doesn't look like an exported estimate."
            )

        # ---- Header (row 2, 0-indexed row 1) ----
        header_row = all_rows[1] if len(all_rows) > 1 else []
        while len(header_row) < 10:
            header_row.append("")

        address = header_row[0].strip()                    # A2
        budget = _parse_float(header_row[2])               # C2
        easy_flag = header_row[4].strip().upper()          # E2
        medium_flag = header_row[6].strip() if len(header_row) > 6 else ""  # G2
        medium_flag = medium_flag.upper()

        if medium_flag == "TRUE":
            access_level = "Medium"
        elif easy_flag == "TRUE":
            access_level = "Easy"
        else:
            access_level = "Difficult"

        # ---- Data rows (row 4+, 0-indexed row 3+) ----
        data_rows = all_rows[3:]
        line_items: list[LineItem] = []
        sections: list[str] = []
        current_li: LineItem | None = None
        current_section: str = ""

        for row in data_rows:
            while len(row) < 17:
                row.append("")

            li_name = row[0].strip()        # A – line item name
            notes_col = row[1].strip()      # B – section name / notes
            elem_col = row[2].strip()       # C – element w/ notes
            area_raw = row[3].strip()       # D – Sq Ft / LF / CY
            area_price_raw = row[4].strip() # E – $/sf
            qty_raw = row[5].strip()        # F – Quantity
            pc_price_raw = row[6].strip()   # G – $/pc
            dump_raw = row[8].strip()       # I – Dump Runs
            labor_raw = row[12].strip()     # M – Labor Hours

            # Detect section header: column A has text, columns C-G are empty
            if li_name and not any([elem_col, area_raw, area_price_raw, qty_raw, pc_price_raw]):
                # Check it's not a regular line item (those also have C-G empty
                # on the first row, but have notes or dump data alongside).
                # A section header row is standalone — B column is also empty.
                if not notes_col and not dump_raw:
                    current_section = li_name
                    if current_section not in sections:
                        sections.append(current_section)
                    continue

            # New line-item group when column A has a value
            if li_name:
                current_li = LineItem(
                    name=li_name,
                    section=current_section,
                )
                if notes_col:
                    current_li.notes = notes_col
                if dump_raw:
                    current_li.dump_runs = int(_parse_float(dump_raw))
                line_items.append(current_li)

            if current_li is None:
                continue

            # Skip rows with no element data
            if not elem_col:
                continue

            mat_name, entry_notes, elem_desc = _parse_element_text(elem_col)

            if elem_desc and not current_li.element_notes:
                current_li.element_notes = elem_desc

            area_val = _parse_float(area_raw)
            area_price = _parse_float(area_price_raw)
            qty_val = _parse_float(qty_raw)
            pc_price = _parse_float(pc_price_raw)
            labor_hrs = _parse_float(labor_raw)

            hint = ""
            mat_category = ""
            if pricing_guide and mat_name:
                mat = pricing_guide.get_material_by_name(mat_name)
                if mat:
                    hint = mat.unit_hint or ""
                    mat_category = mat.category or ""

            entry = _build_entry_from_columns(
                mat_name=mat_name,
                category=mat_category,
                entry_notes=entry_notes,
                area_val=area_val,
                area_price=area_price,
                qty_val=qty_val,
                pc_price=pc_price,
                hint=hint,
                labor_hours=labor_hrs,
            )
            current_li.entries.append(entry)

        # Assign orphan line items to a default section
        if not sections:
            sections.append("GENERAL")
        for li in line_items:
            if not li.section:
                li.section = sections[0]

        return ProjectEstimate(
            address=address,
            project_budget=budget,
            access_level=access_level,
            sections=sections,
            line_items=line_items,
        )

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

        # ---- Build all output rows sequentially (header info + data) ----
        updates: list[dict[str, Any]] = []

        # Project info in the header area (row 2)
        updates.append({"range": "A2", "values": [[estimate.address]]})
        updates.append({"range": "B2", "values": [[estimate.grand_total(cost_config)]]})
        updates.append({"range": "C2", "values": [[estimate.project_budget]]})
        updates.append({
            "range": "E2",
            "values": [[estimate.access_level == "Easy"]],
        })
        updates.append({
            "range": "G2",
            "values": [[estimate.access_level == "Medium"]],
        })

        # ---- Write line-item data starting at row 4 ----
        # Columns: A=Line Item, B=Notes, C=Element, D=SqFt/LF, E=$/sf,
        #          F=Qty, G=$/pc, H=Total, I=Dump Runs, J=Dump$, K=DumpTotal,
        #          L=(spacer), M=Labor Hrs, N=Labor$, O=Element Total,
        #          P=Mat Total, Q=Labor Total, R=Total Line Item Price,
        #          S=(spacer), T=Project Estimate
        r = 4
        section_header_rows: list[int] = []
        current_section = ""
        first_data_row: int | None = None

        for li in estimate.line_items:
            if not (li.entries or li.labor_hours > 0 or li.dump_runs > 0):
                continue

            # Section header row
            if li.section and li.section != current_section:
                current_section = li.section
                updates.append({
                    "range": f"A{r}",
                    "values": [[current_section.upper()]],
                })
                section_header_rows.append(r)
                r += 1

            entries = li.entries
            num_rows = max(len(entries), 1)

            for i in range(num_rows):
                is_first = i == 0

                if entries:
                    entry = entries[i]
                    elem_text = entry.material_name
                    if entry.notes:
                        elem_text += f" ({entry.notes})"
                    if is_first and li.element_notes:
                        elem_text += f" — {li.element_notes}"

                    if entry.length_feet and entry.length_feet > 0:
                        entry_area = entry.quantity * entry.length_feet
                        entry_area_price = entry.cost_per_unit
                        entry_qty = entry.quantity if entry.quantity > 0 else ""
                        entry_cost = ""
                    elif entry.area_value > 0:
                        entry_area = entry.area_value
                        entry_area_price = entry.price_per_area
                        entry_qty = entry.quantity if entry.quantity > 0 else ""
                        entry_cost = entry.cost_per_unit if entry.cost_per_unit > 0 else ""
                    else:
                        entry_area = ""
                        entry_area_price = ""
                        entry_qty = entry.quantity or ""
                        entry_cost = entry.cost_per_unit or ""
                    entry_total = entry.total_cost or ""
                else:
                    elem_text = li.element_notes or ""
                    entry_area = li.sq_ft or ""
                    entry_area_price = li.price_per_sf or ""
                    entry_qty = li.quantity or ""
                    entry_cost = li.price_per_pc or ""
                    entry_total = ""

                entry_labor = entry.labor_hours if entries else 0.0
                if is_first:
                    entry_labor += li.labor_hours

                row_values = [
                    li.name if is_first else "",                             # A
                    li.notes if is_first else "",                             # B
                    elem_text,                                               # C
                    entry_area,                                              # D
                    entry_area_price,                                        # E
                    entry_qty,                                               # F
                    entry_cost,                                              # G
                    entry_total,                                             # H
                    (li.dump_runs or "") if is_first else "",                # I
                    li.dump_cost(cost_config) if is_first else "",           # J
                    li.dump_cost(cost_config) if is_first else "",           # K
                    "",                                                      # L
                    entry_labor or "",                                        # M
                    li.labor_cost(cost_config) if is_first else "",          # N
                    li.total_element_price(cost_config) if is_first else "", # O
                    li.materials_total(cost_config) if is_first else "",     # P
                    li.labor_cost(cost_config) if is_first else "",          # Q
                    li.total_element_price(cost_config) if is_first else "", # R
                    "",                                                      # S
                ]

                # Column T: project estimate grand total on the very first data row
                is_first_data_row = first_data_row is None
                if is_first_data_row:
                    first_data_row = r
                    row_values.append(estimate.grand_total(cost_config))     # T
                else:
                    row_values.append("")                                    # T

                updates.append({
                    "range": f"A{r}:T{r}",
                    "values": [row_values],
                })
                r += 1

        # ---- Apply all updates in one batch call ----
        if updates:
            new_ws.batch_update(updates, value_input_option="USER_ENTERED")

        # ---- Bold-format section header rows ----
        for hdr_row in section_header_rows:
            new_ws.format(
                f"A{hdr_row}:Q{hdr_row}",
                {"textFormat": {"bold": True}},
            )

        return f"{spreadsheet.url}#gid={new_ws.id}"


# Patterns that map notes text to a canonical unit hint.  Checked in order;
# the first match wins.  Each tuple is (compiled regex, hint string).
_UNIT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bcu\.?\s*ft\.?\b"), "cuft"),   # cu.ft., cu ft, cuft
    (re.compile(r"\bcu\.?\s*yd\.?\b"), "cuyd"),    # cu.yd., cu yd, cuyd
    (re.compile(r"\bcy\b"), "cuyd"),               # CY shorthand
    (re.compile(r"\bsf\b"), "sf"),                 # sf, SF
    (re.compile(r"\bsq\.?\s*ft\.?\b"), "sf"),      # sq ft, sq.ft.
    (re.compile(r"\byd\b"), "yd"),                  # yd (linear yard)
    (re.compile(r"\bft\b"), "ft"),                  # ft
    (re.compile(r"\blf\b"), "ft"),                  # LF (linear foot)
]


def _detect_unit_hint(notes: str) -> str:
    """Derive a canonical unit hint from the notes column.

    Returns one of: "ft", "sf", "yd", "cuft", "cuyd", or "" (unknown).
    """
    if not notes:
        return ""
    text = notes.lower()
    for pattern, hint in _UNIT_PATTERNS:
        if pattern.search(text):
            return hint
    return ""


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


def _parse_element_text(text: str) -> tuple[str, str, str]:
    """Split an Element w/ Notes cell back into (material_name, notes, section_desc).

    The export format is: ``"Material Name (notes) — section desc"``.
    """
    section_desc = ""
    if " — " in text:
        text, section_desc = text.split(" — ", 1)
        section_desc = section_desc.strip()

    notes = ""
    if " (" in text and text.endswith(")"):
        idx = text.rindex(" (")
        notes = text[idx + 2 : -1].strip()
        text = text[:idx].strip()

    mat_name = text.strip()
    return mat_name, notes, section_desc


def _build_entry_from_columns(
    *,
    mat_name: str,
    category: str,
    entry_notes: str,
    area_val: float,
    area_price: float,
    qty_val: float,
    pc_price: float,
    hint: str,
    labor_hours: float = 0.0,
) -> LineItemEntry:
    """Reconstruct a LineItemEntry from the template column values.

    Detection logic:
    - If the pricing guide says the material is linear (hint in LINEAR_HINTS)
      and both area and qty are present: linear entry (length = area / qty).
    - If area > 0 and no linear hint: area entry.
    - Otherwise: piece entry.
    """
    if hint in LINEAR_HINTS and area_val > 0 and qty_val > 0:
        length = area_val / qty_val if qty_val else 0.0
        return LineItemEntry(
            material_name=mat_name,
            category=category,
            cost_per_unit=area_price,
            quantity=qty_val,
            length_feet=length,
            unit_hint=hint,
            notes=entry_notes,
            labor_hours=labor_hours,
            use_dynamic_pricing=False,
        )

    if area_val > 0 and area_price > 0:
        return LineItemEntry(
            material_name=mat_name,
            category=category,
            area_value=area_val,
            price_per_area=area_price,
            quantity=qty_val if qty_val > 0 else 0.0,
            cost_per_unit=pc_price if pc_price > 0 else 0.0,
            unit_hint=hint or "",
            notes=entry_notes,
            labor_hours=labor_hours,
            use_dynamic_pricing=False,
        )

    return LineItemEntry(
        material_name=mat_name,
        category=category,
        quantity=qty_val,
        cost_per_unit=pc_price,
        unit_hint=hint or "",
        notes=entry_notes,
        labor_hours=labor_hours,
        use_dynamic_pricing=False,
    )

