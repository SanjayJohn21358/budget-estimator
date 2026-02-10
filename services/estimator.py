"""Core estimation / calculation logic."""

from __future__ import annotations

from config import CostConfig
from models import LineItem, LineItemEntry, Material, PricingGuide, ProjectEstimate


class EstimatorService:
    """Performs calculations and builds estimates."""

    def __init__(self, config: CostConfig, pricing_guide: PricingGuide) -> None:
        self._config = config
        self._pricing = pricing_guide

    # ------------------------------------------------------------------
    # Building helpers
    # ------------------------------------------------------------------

    def create_entry(
        self,
        material_name: str,
        quantity: float,
        notes: str = "",
    ) -> LineItemEntry:
        """Create a LineItemEntry by looking up the material cost."""
        mat = self._pricing.get_material_by_name(material_name)
        cost = mat.cost_with_tax if mat else 0.0
        category = mat.category if mat else ""
        return LineItemEntry(
            material_name=material_name,
            category=category,
            cost_per_unit=cost,
            quantity=quantity,
            notes=notes,
        )

    def build_empty_estimate(
        self,
        line_item_names: list[str],
        address: str = "",
        budget: float = 0.0,
        access_level: str = "Easy",
    ) -> ProjectEstimate:
        """Scaffold an empty ProjectEstimate with the given line items."""
        line_items = [LineItem(name=name) for name in line_item_names]
        return ProjectEstimate(
            address=address,
            project_budget=budget,
            access_level=access_level,
            line_items=line_items,
        )

    # ------------------------------------------------------------------
    # Recalculation
    # ------------------------------------------------------------------

    def recalculate_entry(self, entry: LineItemEntry) -> LineItemEntry:
        """Refresh the cost_per_unit from the pricing guide."""
        mat = self._pricing.get_material_by_name(entry.material_name)
        if mat:
            entry.cost_per_unit = mat.cost_with_tax
        return entry

    def recalculate_line_item(self, li: LineItem) -> LineItem:
        """Recompute derived values for a line item."""
        for entry in li.entries:
            self.recalculate_entry(entry)

        # Aggregate quantity from entries if not set directly
        if li.entries and li.quantity == 0:
            li.quantity = sum(e.quantity for e in li.entries)

        return li

    def recalculate_estimate(self, estimate: ProjectEstimate) -> ProjectEstimate:
        """Recompute all derived values across the full estimate."""
        for li in estimate.line_items:
            self.recalculate_line_item(li)
        return estimate

    # ------------------------------------------------------------------
    # Delivery surcharge
    # ------------------------------------------------------------------

    def apply_plant_delivery(self, estimate: ProjectEstimate) -> ProjectEstimate:
        """Add a plant delivery surcharge entry to the Plants line item."""
        plants_li = next(
            (li for li in estimate.line_items if li.name.lower() == "plants"),
            None,
        )
        if plants_li is None:
            return estimate

        plant_material_total = plants_li.materials_total(self._config)
        if plant_material_total <= 0:
            return estimate

        delivery_cost = round(plant_material_total * self._config.plant_delivery_pct, 2)

        # Remove existing delivery entry if present
        plants_li.entries = [
            e for e in plants_li.entries if e.material_name != "Plant Delivery"
        ]

        plants_li.entries.append(
            LineItemEntry(
                material_name="Plant Delivery",
                category="Plants/Lawn",
                cost_per_unit=delivery_cost,
                quantity=1,
                notes=f"{self._config.plant_delivery_pct:.0%} of plant total",
            )
        )
        return estimate

    # ------------------------------------------------------------------
    # Build estimate from LLM output
    # ------------------------------------------------------------------

    def build_estimate_from_llm(
        self,
        llm_items: list[dict],
        line_item_names: list[str],
        address: str = "",
        budget: float = 0.0,
        access_level: str = "Easy",
    ) -> ProjectEstimate:
        """Build a ProjectEstimate from structured LLM output.

        Args:
            llm_items: List of dicts with keys:
                - line_item: str (category name, e.g. "Fence")
                - material_name: str
                - quantity: float
                - notes: str (optional)
                - sq_ft: float (optional)
                - labor_hours: float (optional)
                - dump_runs: int (optional)
            line_item_names: Ordered list of line item categories.
            address: Project address.
            budget: Project budget.
            access_level: Site access level.

        Returns:
            Fully populated ProjectEstimate.
        """
        estimate = self.build_empty_estimate(
            line_item_names, address, budget, access_level
        )

        # Index line items by lowercase name for lookup
        li_map: dict[str, LineItem] = {
            li.name.lower(): li for li in estimate.line_items
        }

        for item in llm_items:
            li_name = item.get("line_item", "Misc").strip()
            li = li_map.get(li_name.lower())

            # If the LLM gave an unknown category, put it in Misc
            if li is None:
                li = li_map.get("misc")
            if li is None:
                # Create a new line item on the fly
                li = LineItem(name=li_name)
                estimate.line_items.append(li)
                li_map[li_name.lower()] = li

            entry = self.create_entry(
                material_name=item.get("material_name", ""),
                quantity=item.get("quantity", 0),
                notes=item.get("notes", ""),
            )
            li.entries.append(entry)

            # Apply optional aggregate fields
            if "sq_ft" in item:
                li.sq_ft += item["sq_ft"]
            if "labor_hours" in item:
                li.labor_hours += item["labor_hours"]
            if "dump_runs" in item:
                li.dump_runs += item["dump_runs"]

        self.apply_plant_delivery(estimate)
        self.recalculate_estimate(estimate)
        return estimate

