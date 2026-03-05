"""Interactive menu mode UI — cart-like material picker."""

from __future__ import annotations

import streamlit as st

from config import CostConfig
from models import LineItem, LineItemEntry, PricingGuide, ProjectEstimate

# Lumber category check (must match models for length-based pricing)
def _is_lumber(category: str) -> bool:
    return (category or "").strip().lower() == "lumber"


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
    line_item_names: list[str],
) -> ProjectEstimate:
    """Render the cart-like interactive material picker."""

    # ---- Section management ----
    st.subheader("📁 Sections")

    # Section type options come from template names plus any existing section names
    base_section_types = sorted(
        {name for name in line_item_names} | {li.name for li in estimate.line_items}
    ) or sorted(pricing_guide.categories.keys())

    with st.expander("➕ Add Section", expanded=not estimate.line_items):
        col_type, col_name = st.columns(2)
        section_type = col_type.selectbox(
            "Section Type",
            options=base_section_types,
            key="new_section_type",
            help="Choose the base category for this section",
        )
        section_name = col_name.text_input(
            "Section Name (optional)",
            key="new_section_name",
            placeholder="e.g. Front Yard Cleanup",
        )

        section_description = st.text_input(
            "Section Description (optional)",
            key="new_section_description",
            placeholder="Short notes about this section",
        )

        if st.button("Create Section", type="primary", key="create_section_btn"):
            base = section_type.strip() or "Section"
            # Count existing sections of this base type to build a default name
            same_type_count = sum(1 for li in estimate.line_items if li.name == base)
            auto_name = f"{base} {same_type_count + 1}"
            stored_name = section_name.strip() or auto_name

            estimate.line_items.append(
                LineItem(
                    name=base,
                    # Use notes as the human-friendly section name
                    notes=stored_name,
                    # Use element_notes as the description
                    element_notes=section_description.strip(),
                )
            )
            _save(estimate)
            st.rerun()

    if not estimate.line_items:
        st.info("No sections yet. Use **Add Section** above to get started.")
        return estimate

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

    # Precompute category list for item pickers
    category_names = list(pricing_guide.categories.keys())

    # Render each line item section
    type_counters: dict[str, int] = {}
    for li_idx, li in enumerate(estimate.line_items):
        entry_count = len(li.entries)
        section_total = li.total_element_price(config)
        has_content = entry_count > 0 or li.labor_hours > 0 or li.dump_runs > 0

        # Derive a user-friendly display name
        base_type = li.name
        type_counters[base_type] = type_counters.get(base_type, 0) + 1
        ordinal = type_counters[base_type]

        if li.notes:
            display_name = li.notes
            subtitle = f" · {base_type}"
        elif ordinal > 1:
            display_name = f"{base_type} {ordinal}"
            subtitle = ""
        else:
            display_name = base_type
            subtitle = ""

        badge = f" — **${section_total:,.2f}**" if has_content else ""
        label = (
            f"**{display_name}**{subtitle} "
            f"({entry_count} item{'s' if entry_count != 1 else ''}){badge}"
        )

        with st.expander(label, expanded=has_content):
            # ---- Add item to this section ----
            st.markdown("**Add Item to this Section**")

            add_col_cat, add_col_mat = st.columns(2)
            selected_category = add_col_cat.selectbox(
                "Material Category",
                options=["All Categories"] + category_names,
                key=f"cat_{li_idx}",
            )

            if selected_category == "All Categories":
                filtered_materials = pricing_guide.all_materials
            else:
                filtered_materials = pricing_guide.categories.get(
                    selected_category, []
                )

            material_options = [m.display_label() for m in filtered_materials]
            material_name_map: dict[str, str] = {
                m.display_label(): m.name for m in filtered_materials
            }

            selected_material_label = add_col_mat.selectbox(
                "Material",
                options=["— Select a material —"] + material_options,
                key=f"mat_{li_idx}",
                help="Pick a material to add to this section",
            )

            # Detect lumber so we can show length (ft) field
            selected_mat = None
            if selected_material_label != "— Select a material —":
                mat_name = material_name_map.get(selected_material_label, "")
                selected_mat = pricing_guide.get_material_by_name(mat_name)
            is_lumber = selected_mat and _is_lumber(selected_mat.category)

            add_col_qty, add_col_notes, add_col_labor, add_col_btn = st.columns(
                [1, 2, 1, 1]
            )

            new_qty = add_col_qty.number_input(
                "Quantity",
                min_value=0.01,
                value=1.0,
                step=1.0,
                key=f"add_qty_{li_idx}",
            )

            new_notes = add_col_notes.text_input(
                "Notes (optional)",
                key=f"notes_{li_idx}",
                placeholder="e.g. front yard only",
            )

            labor_options = [0.0, 0.5, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0]
            selected_labor = add_col_labor.selectbox(
                "Labor Hours (for this item)",
                options=labor_options,
                key=f"labor_item_{li_idx}",
                help="Labor hours associated with this specific item",
            )

            # Lumber: feet per board (cost = cost_per_unit × quantity × length_feet)
            new_length_feet: float | None = None
            if is_lumber:
                new_length_feet = st.number_input(
                    "Length (ft per board)",
                    min_value=0.01,
                    value=8.0,
                    step=0.5,
                    key=f"add_length_ft_{li_idx}",
                    help="Feet per board; cost = unit price × quantity × length",
                )

            add_col_btn.markdown(
                "<br>", unsafe_allow_html=True
            )  # vertical alignment hack
            if add_col_btn.button(
                "Add Item", key=f"add_item_{li_idx}", type="primary"
            ):
                if selected_material_label != "— Select a material —" and selected_mat:
                    li.entries.append(
                        LineItemEntry(
                            material_name=selected_mat.name,
                            category=selected_mat.category,
                            cost_per_unit=selected_mat.cost_with_tax,
                            quantity=new_qty,
                            notes=new_notes,
                            labor_hours=float(selected_labor),
                            length_feet=new_length_feet if is_lumber else None,
                        )
                    )
                    _save(estimate)
                    st.rerun()
                else:
                    st.warning("Please select a material first.")

            # ---- Material entries table ----
            if li.entries:
                # Header row (Length (ft) for lumber)
                hdr1, hdr2, hdr3, hdr4, hdr5, hdr6, hdr7, hdr8 = st.columns(
                    [3, 1.5, 1.0, 1.0, 1.5, 1.2, 1.6, 0.6]
                )
                hdr1.markdown("**Material**")
                hdr2.markdown("**Unit Cost**")
                hdr3.markdown("**Qty**")
                hdr4.markdown("**Length (ft)**")
                hdr5.markdown("**Subtotal**")
                hdr6.markdown("**Labor Hrs**")
                hdr7.markdown("**Notes**")
                hdr8.markdown("**Del**")

                for e_idx, entry in enumerate(li.entries):
                    is_lumber_entry = _is_lumber(entry.category)
                    c1, c2, c3, c4, c5, c6, c7, c8 = st.columns(
                        [3, 1.5, 1.0, 1.0, 1.5, 1.2, 1.6, 0.6]
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

                    if is_lumber_entry:
                        len_val = entry.length_feet if entry.length_feet is not None else 0.0
                        updated_len = c4.number_input(
                            "Length (ft)",
                            min_value=0.0,
                            value=len_val,
                            step=0.5,
                            key=f"cart_len_{li_idx}_{e_idx}",
                            label_visibility="collapsed",
                        )
                        if updated_len != (entry.length_feet or 0):
                            entry.length_feet = updated_len if updated_len > 0 else None
                            _save(estimate)
                    else:
                        c4.write("—")

                    c5.write(f"**${entry.total_cost:,.2f}**")

                    updated_labor = c6.number_input(
                        "Labor Hrs (item)",
                        min_value=0.0,
                        value=entry.labor_hours,
                        step=0.5,
                        key=f"cart_labor_{li_idx}_{e_idx}",
                        label_visibility="collapsed",
                    )
                    if updated_labor != entry.labor_hours:
                        entry.labor_hours = updated_labor
                        _save(estimate)

                    c7.write(entry.notes or "—")

                    if c8.button("🗑️", key=f"del_{li_idx}_{e_idx}"):
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
            d1, d2, d3 = st.columns(3)
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
            d3.write(f"Labor cost: **${li.labor_cost(config):,.2f}**")

            # ---- Notes ----
            n1, n2 = st.columns(2)
            li.notes = n1.text_input(
                "Section Name",
                value=li.notes,
                key=f"li_notes_{li_idx}",
            )
            li.element_notes = n2.text_input(
                "Section Description",
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
