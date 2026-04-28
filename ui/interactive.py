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


def _ensure_sections(estimate: ProjectEstimate) -> None:
    """Migrate legacy estimates: line items without a section get one."""
    orphans = [li for li in estimate.line_items if not li.section]
    if orphans:
        default = "GENERAL"
        if default not in estimate.sections:
            estimate.sections.insert(0, default)
        for li in orphans:
            li.section = default
        _save(estimate)


_DEFAULT_SECTION_COLOR = "#2E7D5F"


def _section_header_html(name: str, color: str, summary: str) -> str:
    """Build an HTML banner for a section header."""
    return (
        f'<div style="'
        f"background:{color};"
        f"color:#fff;"
        f"padding:10px 16px;"
        f"border-radius:8px 8px 0 0;"
        f"margin-top:0.75rem;"
        f'">'
        f'<strong style="font-size:1.15em;">\U0001F4C1 {name}</strong>'
        f'<span style="margin-left:0.75em;opacity:0.92;font-size:0.92em;">'
        f"{summary}"
        f"</span>"
        f"</div>"
    )


def _move_line_item_within_section(
    estimate: ProjectEstimate,
    li_idx: int,
    *,
    direction: int,
) -> bool:
    """Move a line item up/down, constrained to its section."""
    if li_idx < 0 or li_idx >= len(estimate.line_items):
        return False

    li = estimate.line_items[li_idx]
    target_idx = li_idx + direction
    if target_idx < 0 or target_idx >= len(estimate.line_items):
        return False
    if estimate.line_items[target_idx].section != li.section:
        return False

    estimate.line_items[li_idx], estimate.line_items[target_idx] = (
        estimate.line_items[target_idx],
        estimate.line_items[li_idx],
    )
    return True


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

    _ensure_sections(estimate)

    # ---- Add Section ----
    st.subheader("📁 Sections")

    with st.expander("➕ Add Section", expanded=not estimate.sections):
        new_sec = st.text_input(
            "Section Name",
            key="new_section_name",
            placeholder="e.g. UPPER AREA",
        )
        if st.button("Create Section", type="primary", key="create_section_btn"):
            name = new_sec.strip().upper() or "NEW SECTION"
            if name not in estimate.sections:
                estimate.sections.append(name)
                _save(estimate)
                st.rerun()
            else:
                st.warning(f"Section **{name}** already exists.")

    if not estimate.sections:
        st.info("No sections yet. Use **Add Section** above to get started.")
        return estimate

    # ---- Cart stats ----
    st.markdown("---")
    total_items = sum(len(li.entries) for li in estimate.line_items)
    st.subheader(
        f"🛒 Your Cart ({total_items} item{'s' if total_items != 1 else ''})"
    )

    if total_items == 0:
        st.info(
            "Your cart is empty. Add line items and materials below, "
            "or switch to the **Text Description** tab."
        )

    # Precompute
    category_names = list(pricing_guide.categories.keys())
    base_li_types = sorted(
        {name for name in line_item_names}
        | {li.name for li in estimate.line_items}
    ) or sorted(pricing_guide.categories.keys())

    # ---- Per Section ----
    for sec_idx, section_name in enumerate(estimate.sections):
        section_lis = [
            (i, li)
            for i, li in enumerate(estimate.line_items)
            if li.section == section_name
        ]
        section_total = sum(
            li.total_element_price(config) for _, li in section_lis
        )
        section_mat_count = sum(len(li.entries) for _, li in section_lis)

        sec_color = estimate.section_colors.get(
            section_name, _DEFAULT_SECTION_COLOR
        )

        summary = (
            f"{len(section_lis)} line item"
            f"{'s' if len(section_lis) != 1 else ''}"
            f" · {section_mat_count} material"
            f"{'s' if section_mat_count != 1 else ''}"
            f" — ${section_total:,.2f}"
        )
        st.markdown(
            _section_header_html(section_name, sec_color, summary),
            unsafe_allow_html=True,
        )

        with st.expander("Section details", expanded=bool(section_lis)):
            # ---- Section controls: color picker + delete ----
            ctrl_color, ctrl_del, _ = st.columns([1, 1, 3])
            new_color = ctrl_color.color_picker(
                "Section color",
                value=sec_color,
                key=f"sec_color_{sec_idx}",
            )
            if new_color != sec_color:
                estimate.section_colors[section_name] = new_color
                _save(estimate)
                st.rerun()

            with ctrl_del.popover(
                "🗑️ Delete Section", use_container_width=False
            ):
                item_word = (
                    "line item" if len(section_lis) == 1 else "line items"
                )
                if section_lis:
                    st.warning(
                        f"This will permanently delete **{section_name}** "
                        f"and its {len(section_lis)} {item_word}."
                    )
                else:
                    st.info(f"Delete empty section **{section_name}**?")
                if st.button(
                    "Confirm Delete",
                    key=f"confirm_del_sec_{sec_idx}",
                    type="primary",
                ):
                    estimate.sections.remove(section_name)
                    estimate.line_items = [
                        li
                        for li in estimate.line_items
                        if li.section != section_name
                    ]
                    estimate.section_colors.pop(section_name, None)
                    _save(estimate)
                    st.rerun()

            # ---- Add Line Item (inside section) ----
            with st.expander(
                "➕ Add Line Item", expanded=not section_lis
            ):
                col_type, col_notes = st.columns(2)
                li_type = col_type.selectbox(
                    "Line Item Type",
                    options=base_li_types,
                    key=f"li_type_{sec_idx}",
                    help="Choose the base category for this line item",
                )
                li_notes = col_notes.text_input(
                    "Line Item Notes (optional)",
                    key=f"li_notes_new_{sec_idx}",
                    placeholder="e.g. Front yard fence",
                )
                li_desc = st.text_input(
                    "Description (optional)",
                    key=f"li_desc_new_{sec_idx}",
                    placeholder="Short description for this line item",
                )

                if st.button(
                    "Create Line Item",
                    type="primary",
                    key=f"create_li_{sec_idx}",
                ):
                    base = li_type.strip() or "Line Item"
                    new_item = LineItem(
                        name=base,
                        notes=li_notes.strip(),
                        element_notes=li_desc.strip(),
                        section=section_name,
                    )
                    # Keep line items grouped by section order so exports don't
                    # emit duplicate section headers when revisiting a section.
                    sec_order = {name: idx for idx, name in enumerate(estimate.sections)}
                    target_order = sec_order.get(section_name, len(sec_order))
                    insert_at = len(estimate.line_items)
                    for idx, existing in enumerate(estimate.line_items):
                        existing_order = sec_order.get(existing.section, len(sec_order))
                        if existing_order > target_order:
                            insert_at = idx
                            break
                    estimate.line_items.insert(insert_at, new_item)
                    # Avoid writing widget-backed keys here: Streamlit raises
                    # if a key is mutated after that widget is instantiated.
                    _save(estimate)
                    st.rerun()

            # ---- Render each Line Item in this section ----
            for li_idx, li in section_lis:
                _render_line_item(
                    estimate, li, li_idx, pricing_guide, config,
                    category_names,
                )

    # Save any inline edits
    _save(estimate)

    # ---- Running total footer ----
    st.markdown("---")
    ft1, ft2, ft3, ft4 = st.columns(4)
    ft1.metric("Materials", f"${estimate.total_materials_cost(config):,.2f}")
    ft2.metric("Labor", f"${estimate.total_labor_cost(config):,.2f}")
    ft3.metric("Dump Runs", f"${estimate.total_dump_cost(config):,.2f}")
    ft4.metric("🧾 Grand Total", f"${estimate.grand_total(config):,.2f}")

    return estimate


# ---------------------------------------------------------------------------
# Line-item renderer (one expander per line item, nested inside its section)
# ---------------------------------------------------------------------------


def _render_line_item(
    estimate: ProjectEstimate,
    li: LineItem,
    li_idx: int,
    pricing_guide: PricingGuide,
    config: CostConfig,
    category_names: list[str],
) -> None:
    """Render a single line item as a nested expander with materials, labor, etc."""

    entry_count = len(li.entries)
    li_total = li.total_element_price(config)
    has_content = entry_count > 0 or li.labor_hours > 0 or li.dump_runs > 0

    subtitle = ""
    if li.notes:
        short = li.notes if len(li.notes) <= 80 else li.notes[:77] + "…"
        subtitle = f" — {short}"

    items_tag = f"{entry_count} item{'s' if entry_count != 1 else ''}"
    badge = f" — **${li_total:,.2f}**" if has_content else ""
    label = f"**{li.name}**{subtitle} ({items_tag}){badge}"

    with st.expander(label, expanded=has_content):
        # ---- Line item notes, description, move & delete ----
        n1, n2, n_up, n_down, n_del = st.columns([2, 2, 0.5, 0.5, 0.5])
        li.notes = n1.text_input(
            "Line Item Notes",
            value=li.notes,
            key=f"li_notes_{li_idx}",
        )
        li.element_notes = n2.text_input(
            "Description",
            value=li.element_notes,
            key=f"li_elem_{li_idx}",
        )
        n_up.markdown("<br>", unsafe_allow_html=True)
        n_down.markdown("<br>", unsafe_allow_html=True)
        n_del.markdown("<br>", unsafe_allow_html=True)
        can_move_li_up = (
            li_idx > 0
            and estimate.line_items[li_idx - 1].section == li.section
        )
        can_move_li_down = (
            li_idx < len(estimate.line_items) - 1
            and estimate.line_items[li_idx + 1].section == li.section
        )
        if n_up.button(
            "⬆️",
            key=f"li_up_{li_idx}",
            help="Move line item up",
            disabled=not can_move_li_up,
        ):
            if _move_line_item_within_section(estimate, li_idx, direction=-1):
                _save(estimate)
                st.rerun()
        if n_down.button(
            "⬇️",
            key=f"li_down_{li_idx}",
            help="Move line item down",
            disabled=not can_move_li_down,
        ):
            if _move_line_item_within_section(estimate, li_idx, direction=1):
                _save(estimate)
                st.rerun()
        if li.entries:
            with n_del.popover("🗑️"):
                mat_word = "material" if entry_count == 1 else "materials"
                st.warning(
                    f"Delete **{li.name}** and its "
                    f"{entry_count} {mat_word}?"
                )
                if st.button(
                    "Confirm Delete",
                    key=f"confirm_del_li_{li_idx}",
                    type="primary",
                ):
                    estimate.line_items.pop(li_idx)
                    _save(estimate)
                    st.rerun()
        elif n_del.button("🗑️", key=f"del_li_{li_idx}", help="Delete this line item"):
            estimate.line_items.pop(li_idx)
            _save(estimate)
            st.rerun()

        # ---- Add material to this line item ----
        st.markdown("**Add Material/Unit to this Line Item**")

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
            help="Pick a material to add to this line item",
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

        selected_labor = add_col_labor.number_input(
            "Labor Hours (for this item)",
            min_value=0.0,
            value=0.0,
            step=0.5,
            key=f"labor_item_{li_idx}",
            help="Labor hours associated with this specific item",
        )

        # Unit price — key includes material name so switching materials
        # within the same category resets the widget to the new default.
        chosen_unit_price: float | None = None
        lock_price = False
        if selected_mat is not None:
            sheet_price = float(selected_mat.retail_with_tax or 0.0)
            has_price_range = (
                selected_mat.retail_with_tax_min is not None
                and selected_mat.retail_with_tax_max is not None
            )

            if has_price_range:
                lo = float(selected_mat.retail_with_tax_min or 0.0)
                hi = float(selected_mat.retail_with_tax_max or 0.0)
                midpoint = sheet_price or (lo + hi) / 2.0
                default_price = midpoint
            else:
                default_price = sheet_price

            price_key = f"price_input_{li_idx}_{selected_mat.name}"
            prev_price_mat = st.session_state.get(f"_price_mat_{li_idx}")
            if prev_price_mat and prev_price_mat != selected_mat.name:
                old_key = f"price_input_{li_idx}_{prev_price_mat}"
                st.session_state.pop(old_key, None)
            st.session_state[f"_price_mat_{li_idx}"] = selected_mat.name

            chosen_unit_price = st.number_input(
                "Unit Price",
                min_value=0.0,
                value=default_price,
                step=0.5,
                key=price_key,
                help="Custom unit price for this material.",
            )

            if has_price_range or chosen_unit_price != sheet_price:
                lock_price = True

        # Linear-unit materials: length per piece
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
        )
        if add_col_btn.button(
            "Add Item", key=f"add_item_{li_idx}", type="primary"
        ):
            if (
                selected_material_label != "— Select a material —"
                and selected_mat
            ):
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
                # Avoid writing widget-backed keys here: Streamlit raises
                # if a key is mutated after that widget is instantiated.
                _save(estimate)
                st.rerun()
            else:
                st.warning("Please select a material first.")

        # ---- Material entries table ----
        if li.entries:
            _col_w = [2.6, 0.9, 0.8, 0.8, 0.8, 1.1, 0.8, 1.4, 0.5, 0.5, 0.5]
            (hdr1, hdr2, hdr3, hdr4, hdr5,
             hdr6, hdr7, hdr8, hdr9, hdr10, hdr11) = st.columns(_col_w)
            hdr1.markdown("**Material**")
            hdr2.markdown("**SqFt/LF**")
            hdr3.markdown("**$/sf**")
            hdr4.markdown("**Qty**")
            hdr5.markdown("**$/pc**")
            hdr6.markdown("**Total**")
            hdr7.markdown("**Labor**")
            hdr8.markdown("**Notes**")
            hdr9.markdown("**Up**")
            hdr10.markdown("**Dn**")
            hdr11.markdown("**Del**")

            for e_idx, entry in enumerate(li.entries):
                entry_key = entry.ui_key
                e_hint = entry.unit_hint or ""
                is_area_entry = e_hint in AREA_HINTS or (
                    entry.area_value > 0 and entry.quantity == 0
                )
                has_length = (
                    entry.length_feet is not None and entry.length_feet > 0
                )

                (c1, c2, c3, c4, c5,
                 c6, c7, c8, c9, c10, c11) = st.columns(_col_w)

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
                        key=f"cart_area_{li_idx}_{entry_key}",
                        label_visibility="collapsed",
                    )
                    if updated_area != entry.area_value:
                        entry.area_value = updated_area
                        _save(estimate)
                        st.rerun()
                elif has_length:
                    c2.write(
                        f"{entry.quantity * (entry.length_feet or 0):.1f}"
                    )
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
                        key=f"cart_qty_{li_idx}_{entry_key}",
                        label_visibility="collapsed",
                    )
                    if updated_qty != entry.quantity:
                        entry.quantity = updated_qty
                        _save(estimate)
                        st.rerun()

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
                    key=f"cart_labor_{li_idx}_{entry_key}",
                    label_visibility="collapsed",
                )
                if updated_labor != entry.labor_hours:
                    entry.labor_hours = updated_labor
                    _save(estimate)
                    st.rerun()

                updated_notes = c8.text_input(
                    "Notes",
                    value=entry.notes,
                    key=f"cart_notes_{li_idx}_{entry_key}",
                    placeholder="Optional notes",
                    label_visibility="collapsed",
                )
                if updated_notes != entry.notes:
                    entry.notes = updated_notes
                    _save(estimate)
                    st.rerun()

                can_move_entry_up = e_idx > 0
                can_move_entry_down = e_idx < len(li.entries) - 1
                if c9.button(
                    "⬆️",
                    key=f"entry_up_{li_idx}_{entry_key}",
                    disabled=not can_move_entry_up,
                ):
                    li.entries[e_idx], li.entries[e_idx - 1] = (
                        li.entries[e_idx - 1],
                        li.entries[e_idx],
                    )
                    _save(estimate)
                    st.rerun()

                if c10.button(
                    "⬇️",
                    key=f"entry_down_{li_idx}_{entry_key}",
                    disabled=not can_move_entry_down,
                ):
                    li.entries[e_idx], li.entries[e_idx + 1] = (
                        li.entries[e_idx + 1],
                        li.entries[e_idx],
                    )
                    _save(estimate)
                    st.rerun()

                if c11.button("🗑️", key=f"del_{li_idx}_{entry_key}"):
                    li.entries.pop(e_idx)
                    _save(estimate)
                    st.rerun()

            st.markdown(
                f"**Materials Subtotal: ${li.materials_total(config):,.2f}**"
            )
        else:
            st.caption("No materials added yet.")

        # ---- Custom Area / Piece materials ----
        with st.popover("📐 Area / Piece Pricing (advanced)"):
            st.markdown("**Custom Material (Area / Piece)**")

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
                    st.warning(
                        "Quantity and unit price must be greater than zero."
                    )
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
        updated_dump_runs = int(
            d1.number_input(
                "Dump Runs",
                min_value=0,
                value=li.dump_runs,
                step=1,
                key=f"dump_{li_idx}",
            )
        )
        if updated_dump_runs != li.dump_runs:
            li.dump_runs = updated_dump_runs
            _save(estimate)
            st.rerun()
        d2.write(f"Dump cost: **${li.dump_cost(config):,.2f}**")
        total_hrs = li.labor_hours + sum(e.labor_hours for e in li.entries)
        d3.write(
            f"Labor: **{total_hrs:.1f}h** · "
            f"**${li.labor_cost(config):,.2f}**"
        )
