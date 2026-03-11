"""Interactive menu mode UI — cart-like material picker."""

from __future__ import annotations

import streamlit as st

from config import CostConfig
from models import (
    AREA_HINTS,
    LINEAR_HINTS,
    LineItem,
    LineItemEntry,
    PricingGuide,
    ProjectEstimate,
    unit_label,
)


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

            # Detect unit behavior based on notes-derived hint
            selected_mat = None
            if selected_material_label != "— Select a material —":
                mat_name = material_name_map.get(selected_material_label, "")
                selected_mat = pricing_guide.get_material_by_name(mat_name)
            mat_hint = (
                (getattr(selected_mat, "unit_hint", "") or "").lower()
                if selected_mat is not None
                else ""
            )
            is_linear = mat_hint in LINEAR_HINTS
            is_area = mat_hint in AREA_HINTS

            add_col_qty, add_col_notes, add_col_labor, add_col_btn = st.columns(
                [1, 2, 1, 1]
            )

            qty_label = unit_label(mat_hint) if is_area else "Quantity"
            new_qty = add_col_qty.number_input(
                qty_label,
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

            # Unit price: always allow a custom value, with a sensible default
            chosen_unit_price: float | None = None
            lock_price = False
            if selected_mat is not None:
                sheet_price = float(selected_mat.retail_with_tax or 0.0)
                has_price_range = (
                    selected_mat.retail_with_tax_min is not None
                    and selected_mat.retail_with_tax_max is not None
                )

                if has_price_range:
                    # Default to midpoint of the range (or sheet price if present)
                    lo = float(selected_mat.retail_with_tax_min or 0.0)
                    hi = float(selected_mat.retail_with_tax_max or 0.0)
                    midpoint = sheet_price or (lo + hi) / 2.0
                    default_price = midpoint
                else:
                    default_price = sheet_price

                chosen_unit_price = st.number_input(
                    "Unit Price",
                    min_value=0.0,
                    value=default_price,
                    step=0.5,
                    key=f"price_input_{li_idx}",
                    help="Custom unit price for this material.",
                )

                # Lock the price if it differs from the sheet price or if this
                # material came from a range.
                if has_price_range or chosen_unit_price != sheet_price:
                    lock_price = True

            # Linear-unit materials: length per piece (cost = $/unit × qty × length)
            new_length_feet: float | None = None
            if is_linear:
                length_label = f"Length ({unit_label(mat_hint)} per piece)"
                new_length_feet = st.number_input(
                    length_label,
                    min_value=0.01,
                    value=8.0,
                    step=0.5,
                    key=f"add_length_ft_{li_idx}",
                    help="Length per piece; cost = unit price × quantity × length",
                )

            add_col_btn.markdown(
                "<br>", unsafe_allow_html=True
            )  # vertical alignment hack
            if add_col_btn.button(
                "Add Item", key=f"add_item_{li_idx}", type="primary"
            ):
                if selected_material_label != "— Select a material —" and selected_mat:
                    unit_price = (
                        chosen_unit_price
                        if chosen_unit_price is not None and chosen_unit_price > 0
                        else float(selected_mat.retail_with_tax or 0.0)
                    )

                    if is_area:
                        entry = LineItemEntry(
                            material_name=selected_mat.name,
                            category=selected_mat.category,
                            area_value=new_qty,
                            price_per_area=unit_price,
                            unit_hint=mat_hint,
                            notes=new_notes,
                            labor_hours=float(selected_labor),
                            use_dynamic_pricing=not lock_price,
                        )
                    elif is_linear:
                        entry = LineItemEntry(
                            material_name=selected_mat.name,
                            category=selected_mat.category,
                            cost_per_unit=unit_price,
                            quantity=new_qty,
                            unit_hint=mat_hint,
                            length_feet=new_length_feet,
                            notes=new_notes,
                            labor_hours=float(selected_labor),
                            use_dynamic_pricing=not lock_price,
                        )
                    else:
                        entry = LineItemEntry(
                            material_name=selected_mat.name,
                            category=selected_mat.category,
                            cost_per_unit=unit_price,
                            quantity=new_qty,
                            notes=new_notes,
                            labor_hours=float(selected_labor),
                            use_dynamic_pricing=not lock_price,
                        )
                    li.entries.append(entry)
                    _save(estimate)
                    st.rerun()
                else:
                    st.warning("Please select a material first.")

            # ---- Material entries table ----
            if li.entries:
                _col_w = [2.6, 0.9, 0.8, 0.8, 0.8, 1.1, 0.8, 1.4, 0.5]
                (hdr1, hdr2, hdr3, hdr4, hdr5,
                 hdr6, hdr7, hdr8, hdr9) = st.columns(_col_w)
                hdr1.markdown("**Material**")
                hdr2.markdown("**SqFt/LF**")
                hdr3.markdown("**$/sf**")
                hdr4.markdown("**Qty**")
                hdr5.markdown("**$/pc**")
                hdr6.markdown("**Total**")
                hdr7.markdown("**Labor**")
                hdr8.markdown("**Notes**")
                hdr9.markdown("**Del**")

                for e_idx, entry in enumerate(li.entries):
                    e_hint = entry.unit_hint or ""
                    is_area_entry = e_hint in AREA_HINTS or (
                        entry.area_value > 0 and entry.quantity == 0
                    )
                    has_length = entry.length_feet is not None and entry.length_feet > 0

                    (c1, c2, c3, c4, c5,
                     c6, c7, c8, c9) = st.columns(_col_w)

                    mat_display = entry.material_name
                    if e_hint:
                        mat_display += f"  `{unit_label(e_hint)}`"
                    c1.write(mat_display)

                    # -- Sq Ft / LF / CY column --
                    if is_area_entry:
                        updated_area = c2.number_input(
                            "Area",
                            min_value=0.0,
                            value=entry.area_value,
                            step=1.0,
                            key=f"cart_area_{li_idx}_{e_idx}",
                            label_visibility="collapsed",
                        )
                        if updated_area != entry.area_value:
                            entry.area_value = updated_area
                            _save(estimate)
                    elif has_length:
                        c2.write(f"{entry.quantity * (entry.length_feet or 0):.1f}")
                    else:
                        c2.write("—")

                    # -- $/sf column --
                    if is_area_entry:
                        c3.write(f"${entry.price_per_area:,.2f}")
                    elif has_length:
                        c3.write(f"${entry.cost_per_unit:,.2f}")
                    else:
                        c3.write("—")

                    # -- Qty column --
                    if is_area_entry and not has_length:
                        c4.write("—")
                    else:
                        updated_qty = c4.number_input(
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

                    # -- $/pc column --
                    if not is_area_entry and not has_length:
                        c5.write(f"${entry.cost_per_unit:,.2f}")
                    else:
                        c5.write("—")

                    c6.write(f"**${entry.total_cost:,.2f}**")

                    updated_labor = c7.number_input(
                        "Labor",
                        min_value=0.0,
                        value=entry.labor_hours,
                        step=0.5,
                        key=f"cart_labor_{li_idx}_{e_idx}",
                        label_visibility="collapsed",
                    )
                    if updated_labor != entry.labor_hours:
                        entry.labor_hours = updated_labor
                        _save(estimate)

                    c8.write(entry.notes or "—")

                    if c9.button("🗑️", key=f"del_{li_idx}_{e_idx}"):
                        li.entries.pop(e_idx)
                        _save(estimate)
                        st.rerun()

                st.markdown(
                    f"**Materials Subtotal: ${li.materials_total(config):,.2f}**"
                )
            else:
                st.caption("No materials added to this section yet.")

            # ---- Custom Area / Piece materials (no section-level pricing) ----
            with st.popover("📐 Area / Piece Pricing (advanced)"):
                st.markdown("**Custom Material (Area / Piece)**")

                # Custom material definition: lets users create ad-hoc materials
                # that behave like normal entries in this section.
                cm1, cm2 = st.columns(2)
                custom_name = cm1.text_input(
                    "Custom Material Name",
                    key=f"custom_mat_name_{li_idx}",
                    placeholder="e.g. Misc plantings",
                )
                custom_category = cm2.text_input(
                    "Category (optional)",
                    key=f"custom_mat_cat_{li_idx}",
                    placeholder="e.g. Plants/Lawn",
                )

                custom_pricing_mode = st.selectbox(
                    "Pricing Type",
                    options=["Per Piece", "Per Area (Sq Ft / LF / CY)"],
                    key=f"custom_pricing_mode_{li_idx}",
                )

                if custom_pricing_mode == "Per Piece":
                    cq1, cq2 = st.columns(2)
                    custom_qty = cq1.number_input(
                        "Quantity (pc)",
                        min_value=0.0,
                        value=0.0,
                        step=1.0,
                        key=f"custom_qty_pc_{li_idx}",
                    )
                    custom_unit_price = cq2.number_input(
                        "$/pc",
                        min_value=0.0,
                        value=0.0,
                        step=0.01,
                        key=f"custom_price_pc_{li_idx}",
                    )
                else:
                    cq1, cq2 = st.columns(2)
                    custom_qty = cq1.number_input(
                        "Area (Sq Ft / LF / CY)",
                        min_value=0.0,
                        value=0.0,
                        step=1.0,
                        key=f"custom_qty_area_{li_idx}",
                    )
                    custom_unit_price = cq2.number_input(
                        "$ per unit area",
                        min_value=0.0,
                        value=0.0,
                        step=0.01,
                        key=f"custom_price_area_{li_idx}",
                    )

                custom_notes = st.text_input(
                    "Custom Notes (optional)",
                    key=f"custom_notes_{li_idx}",
                    placeholder="Any details to show on the estimate",
                )

                if st.button(
                    "Add Custom Material",
                    type="primary",
                    key=f"add_custom_material_{li_idx}",
                    help="Create a custom material entry using the pricing above.",
                ):
                    if not custom_name:
                        st.warning("Please enter a custom material name.")
                    elif custom_qty <= 0 or custom_unit_price <= 0:
                        st.warning("Quantity and unit price must be greater than zero.")
                    else:
                        if custom_pricing_mode == "Per Piece":
                            custom_entry = LineItemEntry(
                                material_name=custom_name,
                                category=custom_category or li.name,
                                cost_per_unit=custom_unit_price,
                                quantity=custom_qty,
                                notes=custom_notes,
                                use_dynamic_pricing=False,
                            )
                        else:
                            custom_entry = LineItemEntry(
                                material_name=custom_name,
                                category=custom_category or li.name,
                                area_value=custom_qty,
                                price_per_area=custom_unit_price,
                                notes=custom_notes,
                                use_dynamic_pricing=False,
                            )
                        li.entries.append(custom_entry)
                        _save(estimate)
                        st.rerun()

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
            total_hrs = li.labor_hours + sum(e.labor_hours for e in li.entries)
            d3.write(
                f"Labor: **{total_hrs:.1f}h** · "
                f"**${li.labor_cost(config):,.2f}**"
            )

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
