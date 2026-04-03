"""Output display & export UI — with editable cart."""

from __future__ import annotations

import io
from datetime import datetime

import pandas as pd
import streamlit as st
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Table,
    TableStyle,
)

from config import CostConfig, LLMConfig, SheetConfig
from models import AREA_HINTS, ProjectEstimate, unit_label
from services.llm import LLMService
from services.sheets import SheetsService

_DEFAULT_SECTION_COLOR = "#2E7D5F"


# ---------------------------------------------------------------------------
# Session-state helper
# ---------------------------------------------------------------------------


def _save(estimate: ProjectEstimate) -> None:
    st.session_state["estimate"] = estimate.model_dump()


# ---------------------------------------------------------------------------
# Line-item renderer for output cart
# ---------------------------------------------------------------------------


def _render_output_line_item(
    estimate: ProjectEstimate,
    li: "LineItem",
    li_idx: int,
    config: CostConfig,
) -> None:
    """Render one line item in the output cart detail."""
    from models import LineItem  # noqa: F811 — deferred to avoid circular

    li_total = li.total_element_price(config)
    subtitle = ""
    if li.notes:
        short = li.notes if len(li.notes) <= 80 else li.notes[:77] + "…"
        subtitle = f" — {short}"

    with st.expander(
        f"**{li.name}**{subtitle} · "
        f"{len(li.entries)} item(s) · **${li_total:,.2f}**",
        expanded=True,
    ):
        if li.entries:
            _col_w = [2.8, 1.0, 0.8, 0.8, 0.8, 1.2, 0.5]
            h1, h2, h3, h4, h5, h6, h7 = st.columns(_col_w)
            h1.markdown("**Material**")
            h2.markdown("**SqFt/LF**")
            h3.markdown("**$/sf**")
            h4.markdown("**Qty**")
            h5.markdown("**$/pc**")
            h6.markdown("**Total**")
            h7.markdown("**Del**")

            for e_idx, entry in enumerate(li.entries):
                e_hint = entry.unit_hint or ""
                is_area_entry = e_hint in AREA_HINTS or (
                    entry.area_value > 0 and entry.quantity == 0
                )
                has_length = (
                    entry.length_feet is not None and entry.length_feet > 0
                )

                c1, c2, c3, c4, c5, c6, c7 = st.columns(_col_w)

                mat_display = entry.material_name
                if e_hint:
                    mat_display += f"  `{unit_label(e_hint)}`"
                c1.write(mat_display)

                if is_area_entry:
                    updated_area = c2.number_input(
                        "Area",
                        min_value=0.0,
                        value=entry.area_value,
                        step=1.0,
                        key=f"out_area_{li_idx}_{e_idx}",
                        label_visibility="collapsed",
                    )
                    if updated_area != entry.area_value:
                        entry.area_value = updated_area
                        _save(estimate)
                elif has_length:
                    c2.write(
                        f"{entry.quantity * (entry.length_feet or 0):.1f}"
                    )
                else:
                    c2.write("—")

                if is_area_entry:
                    c3.write(f"${entry.price_per_area:,.2f}")
                elif has_length:
                    c3.write(f"${entry.cost_per_unit:,.2f}")
                else:
                    c3.write("—")

                if is_area_entry and not has_length:
                    c4.write("—")
                else:
                    updated_qty = c4.number_input(
                        "Qty",
                        min_value=0.0,
                        value=entry.quantity,
                        step=1.0,
                        key=f"out_qty_{li_idx}_{e_idx}",
                        label_visibility="collapsed",
                    )
                    if updated_qty != entry.quantity:
                        entry.quantity = updated_qty
                        _save(estimate)

                if not is_area_entry and not has_length:
                    c5.write(f"${entry.cost_per_unit:,.2f}")
                else:
                    c5.write("—")

                c6.write(f"**${entry.total_cost:,.2f}**")

                if c7.button("🗑️", key=f"out_del_{li_idx}_{e_idx}"):
                    li.entries.pop(e_idx)
                    _save(estimate)
                    st.rerun()

        extras: list[str] = []
        total_labor_hours = li.labor_hours + sum(
            e.labor_hours for e in li.entries
        )
        if total_labor_hours > 0:
            extras.append(
                f"Labor: {total_labor_hours}h → ${li.labor_cost(config):,.2f}"
            )
        if li.dump_runs > 0:
            extras.append(
                f"Dump runs: {li.dump_runs} → ${li.dump_cost(config):,.2f}"
            )
        if extras:
            st.caption(" · ".join(extras))


# ---------------------------------------------------------------------------
# Public render
# ---------------------------------------------------------------------------


def render_output(
    estimate: ProjectEstimate,
    config: CostConfig,
    sheet_config: SheetConfig,
    llm_config: LLMConfig | None = None,
) -> ProjectEstimate:
    """Render the output estimate view with summary, editable cart, writeup, and export.

    Returns the (possibly modified) estimate so the caller can persist it.
    """

    st.subheader("📊 Project Estimate Summary")

    # ---- Summary metrics ----
    m1, m2, m3, m4 = st.columns(4)
    total = estimate.grand_total(config)
    delta = estimate.budget_delta(config)
    delta_label = "under budget" if delta >= 0 else "over budget"

    m1.metric("Grand Total", f"${total:,.2f}")
    m2.metric("Materials", f"${estimate.total_materials_cost(config):,.2f}")
    m3.metric("Labor", f"${estimate.total_labor_cost(config):,.2f}")
    m4.metric(
        "Budget Delta",
        f"${abs(delta):,.2f}",
        delta=delta_label,
        delta_color="normal" if delta >= 0 else "inverse",
    )

    # ---- Editable material breakdown ----
    st.markdown("---")
    st.subheader("🛒 Cart Detail  ·  Edit or Remove Items")

    total_items = sum(len(li.entries) for li in estimate.line_items)
    if total_items == 0:
        st.info(
            "No items in the cart yet. Add items from the "
            "**Interactive Menu** or **Text Description** tab."
        )
    else:
        sections_order = estimate.sections or [""]
        for section_name in sections_order:
            section_lis = [
                (i, li)
                for i, li in enumerate(estimate.line_items)
                if li.section == section_name
            ]
            active_lis = [
                (i, li) for i, li in section_lis
                if li.entries or li.labor_hours > 0 or li.dump_runs > 0
            ]
            if not active_lis:
                continue

            if section_name:
                sec_color = estimate.section_colors.get(
                    section_name, _DEFAULT_SECTION_COLOR
                )
                sec_total = sum(
                    li.total_element_price(config) for _, li in active_lis
                )
                st.markdown(
                    f'<div style="'
                    f"background:{sec_color};"
                    f"color:#fff;"
                    f"padding:10px 16px;"
                    f"border-radius:8px;"
                    f"margin:0.75rem 0 0.5rem 0;"
                    f'">'
                    f'<strong style="font-size:1.1em;">'
                    f"\U0001F4C1 {section_name}</strong>"
                    f'<span style="margin-left:0.75em;opacity:0.92;'
                    f'font-size:0.92em;">'
                    f"{len(active_lis)} line item"
                    f"{'s' if len(active_lis) != 1 else ''}"
                    f" — ${sec_total:,.2f}"
                    f"</span></div>",
                    unsafe_allow_html=True,
                )

            for li_idx, li in active_lis:
                _render_output_line_item(estimate, li, li_idx, config)

    # ---- Summary table (template format) ----
    st.markdown("---")
    st.subheader("📋 Line Item Summary")

    df = estimate.to_summary_dataframe(config)

    has_data = df.apply(
        lambda row: any(v is not None and v != 0 and v != "" for v in row), axis=1
    )
    display_df = df[has_data] if has_data.any() else df

    if display_df.empty:
        st.info("No data to display")
        _save(estimate)
        return estimate

    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
    )

    # ---- Project writeup (client-facing proposal from line items) ----
    st.markdown("---")
    st.subheader("✉️ Project Writeup")
    st.caption(
        "Generate a client-ready email that walks through the estimate and "
        "incorporates site access."
    )

    writeup_key = "output_writeup"
    if writeup_key not in st.session_state:
        st.session_state[writeup_key] = ""

    col_gen, _ = st.columns([1, 3])
    generate_clicked = col_gen.button("✨ Generate Writeup", type="primary")

    if generate_clicked:
        if not llm_config or not llm_config.openai_api_key:
            st.warning(
                "OpenAI API key is not configured. Add it to `.streamlit/secrets.toml` "
                "under `[llm]` → `openai_api_key` to generate writeups."
            )
        elif not estimate.line_items:
            st.warning("Add at least one section and items in the **Interactive Menu** to generate a writeup.")
        else:
            with st.spinner("Generating writeup…"):
                try:
                    llm = LLMService(llm_config)
                    st.session_state[writeup_key] = llm.generate_project_writeup(
                        estimate, config
                    )
                    st.rerun()
                except Exception as e:
                    st.error(f"Writeup generation failed: {e}")

    if st.session_state[writeup_key]:
        st.download_button(
            label="⬇️ Download writeup as .txt",
            data=st.session_state[writeup_key],
            file_name=f"writeup_{estimate.address or 'project'}_{datetime.now():%Y%m%d}.txt",
            mime="text/plain",
        )

    # ---- Export options ----
    st.markdown("---")
    st.subheader("📤 Export")

    exp1, exp2, exp3 = st.columns(3)

    # CSV
    csv_buf = io.StringIO()
    df.to_csv(csv_buf, index=False)
    exp1.download_button(
        label="⬇️ Download CSV",
        data=csv_buf.getvalue(),
        file_name=f"estimate_{estimate.address or 'project'}_{datetime.now():%Y%m%d}.csv",
        mime="text/csv",
    )

    # PDF — generate condensed descriptions (LLM if available, else fallback)
    pdf_desc_key = "pdf_descriptions"
    if pdf_desc_key not in st.session_state:
        st.session_state[pdf_desc_key] = {}

    if exp2.button("✨ Generate & Download PDF", type="secondary"):
        if llm_config and llm_config.openai_api_key:
            with st.spinner("Generating PDF descriptions…"):
                try:
                    llm = LLMService(llm_config)
                    st.session_state[pdf_desc_key] = (
                        llm.generate_pdf_line_descriptions(estimate, config)
                    )
                except Exception:
                    st.session_state[pdf_desc_key] = (
                        _build_fallback_descriptions(estimate, config)
                    )
        else:
            st.session_state[pdf_desc_key] = (
                _build_fallback_descriptions(estimate, config)
            )
        st.rerun()

    pdf_descriptions: dict[str, str] = st.session_state.get(pdf_desc_key, {})
    if not pdf_descriptions:
        pdf_descriptions = _build_fallback_descriptions(estimate, config)

    pdf_bytes = _generate_pdf(estimate, config, descriptions=pdf_descriptions)
    exp2.download_button(
        label="⬇️ Download PDF",
        data=pdf_bytes,
        file_name=f"estimate_{estimate.address or 'project'}_{datetime.now():%Y%m%d}.pdf",
        mime="application/pdf",
    )

    # Google Sheets
    if exp3.button("📤 Export to Google Sheets"):
        _export_to_sheets(estimate, config, sheet_config)

    # Persist any inline edits
    _save(estimate)
    return estimate


# ---------------------------------------------------------------------------
# PDF description helpers
# ---------------------------------------------------------------------------


def _build_fallback_descriptions(
    estimate: ProjectEstimate,
    config: CostConfig,
) -> dict[str, str]:
    """Build condensed descriptions by concatenating material names and dimensions.

    Used when no LLM is available.  Produces strings like:
    "~300sf turf, black steel edging, base materials, seam tape, infill sand"
    """
    from models import unit_label as _unit_label  # noqa: F811

    descriptions: dict[str, str] = {}
    for li in estimate.line_items:
        if not li.entries and li.labor_hours <= 0 and li.dump_runs <= 0:
            continue
        parts: list[str] = []
        if li.notes:
            parts.append(li.notes)
        for e in li.entries:
            if e.length_feet and e.length_feet > 0:
                total_len = e.quantity * e.length_feet
                parts.append(f"~{total_len:.0f}' {e.material_name}")
            elif e.area_value > 0:
                u = _unit_label(e.unit_hint) if e.unit_hint else "sf"
                u_short = u.lower().replace(" ", "")
                parts.append(f"~{e.area_value:.0f}{u_short} {e.material_name}")
            elif e.quantity > 0:
                qty_str = (
                    f"{int(e.quantity)}" if e.quantity == int(e.quantity)
                    else f"{e.quantity:.1f}"
                )
                parts.append(f"~{qty_str} {e.material_name}")
            else:
                parts.append(e.material_name)
        descriptions[li.name] = ", ".join(parts)
    return descriptions


# ---------------------------------------------------------------------------
# PDF generation
# ---------------------------------------------------------------------------


def _generate_pdf(
    estimate: ProjectEstimate,
    config: CostConfig,
    descriptions: dict[str, str] | None = None,
) -> bytes:
    """Generate a clean, client-facing invoice PDF.

    ``descriptions`` maps line-item names to short summary strings.
    If not provided, entries are omitted from the activity column.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=0.6 * inch,
        rightMargin=0.6 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
    )
    styles = getSampleStyleSheet()
    elements: list = []

    descriptions = descriptions or {}

    # -- Styles --
    header_color = colors.HexColor("#D5EDE1")
    header_text_color = colors.HexColor("#5A7D6E")
    border_color = colors.HexColor("#CCCCCC")

    activity_desc_style = ParagraphStyle(
        "ActivityDesc",
        parent=styles["Normal"],
        fontSize=8.5,
        leading=11,
        fontName="Helvetica",
        textColor=colors.HexColor("#444444"),
    )
    header_style = ParagraphStyle(
        "ColHeader",
        parent=styles["Normal"],
        fontSize=8,
        fontName="Helvetica",
        textColor=header_text_color,
    )
    money_style = ParagraphStyle(
        "Money",
        parent=styles["Normal"],
        fontSize=9,
        fontName="Helvetica",
        alignment=2,
    )
    center_style = ParagraphStyle(
        "Center",
        parent=styles["Normal"],
        fontSize=9,
        fontName="Helvetica",
        alignment=1,
    )
    total_label_style = ParagraphStyle(
        "TotalLabel",
        parent=styles["Normal"],
        fontSize=12,
        fontName="Helvetica-Bold",
        alignment=2,
    )
    total_value_style = ParagraphStyle(
        "TotalValue",
        parent=styles["Normal"],
        fontSize=14,
        fontName="Helvetica-Bold",
        alignment=2,
    )

    # Wider AMOUNT column so large totals (e.g. $500,000.10) never wrap.
    # Usable width: 8.5" - 1.2" margins = 7.3"
    col_widths = [3.9 * inch, 0.6 * inch, 1.2 * inch, 1.6 * inch]

    # -- Shared helpers to build rows & styles consistently --
    def _header_row() -> list:
        return [
            Paragraph("ACTIVITY", header_style),
            Paragraph("QTY", header_style),
            Paragraph("RATE", header_style),
            Paragraph("AMOUNT", header_style),
        ]

    def _data_row(li: "LineItem") -> list:
        li_total = li.total_element_price(config)
        desc_text = descriptions.get(li.name, "")
        activity_html = f"<b>{li.name}</b>"
        if desc_text:
            activity_html += f"<br/>{desc_text}"
        return [
            Paragraph(activity_html, activity_desc_style),
            Paragraph("1", center_style),
            Paragraph(f"{li_total:,.2f}", money_style),
            Paragraph(f"{li_total:,.2f}", money_style),
        ]

    def _total_row() -> list:
        grand = estimate.grand_total(config)
        return [
            Paragraph("", styles["Normal"]),
            Paragraph("", styles["Normal"]),
            Paragraph("TOTAL", total_label_style),
            Paragraph(f"${grand:,.2f}", total_value_style),
        ]

    def _base_style_commands(n_data: int) -> list:
        """Style commands shared by both the main table and the tail table."""
        cmds: list = [
            ("BACKGROUND", (0, 0), (-1, 0), header_color),
            ("TOPPADDING", (0, 0), (-1, 0), 8),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
            ("LEFTPADDING", (0, 0), (0, 0), 12),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 1), (0, -1), 12),
            ("RIGHTPADDING", (-1, 0), (-1, -1), 12),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, border_color),
        ]
        for row_idx in range(1, n_data + 1):
            cmds.append(("TOPPADDING", (0, row_idx), (-1, row_idx), 8))
            cmds.append(("BOTTOMPADDING", (0, row_idx), (-1, row_idx), 8))
            cmds.append(
                ("LINEBELOW", (0, row_idx), (-1, row_idx), 0.25, border_color)
            )
        return cmds

    active_items = [
        li for li in estimate.line_items
        if li.entries or li.labor_hours > 0 or li.dump_runs > 0
    ]

    if len(active_items) <= 1:
        # Few enough rows — single table, no split concerns.
        table_data = [_header_row()]
        for li in active_items:
            table_data.append(_data_row(li))
        table_data.append(_total_row())

        n = len(active_items)
        cmds = _base_style_commands(n)
        cmds.append(
            ("LINEABOVE", (0, n + 1), (-1, n + 1), 1.0, border_color)
        )
        cmds.append(("TOPPADDING", (0, -1), (-1, -1), 14))
        cmds.append(("BOTTOMPADDING", (0, -1), (-1, -1), 10))

        table = Table(table_data, colWidths=col_widths, repeatRows=1)
        table.setStyle(TableStyle(cmds))
        elements.append(table)
    else:
        # Split into main table + tail table (last data row + TOTAL).
        # KeepTogether on the tail ensures the TOTAL is never orphaned.
        main_items = active_items[:-1]
        tail_item = active_items[-1]

        # --- Main table (header + all rows except the last) ---
        main_data = [_header_row()]
        for li in main_items:
            main_data.append(_data_row(li))

        main_cmds = _base_style_commands(len(main_items))
        main_table = Table(main_data, colWidths=col_widths, repeatRows=1)
        main_table.setStyle(TableStyle(main_cmds))
        elements.append(main_table)

        # --- Tail table (last data row + TOTAL), kept together ---
        tail_data = [_data_row(tail_item), _total_row()]
        tail_cmds: list = [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (0, -1), 12),
            ("RIGHTPADDING", (-1, 0), (-1, -1), 12),
            ("TOPPADDING", (0, 0), (-1, 0), 8),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
            ("LINEBELOW", (0, 0), (-1, 0), 0.25, border_color),
            ("LINEABOVE", (0, 1), (-1, 1), 1.0, border_color),
            ("TOPPADDING", (0, 1), (-1, 1), 14),
            ("BOTTOMPADDING", (0, 1), (-1, 1), 10),
        ]
        tail_table = Table(tail_data, colWidths=col_widths)
        tail_table.setStyle(TableStyle(tail_cmds))
        elements.append(KeepTogether([tail_table]))

    doc.build(elements)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Google Sheets export
# ---------------------------------------------------------------------------


def _export_to_sheets(
    estimate: ProjectEstimate,
    config: CostConfig,
    sheet_config: SheetConfig,
) -> None:
    """Overwrite the existing estimate tab (or create one) with current data."""
    try:
        service = SheetsService(sheet_config)
        tab_title = (
            f"Estimate - {estimate.address or 'Project'}"
            f" - {datetime.now():%Y-%m-%d}"
        )
        url = service.export_estimate_to_sheet(
            tab_title=tab_title,
            estimate=estimate,
            cost_config=config,
        )
        st.session_state["_last_autosave_ts"] = datetime.now()
        st.success(f"✅ Exported! [Open in Google Sheets]({url})")
    except Exception as e:
        st.error(f"Export failed: {e}")
