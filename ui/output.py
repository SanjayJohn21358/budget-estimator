"""Output display & export UI — with editable cart."""

from __future__ import annotations

import io
from datetime import datetime

import pandas as pd
import streamlit as st
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from config import CostConfig, LLMConfig, SheetConfig
from models import ProjectEstimate
from services.llm import LLMService
from services.sheets import SheetsService


# ---------------------------------------------------------------------------
# Session-state helper
# ---------------------------------------------------------------------------


def _save(estimate: ProjectEstimate) -> None:
    st.session_state["estimate"] = estimate.model_dump()


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
        st.info("No items in the cart yet. Add items from the **Interactive Menu** or **Text Description** tab.")
    else:
        for li_idx, li in enumerate(estimate.line_items):
            if not li.entries and li.labor_hours == 0 and li.dump_runs == 0:
                continue

            section_total = li.total_element_price(config)
            with st.expander(
                f"**{li.name}** — {len(li.entries)} item(s) · **${section_total:,.2f}**",
                expanded=True,
            ):
                if li.entries:
                    # Header
                    h1, h2, h3, h4, h5 = st.columns([3, 1.5, 1.2, 1.5, 0.6])
                    h1.markdown("**Material**")
                    h2.markdown("**Unit Cost**")
                    h3.markdown("**Qty**")
                    h4.markdown("**Subtotal**")
                    h5.markdown("**Del**")

                    for e_idx, entry in enumerate(li.entries):
                        c1, c2, c3, c4, c5 = st.columns([3, 1.5, 1.2, 1.5, 0.6])
                        c1.write(entry.material_name)
                        c2.write(f"${entry.cost_per_unit:,.2f}")

                        updated_qty = c3.number_input(
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

                        c4.write(f"**${entry.total_cost:,.2f}**")

                        if c5.button("🗑️", key=f"out_del_{li_idx}_{e_idx}"):
                            li.entries.pop(e_idx)
                            _save(estimate)
                            st.rerun()

                # Show labor / dump if present
                extras: list[str] = []

                # Total labor hours = section-wide + per-entry
                total_labor_hours = li.labor_hours + sum(
                    e.labor_hours for e in li.entries
                )
                if total_labor_hours > 0:
                    extras.append(
                        f"Labor: {total_labor_hours}h → ${li.labor_cost(config):,.2f}"
                    )
                if li.dump_runs > 0:
                    extras.append(f"Dump runs: {li.dump_runs} → ${li.dump_cost(config):,.2f}")
                if extras:
                    st.caption(" · ".join(extras))

    # ---- Summary table (template format) ----
    st.markdown("---")
    st.subheader("📋 Line Item Summary")

    df = estimate.to_summary_dataframe(config)

    has_data = df.apply(
        lambda row: any(v != 0 and v != "" for v in row), axis=1
    )
    display_df = df[has_data] if has_data.any() else df

    if display_df.empty:
        st.info("No data to display")
        _save(estimate)
        return estimate

    display_df['Sq Ft / LF / CY'] = pd.to_numeric(display_df['Sq Ft / LF / CY'], errors='coerce')

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

    writeup_text = st.session_state[writeup_key]

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

    # PDF
    pdf_bytes = _generate_pdf(estimate, config)
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
# PDF generation
# ---------------------------------------------------------------------------


def _generate_pdf(estimate: ProjectEstimate, config: CostConfig) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(letter),
        leftMargin=0.5 * inch,
        rightMargin=0.5 * inch,
    )
    styles = getSampleStyleSheet()
    elements: list = []

    title_style = ParagraphStyle(
        "Title",
        parent=styles["Heading1"],
        fontSize=16,
        spaceAfter=12,
    )
    elements.append(Paragraph("Landscaping Project Estimate", title_style))
    elements.append(Spacer(1, 6))

    info_lines = [
        f"<b>Address:</b> {estimate.address or 'N/A'}",
        f"<b>Budget:</b> ${estimate.project_budget:,.2f}",
        f"<b>Access:</b> {estimate.access_level}",
        f"<b>Total Estimate:</b> ${estimate.grand_total(config):,.2f}",
    ]
    for line in info_lines:
        elements.append(Paragraph(line, styles["Normal"]))
    elements.append(Spacer(1, 12))

    df = estimate.to_summary_dataframe(config)
    header = list(df.columns)
    table_data = [header]
    for _, row in df.iterrows():
        table_data.append([str(v) for v in row.values])

    col_count = len(header)
    col_width = (10 * inch) / col_count if col_count else inch
    table = Table(table_data, colWidths=[col_width] * col_count)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2E4057")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("FONTSIZE", (0, 0), (-1, 0), 8),
                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [colors.white, colors.HexColor("#F0F2F6")],
                ),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    elements.append(table)

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
    """Duplicate the template tab and fill in estimate data."""
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
        st.success(f"✅ Exported! [Open in Google Sheets]({url})")
    except Exception as e:
        st.error(f"Export failed: {e}")
