"""Landscaping Budget Estimator — Streamlit app entry point."""

from __future__ import annotations

import streamlit as st

from config import AppConfig, CostConfig, LLMConfig, SheetConfig
from models import LineItem, PricingGuide, ProjectEstimate
from services.estimator import EstimatorService
from services.sheets import SheetsService
from ui.interactive import render_interactive_mode
from ui.output import render_output
from ui.text_mode import render_text_mode


# ---------------------------------------------------------------------------
# Config loading (reads from env / secrets)
# ---------------------------------------------------------------------------


def _load_configs() -> tuple[AppConfig, SheetConfig, CostConfig, LLMConfig]:
    """Instantiate all config objects, pulling from Streamlit secrets."""
    sheet_kwargs: dict = {}
    cost_kwargs: dict = {}
    llm_kwargs: dict = {}

    if "sheets" in st.secrets:
        sec = st.secrets["sheets"]
        sheet_kwargs = {
            "pricing_guide_sheet_id": sec.get("pricing_guide_sheet_id", ""),
            "output_template_sheet_id": sec.get("output_template_sheet_id", ""),
            "pricing_guide_tab_name": sec.get("pricing_guide_tab_name", "Sheet1"),
            "output_template_tab_name": sec.get(
                "output_template_tab_name", "Sheet1"
            ),
            "estimates_sheet_id": sec.get("estimates_sheet_id", ""),
        }

    if "costs" in st.secrets:
        sec = st.secrets["costs"]
        for key in (
            "dump_run_cost",
            "labor_rate_per_hour",
            "crew_size",
            "plant_delivery_pct",
            "tax_rate",
        ):
            if key in sec:
                cost_kwargs[key] = sec[key]

    if "llm" in st.secrets:
        sec = st.secrets["llm"]
        llm_kwargs = {
            "openai_api_key": sec.get("openai_api_key", ""),
            "model_name": sec.get("model_name", "gpt-4o"),
            "temperature": sec.get("temperature", 0.2),
        }

    return (
        AppConfig(),
        SheetConfig(**sheet_kwargs),
        CostConfig(**cost_kwargs),
        LLMConfig(**llm_kwargs),
    )


# ---------------------------------------------------------------------------
# Data loading (cached)
# ---------------------------------------------------------------------------


@st.cache_data(ttl=300, show_spinner="Loading pricing guide…")
def _load_pricing_guide(_sheet_config: SheetConfig) -> PricingGuide:
    service = SheetsService(_sheet_config)
    return service.load_pricing_guide()


@st.cache_data(ttl=300, show_spinner="Loading template…")
def _load_template_line_items(_sheet_config: SheetConfig) -> list[str]:
    service = SheetsService(_sheet_config)
    return service.load_template_line_items()


# ---------------------------------------------------------------------------
# Session state helpers
# ---------------------------------------------------------------------------


def _get_estimate(line_item_names: list[str]) -> ProjectEstimate:
    """Retrieve or create the ProjectEstimate in session state."""
    if "estimate" in st.session_state:
        try:
            return ProjectEstimate.model_validate(st.session_state["estimate"])
        except Exception:
            pass
    return _new_estimate(line_item_names)


def _new_estimate(line_item_names: list[str]) -> ProjectEstimate:
    """Create a fresh empty estimate and persist it."""
    est = ProjectEstimate(
        line_items=[LineItem(name=name) for name in line_item_names],
    )
    st.session_state["estimate"] = est.model_dump()
    return est


def _save_estimate(estimate: ProjectEstimate) -> None:
    st.session_state["estimate"] = estimate.model_dump()


# ---------------------------------------------------------------------------
# Button callbacks (run BEFORE the rerun, so state is correct on next render)
# ---------------------------------------------------------------------------


def _on_refresh_prices() -> None:
    """Clear all cached sheet data so the next render fetches fresh data."""
    st.cache_data.clear()
    st.toast("♻️ Refreshing pricing data from Google Sheets…")


def _on_reset_cart() -> None:
    """Wipe the estimate from session state; it will be recreated on rerun."""
    if "estimate" in st.session_state:
        del st.session_state["estimate"]
    st.toast("🗑️ Cart cleared!")


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------


def main() -> None:
    app_cfg, sheet_cfg, cost_cfg, llm_cfg = _load_configs()

    st.set_page_config(
        page_title=app_cfg.app_title,
        page_icon="🌿",
        layout="wide",
    )
    st.title(f"🌿 {app_cfg.app_title}")

    # ---- Check configuration ----
    if not sheet_cfg.pricing_guide_sheet_id:
        st.error(
            "⚠️ **Pricing Guide Sheet ID not configured.** "
            "Add it to `.streamlit/secrets.toml` under `[sheets]` "
            "→ `pricing_guide_sheet_id`."
        )
        st.stop()

    # ---- Load data ----
    pricing_guide = _load_pricing_guide(sheet_cfg)

    if sheet_cfg.output_template_sheet_id:
        line_item_names = _load_template_line_items(sheet_cfg)
    else:
        line_item_names = app_cfg.default_line_items
    if not line_item_names:
        line_item_names = app_cfg.default_line_items

    # ---- Sidebar ----
    with st.sidebar:
        st.header("Project Info")
        address = st.text_input("Address", key="address")
        budget = st.number_input(
            "Project Budget ($)", min_value=0.0, step=100.0, key="budget"
        )
        access = st.selectbox(
            "Site Access", options=app_cfg.access_levels, key="access"
        )

        st.markdown("---")
        st.header("Cost Settings")
        dump_cost = st.number_input(
            "Dump Run Cost ($)",
            value=cost_cfg.dump_run_cost,
            step=10.0,
            key="dump_cost",
        )
        labor_rate = st.number_input(
            "Labor Rate ($/hr)",
            value=cost_cfg.labor_rate_per_hour,
            step=10.0,
            key="labor_rate",
        )
        crew_size = int(
            st.number_input(
                "Crew Size",
                value=cost_cfg.crew_size,
                min_value=1,
                step=1,
                key="crew_size",
            )
        )

        cost_cfg = CostConfig(
            dump_run_cost=dump_cost,
            labor_rate_per_hour=labor_rate,
            crew_size=crew_size,
            plant_delivery_pct=cost_cfg.plant_delivery_pct,
            tax_rate=cost_cfg.tax_rate,
        )

        # ---- Cart stats + reset ----
        st.markdown("---")
        estimate_peek = _get_estimate(line_item_names)
        cart_count = sum(len(li.entries) for li in estimate_peek.line_items)
        st.caption(
            f"🛒 **{cart_count}** item{'s' if cart_count != 1 else ''} in cart  ·  "
            f"📦 {len(pricing_guide.all_materials)} materials loaded"
        )

        c1, c2 = st.columns(2)
        c1.button("🔄 Refresh Prices", on_click=_on_refresh_prices)
        c2.button("🗑️ Reset Cart", type="secondary", on_click=_on_reset_cart)

    # ---- Get / create estimate & sync sidebar fields ----
    estimate = _get_estimate(line_item_names)
    estimate.address = address  # type: ignore[assignment]
    estimate.project_budget = budget  # type: ignore[assignment]
    estimate.access_level = access  # type: ignore[assignment]

    # ---- Sync cart prices with the (possibly refreshed) pricing guide ----
    estimator = EstimatorService(cost_cfg, pricing_guide)
    estimator.recalculate_estimate(estimate)
    _save_estimate(estimate)

    # ---- Tabs ----
    tab_interactive, tab_text, tab_output = st.tabs(
        ["📋 Interactive Menu", "✍️ Text Description", "📊 Output"]
    )

    with tab_interactive:
        estimate = render_interactive_mode(estimate, pricing_guide, cost_cfg)

    with tab_text:
        estimate = render_text_mode(
            estimate, pricing_guide, cost_cfg, llm_cfg, line_item_names
        )

    with tab_output:
        estimate = render_output(estimate, cost_cfg, sheet_cfg)

    # Final save (catches any remaining in-tab mutations)
    _save_estimate(estimate)


if __name__ == "__main__":
    main()
