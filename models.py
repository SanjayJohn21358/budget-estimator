"""Pydantic data models for the Budget Estimator app."""

from __future__ import annotations

from typing import Optional

import pandas as pd
from pydantic import BaseModel, Field, computed_field

from config import CostConfig


# ---------------------------------------------------------------------------
# Pricing Guide models
# ---------------------------------------------------------------------------


class Material(BaseModel):
    """A single material row from the pricing guide sheet."""

    name: str
    category: str = ""
    cost: float = 0.0
    cost_with_tax: float = 0.0
    retail: float = 0.0
    retail_with_tax: float = 0.0
    notes: str = ""
    vendor: str = ""
    price_updated_on: str = ""

    def display_label(self) -> str:
        """Human-readable label for dropdowns."""
        parts = [self.name]
        if self.notes:
            parts.append(f"({self.notes})")
        parts.append(f"— ${self.cost_with_tax:.2f}")
        return " ".join(parts)


class PricingGuide(BaseModel):
    """Parsed pricing guide containing materials grouped by category."""

    categories: dict[str, list[Material]] = Field(default_factory=dict)

    @property
    def all_materials(self) -> list[Material]:
        """Flat list of every material across all categories."""
        return [m for mats in self.categories.values() for m in mats]

    def get_material_by_name(self, name: str) -> Optional[Material]:
        """Case-insensitive lookup by material name."""
        name_lower = name.lower().strip()
        for mat in self.all_materials:
            if mat.name.lower().strip() == name_lower:
                return mat
        return None

    def search_materials(self, query: str) -> list[Material]:
        """Search materials whose name contains the query (case-insensitive)."""
        q = query.lower().strip()
        return [m for m in self.all_materials if q in m.name.lower()]

    def list_all_names(self) -> list[str]:
        """Return a list of all material names."""
        return [m.name for m in self.all_materials]

    def to_prompt_text(self) -> str:
        """Build a text representation for LLM prompt injection."""
        lines: list[str] = []
        for category, materials in self.categories.items():
            lines.append(f"\n## {category}")
            for mat in materials:
                parts = [f"  - {mat.name}: cost=${mat.cost_with_tax:.2f}"]
                if mat.notes:
                    parts.append(f"(notes: {mat.notes})")
                if mat.vendor:
                    parts.append(f"[vendor: {mat.vendor}]")
                lines.append(" ".join(parts))
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Estimate / output models
# ---------------------------------------------------------------------------


class LineItemEntry(BaseModel):
    """A single material selection within a line item."""

    material_name: str = ""
    category: str = ""
    cost_per_unit: float = 0.0
    quantity: float = 0.0
    notes: str = ""

    @computed_field  # type: ignore[misc]
    @property
    def total_cost(self) -> float:
        """Total cost for this entry = cost × quantity."""
        return round(self.cost_per_unit * self.quantity, 2)


class LineItem(BaseModel):
    """One row / section in the output estimate (e.g. 'Fence', 'Plants')."""

    name: str
    notes: str = ""
    element_notes: str = ""
    entries: list[LineItemEntry] = Field(default_factory=list)

    # Area / quantity fields (may be filled directly or aggregated)
    sq_ft: float = 0.0
    price_per_sf: float = 0.0
    quantity: float = 0.0
    price_per_pc: float = 0.0

    # Dump runs
    dump_runs: int = 0

    # Labor
    labor_hours: float = 0.0

    def materials_total(self, config: CostConfig) -> float:
        """Sum of all material entry costs."""
        _ = config  # available for future adjustments
        if self.entries:
            return round(sum(e.total_cost for e in self.entries), 2)
        # Fallback: direct fields
        by_sf = self.sq_ft * self.price_per_sf
        by_pc = self.quantity * self.price_per_pc
        return round(by_sf + by_pc, 2)

    def dump_cost(self, config: CostConfig) -> float:
        """Total dump run cost."""
        return round(self.dump_runs * config.dump_run_cost, 2)

    def labor_cost(self, config: CostConfig) -> float:
        """Total labor cost = hours × rate × crew_size."""
        return round(
            self.labor_hours * config.labor_rate_per_hour * config.crew_size, 2
        )

    def total_element_price(self, config: CostConfig) -> float:
        """Materials + dump + labor."""
        return round(
            self.materials_total(config)
            + self.dump_cost(config)
            + self.labor_cost(config),
            2,
        )


class ProjectEstimate(BaseModel):
    """The full project estimation output."""

    address: str = ""
    project_budget: float = 0.0
    access_level: str = "Easy"
    line_items: list[LineItem] = Field(default_factory=list)

    def total_materials_cost(self, config: CostConfig) -> float:
        return round(sum(li.materials_total(config) for li in self.line_items), 2)

    def total_labor_cost(self, config: CostConfig) -> float:
        return round(sum(li.labor_cost(config) for li in self.line_items), 2)

    def total_dump_cost(self, config: CostConfig) -> float:
        return round(sum(li.dump_cost(config) for li in self.line_items), 2)

    def grand_total(self, config: CostConfig) -> float:
        return round(
            self.total_materials_cost(config)
            + self.total_labor_cost(config)
            + self.total_dump_cost(config),
            2,
        )

    @computed_field  # type: ignore[misc]
    @property
    def project_estimate_total(self) -> float:
        """Quick total using default config (for serialization)."""
        cfg = CostConfig()
        return self.grand_total(cfg)

    def budget_delta(self, config: CostConfig) -> float:
        """Positive = under budget, negative = over budget."""
        return round(self.project_budget - self.grand_total(config), 2)

    def to_summary_dataframe(self, config: CostConfig) -> pd.DataFrame:
        """Build a summary DataFrame with one row per material entry."""
        rows: list[dict] = []
        labor_col = (
            f"Labor Cost (${config.labor_rate_per_hour:.0f}/hr × {config.crew_size})"
        )
        dump_col = f"${config.dump_run_cost:.0f}/dump run"

        for li in self.line_items:
            entries = li.entries if li.entries else [None]  # type: ignore[list-item]
            for i, entry in enumerate(entries):
                is_first = i == 0

                # Element w/ Notes: material name + entry notes
                if entry is not None:
                    elem_text = entry.material_name
                    if entry.notes:
                        elem_text += f" ({entry.notes})"
                    if is_first and li.element_notes:
                        elem_text += f" — {li.element_notes}"
                else:
                    elem_text = li.element_notes or ""

                rows.append(
                    {
                        "Line Item": li.name if is_first else "",
                        "Notes": li.notes if is_first else "",
                        "Element w/ Notes": elem_text,
                        "Sq Ft / LF / CY": li.sq_ft if is_first else "",
                        "$/sf": li.price_per_sf if is_first else "",
                        "Quantity": entry.quantity if entry else (li.quantity if is_first else ""),
                        "$/pc": entry.cost_per_unit if entry else (li.price_per_pc if is_first else ""),
                        "Total": entry.total_cost if entry else "",
                        "Dump Runs": li.dump_runs if is_first else "",
                        dump_col: li.dump_cost(config) if is_first else "",
                        "Dump Total": li.dump_cost(config) if is_first else "",
                        "Labor Hours": li.labor_hours if is_first else "",
                        labor_col: li.labor_cost(config) if is_first else "",
                        "Total Element Price": li.total_element_price(config) if is_first else "",
                        "Total Materials Cost": li.materials_total(config) if is_first else "",
                        "Total Labor Cost": li.labor_cost(config) if is_first else "",
                    }
                )
        return pd.DataFrame(rows)

