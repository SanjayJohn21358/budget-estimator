"""Text description mode UI — LLM-powered project interpretation.

Results are ADDITIVE: generated items are merged into the existing cart
so the user can combine text-generated items with manually-added ones.
"""

from __future__ import annotations

import streamlit as st

from config import CostConfig, LLMConfig
from models import LineItem, PricingGuide, ProjectEstimate
from services.estimator import EstimatorService
from services.llm import LLMService


def _save(estimate: ProjectEstimate) -> None:
    st.session_state["estimate"] = estimate.model_dump()


def _merge_into_existing(
    existing: ProjectEstimate,
    generated: ProjectEstimate,
) -> ProjectEstimate:
    """Merge generated line items into the existing estimate (additive).

    For each line item in the generated estimate:
      - If a matching section exists in the existing estimate, append entries.
      - If not, create a new line item section.
    Labor hours and dump runs are summed.
    """
    existing_map: dict[str, LineItem] = {
        li.name.lower(): li for li in existing.line_items
    }

    for gen_li in generated.line_items:
        key = gen_li.name.lower()
        if key in existing_map:
            target = existing_map[key]
            target.entries.extend(gen_li.entries)
            target.labor_hours += gen_li.labor_hours
            target.dump_runs += gen_li.dump_runs
            if gen_li.sq_ft:
                target.sq_ft += gen_li.sq_ft
        else:
            existing.line_items.append(gen_li)
            existing_map[key] = gen_li

    return existing


def render_text_mode(
    estimate: ProjectEstimate,
    pricing_guide: PricingGuide,
    config: CostConfig,
    llm_config: LLMConfig,
    line_item_names: list[str],
) -> ProjectEstimate:
    """Render the text-description UI and return an updated estimate."""

    st.subheader("✍️ Describe Your Project")
    st.caption(
        "Write a natural-language description of the project. "
        "The AI will interpret it and **add** the items to your existing cart."
    )

    description = st.text_area(
        "Project Description",
        height=200,
        placeholder=(
            "Example: Install 200 sq ft of Kurapia lawn with gopher wire "
            "underneath, 50 linear ft of black steel edging, remove existing "
            "shrubs (2 dump runs), and mulch 300 sq ft with 3 inches of bark."
        ),
        key="project_description",
    )

    col1, col2 = st.columns([1, 3])
    generate = col1.button("🚀 Generate Estimate", type="primary")

    if not llm_config.openai_api_key:
        st.warning(
            "⚠️ OpenAI API key not configured. "
            "Add it to `.streamlit/secrets.toml` under `[llm]` → `openai_api_key`."
        )
        return estimate

    if generate and description.strip():
        with st.spinner("Interpreting your description…"):
            llm_service = LLMService(llm_config)
            result = llm_service.interpret_description(
                description=description.strip(),
                pricing_guide=pricing_guide,
                line_item_names=line_item_names,
            )

        # Show warnings
        warnings = result.get("warnings", [])
        if warnings:
            st.warning(
                "⚠️ The AI flagged the following:\n"
                + "\n".join(f"- {w}" for w in warnings)
            )

        # Build estimate from LLM output
        items = result.get("items", [])
        if items:
            estimator = EstimatorService(config, pricing_guide)
            generated = estimator.build_estimate_from_llm(
                llm_items=items,
                line_item_names=line_item_names,
                address=estimate.address,
                budget=estimate.project_budget,
                access_level=estimate.access_level,
            )
            # MERGE into existing cart (additive)
            estimate = _merge_into_existing(estimate, generated)
            _save(estimate)

            st.success(
                f"✅ Added {len(items)} item(s) to your cart from the description. "
                "Switch to the **Interactive Menu** or **Output** tab to review."
            )
        else:
            st.error(
                "The AI could not extract any items from your description. "
                "Try being more specific."
            )

    elif generate and not description.strip():
        st.error("Please enter a project description first.")

    # Show current cart count for context
    total_items = sum(len(li.entries) for li in estimate.line_items)
    if total_items > 0:
        st.info(f"🛒 Your cart currently has **{total_items}** item(s). New items will be added to the existing cart.")

    return estimate
