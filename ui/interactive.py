"""Interactive menu mode UI — cart-like material picker."""

from __future__ import annotations

import streamlit as st

from config import CostConfig
from models import LineItem, LineItemEntry, PricingGuide, ProjectEstimate


# ---------------------------------------------------------------------------
# Session-state helpers (so mutations persist across reruns)
# ---------------------------------------------------------------------------


def _save(estimate: ProjectEstimate) -> None:
    """Persist estimate to session state immediately."""
    st.session_state["estimate"] = estimate.model_dump()


# ---------------------------------------------------------------------------
# Public render function
# ---------------------------------------------------------------------------


def render_interactive_mode(
    estimate: ProjectEstimate,
    pricing_guide: PricingGuide,
    config: CostConfig,
) -> ProjectEstimate:
    """Render the cart-like interactive material picker."""

    # ---- Add-to-cart section (always visible at top) ----
    st.subheader("➕ Add Items")

    # Category filter
    category_names = list(pricing_guide.categories.keys())
    line_item_names = [li.name for li in estimate.line_items]

    col_cat, col_mat = st.columns(2)

    selected_category = col_cat.selectbox(
        "Material Category",
        options=["All Categories"] + category_names,
        key="add_category",
        help="Filter the material list by category from your pricing guide",
    )

    # Build filtered material list
    if selected_category == "All Categories":
        filtered_materials = pricing_guide.all_materials
    else:
        filtered_materials = pricing_guide.categories.get(selected_category, [])

    material_options = [m.display_label() for m in filtered_materials]
    material_name_map: dict[str, str] = {
        m.display_label(): m.name for m in filtered_materials
    }

    selected_material_label = col_mat.selectbox(
        "Material",
        options=["— Select a material —"] + material_options,
        key="add_material",
        help="Pick a material to add to your estimate",
    )

    col_li, col_qty, col_notes, col_btn = st.columns([2, 1, 2, 1])

    target_line_item = col_li.selectbox(
        "Add to Section",
        options=line_item_names,
        key="add_target_li",
        help="Which line-item section should this go under?",
    )

    new_qty = col_qty.number_input(
        "Quantity",
        min_value=0.01,
        value=1.0,
        step=1.0,
        key="add_qty",
    )

    new_notes = col_notes.text_input(
        "Notes (optional)",
        key="add_notes",
        placeholder="e.g. front yard only",
    )

    # Add button
    col_btn.markdown("<br>", unsafe_allow_html=True)  # vertical alignment hack
    if col_btn.button("🛒 Add to Cart", key="add_to_cart_btn", type="primary"):
        if selected_material_label != "— Select a material —":
            mat_name = material_name_map.get(selected_material_label, "")
            mat = pricing_guide.get_material_by_name(mat_name)
            if mat:
                # Find the target line item
                target_li = next(
                    (li for li in estimate.line_items if li.name == target_line_item),
                    None,
                )
                if target_li:
                    target_li.entries.append(
                        LineItemEntry(
                            material_name=mat.name,
                            category=mat.category,
                            cost_per_unit=mat.cost_with_tax,
                            quantity=new_qty,
                            notes=new_notes,
                        )
                    )
                    _save(estimate)
                    st.rerun()
        else:
            st.warning("Please select a material first.")

    # ---- Cart contents ----
    st.markdown("---")

    # Quick stats
    total_items = sum(len(li.entries) for li in estimate.line_items)
    st.subheader(f"🛒 Your Cart ({total_items} item{'s' if total_items != 1 else ''})")

    if total_items == 0:
        st.info(
            "Your cart is empty. Use the controls above to add materials, "
            "or switch to the **Text Description** tab to generate items from "
            "a project description."
        )

    # Render each line item section
    for li_idx, li in enumerate(estimate.line_items):
        entry_count = len(li.entries)
        section_total = li.total_element_price(config)
        has_content = entry_count > 0 or li.labor_hours > 0 or li.dump_runs > 0

        badge = f" — **${section_total:,.2f}**" if has_content else ""
        label = f"**{li.name}** ({entry_count} item{'s' if entry_count != 1 else ''}){badge}"

        with st.expander(label, expanded=has_content):
            # ---- Material entries table ----
            if li.entries:
                # Header row
                hdr1, hdr2, hdr3, hdr4, hdr5, hdr6 = st.columns(
                    [3, 1.5, 1.2, 1.5, 2, 0.6]
                )
                hdr1.markdown("**Material**")
                hdr2.markdown("**Unit Cost**")
                hdr3.markdown("**Qty**")
                hdr4.markdown("**Subtotal**")
                hdr5.markdown("**Notes**")
                hdr6.markdown("**Del**")

                for e_idx, entry in enumerate(li.entries):
                    c1, c2, c3, c4, c5, c6 = st.columns(
                        [3, 1.5, 1.2, 1.5, 2, 0.6]
                    )
                    c1.write(entry.material_name)
                    c2.write(f"${entry.cost_per_unit:,.2f}")

                    updated_qty = c3.number_input(
                        "Qty",
                        min_value=0.0,
                        value=entry.quantity,
                        step=1.0,
                        key=f"cart_qty_{li_idx}_{e_idx}",
                        label_visibility="collapsed",
                    )
                    if updated_qty != entry.quantity:
                        entry.quantity = updated_qty
                        _save(estimate)

                    c4.write(f"**${entry.total_cost:,.2f}**")
                    c5.write(entry.notes or "—")

                    if c6.button("🗑️", key=f"del_{li_idx}_{e_idx}"):
                        li.entries.pop(e_idx)
                        _save(estimate)
                        st.rerun()

                st.markdown(
                    f"**Materials Subtotal: ${li.materials_total(config):,.2f}**"
                )
            else:
                st.caption("No materials added to this section yet.")

            # ---- Area / piece pricing (direct) ----
            with st.popover("📐 Area / Piece Pricing (advanced)"):
                cp1, cp2 = st.columns(2)
                li.sq_ft = cp1.number_input(
                    "Sq Ft / LF / CY",
                    min_value=0.0,
                    value=li.sq_ft,
                    step=1.0,
                    key=f"sqft_{li_idx}",
                )
                li.price_per_sf = cp2.number_input(
                    "$/sf",
                    min_value=0.0,
                    value=li.price_per_sf,
                    step=0.01,
                    key=f"psf_{li_idx}",
                )
                cp3, cp4 = st.columns(2)
                li.quantity = cp3.number_input(
                    "Quantity (pc)",
                    min_value=0.0,
                    value=li.quantity,
                    step=1.0,
                    key=f"qty_{li_idx}",
                )
                li.price_per_pc = cp4.number_input(
                    "$/pc",
                    min_value=0.0,
                    value=li.price_per_pc,
                    step=0.01,
                    key=f"ppc_{li_idx}",
                )

            # ---- Labor & dump runs ----
            st.markdown("**Labor & Dump Runs**")
            d1, d2, d3, d4 = st.columns(4)
            li.dump_runs = int(
                d1.number_input(
                    "Dump Runs",
                    min_value=0,
                    value=li.dump_runs,
                    step=1,
                    key=f"dump_{li_idx}",
                )
            )
            d2.write(f"Dump cost: **${li.dump_cost(config):,.2f}**")

            li.labor_hours = d3.number_input(
                "Labor Hours",
                min_value=0.0,
                value=li.labor_hours,
                step=0.5,
                key=f"labor_{li_idx}",
            )
            d4.write(f"Labor cost: **${li.labor_cost(config):,.2f}**")

            # ---- Notes ----
            n1, n2 = st.columns(2)
            li.notes = n1.text_input(
                "Section Notes",
                value=li.notes,
                key=f"li_notes_{li_idx}",
            )
            li.element_notes = n2.text_input(
                "Element Notes",
                value=li.element_notes,
                key=f"li_elem_{li_idx}",
            )

    # Save any inline edits (labor, dump, notes, qty changes)
    _save(estimate)

    # ---- Running total footer ----
    st.markdown("---")
    ft1, ft2, ft3, ft4 = st.columns(4)
    ft1.metric("Materials", f"${estimate.total_materials_cost(config):,.2f}")
    ft2.metric("Labor", f"${estimate.total_labor_cost(config):,.2f}")
    ft3.metric("Dump Runs", f"${estimate.total_dump_cost(config):,.2f}")
    ft4.metric("🧾 Grand Total", f"${estimate.grand_total(config):,.2f}")

    return estimate
