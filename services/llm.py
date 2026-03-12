"""LLM service for interpreting text descriptions into structured estimates."""

from __future__ import annotations

import json
from typing import Any

from openai import OpenAI

from config import CostConfig, LLMConfig
from models import PricingGuide, ProjectEstimate, unit_label


# ---------------------------------------------------------------------------
# Example writeups (client proposal style) — used as few-shot for writeup generation
# ---------------------------------------------------------------------------

_WRITEUP_EXAMPLES = """\
Example 1 (Kim):
---
Hi Kim,

Hope your week is going well! Thanks for your patience as we put this together, finally had a chance to sit down to put together numbers here. Attached is the estimate for the proposed work – I broke it down into the major elements, which include materials, labor, and taxes. I included an example of what a typical overhead design document looks like and pictures of that design before and after installation so you can get an idea of how that translates. I also attached a quick sketch of the proposed layout to follow along. This concept incorporates spaces for entertainment and play, while keeping a low maintenance focus among an aesthetically integrated whole.

We would start with demo and cleanup of the space removing any unwanted plants and materials including the existing deck and fences. A major unknown here is what's going on underneath the deck - there are some concrete footings and brick that we saw at the consult, but we won't know what we're dealing with until we remove the deck. The miscellaneous line item factors in discovery and some materials removal to allow room in the budget for unforeseen objects or obstacles. In conjunction with the cleanup, we would draw up a design for the space, incorporating proposed elements with a plan for plant and hardscape layout.

Once cleanup is done, we'll move onto installing the ~6'H redwood vertical slat fences on the north and east sides. We'll plan to build a low retaining wall along the north fence to retain soil along the neighbor's property line.

Example 2 (Tracey):
---
Hi Tracey,

Here is the estimate for the backyard space – I broke it down into the major elements, which include materials, labor, and taxes. This also factors in the relatively difficult entryway to the back space for hauling materials etc. I attached a quick sketch of the proposed layout to follow along.

We would start with a clean up of the space, removing most, if not all, of the dodonaea shrubs and any other unwanted plants and materials. From there we would demo the existing concrete pad in the lower area to make space for the slate patio. I added a line item for a low ~6" retaining wall along the back perimeter if we decide to leave any plants and need to accommodate the grade change. In conjunction with the cleanup, we would draw up a design for the space, incorporating proposed elements with a plan for plant and hardscape layout.

Once the concrete demo is complete we'll get to work installing the ~245SF patio. The patio design will follow a more oval, organic shape leaving room for a planted border to soften the concrete wall and create a more inviting space. I've included a raised planter bed for edibles that could go in the northeast corner as this would most likely get the most sun.

After the hardscape elements are in place, we would install lighting, irrigation, plants and mulch. We'd plan to run a copper line down to the garden level and install the drip irrigation for the plants from there. The line item for the low voltage lighting includes 4 uplights and 6 pathlights to create a warm ambience in the evenings, but we can chat more about what kind of lighting you're looking for to make sure it fits your needs. For plants, we would plan to go with the CA native/Mediterranean climate plants and potentially some edibles, but can talk through any ideas and thoughts you have around that!

Lastly, I included a small miscellaneous line item to allow some flexibility if there are any changes or additions that arise during the project. This wouldn't be billed unless it was used for a specific element (i.e. rain barrel).

Let us know what you think – feel free to send along any thoughts or questions!

Example 3 (Tom):
---
Hi Tom,

Hope your week is going well! Thanks for your patience as we put this together, finally had a chance to sit down to put together some design ideas and numbers here. Attached is the estimate for the proposed work – I broke it down into the major elements, which include materials, labor, and taxes. I included an example of what a typical overhead design document looks like and pictures of that design before and after installation so you can get an idea of how that translates. I also attached a quick sketch of the proposed layout to follow along. This concept incorporates spaces for entertainment and play, while keeping a low maintenance focus among an aesthetically integrated whole.

We would start by doing a clean up of the space, removing any unwanted plants and materials. We would plan to remove the remainder of the concrete walkway and patio area to give the space a fresh start. In conjunction with the cleanup, we would draw up a design for the space, incorporating proposed elements with a plan for plant and hardscape layout.

From there we would proceed with the hardscape elements – walking out into the yard, the thought is to have a bluestone patio that roughly covers the same area as the current patio, giving plenty of space for an adult lounge/dining area. For reference, the project in the design example photo uses this material for the patio. Moving out past the patio, you have a ~300 sq. ft. turf area, which provides ample room for kids to play on, while also offering an extension to the patio for larger groups. The third main hardscape element is a DG pathway that leads from the base of the stairs out around the turf toward the back of the garden. This will offer access to the back area while also providing an opportunity for a little garden stroll – the center of this area is a great spot for a featured tree, which could be fruiting or ornamental. One thought is to frame the transition area with a couple outdoor pots.

Along the north side of the turf section, we have a proposed raised bed area, which would be a great spot for an herb garden, cut flowers, or vegetables. Once the hardscape elements are in, we would get the plants in the ground, run irrigation, and finish up with a layer of mulch. We typically focus on California native or otherwise Mediterranean climate plants that are well suited to the area for lower maintenance and water use. I also included a line item for lighting – this budget allows for a mix of up lights, path lights, and string lights to accent the space in the evening, creating a warm ambience for hanging on the patio or just viewing through the window.

Lastly, I included a small miscellaneous line item to allow some flexibility if there are any changes or additions that arise during the project. This wouldn't be billed unless it was used for a specific element (i.e. material upgrade, add pots, etc.). I know this is above the reference budget you mentioned – wanted to show an option that balances use of the whole space as discussed, but we can definitely make adjustments if needed (scale elements up or down, etc.). Also left out the sauna for now given that the cost there can run well into the 5 figure range with the price of the unit, electrical work, and assembly. Happy to explore that with you further though if you'd like. Let us know what you think – feel free to send along any thoughts or questions!
"""


_EXTRACTION_SCHEMA = """\
Return a JSON object with this exact structure:
{
  "items": [
    {
      "line_item": "<category from the allowed list>",
      "material_name": "<exact name from the pricing guide>",
      "quantity": <number>,
      "sq_ft": <number or 0>,
      "labor_hours": <number or 0>,
      "dump_runs": <number or 0>,
      "notes": "<brief note>"
    }
  ],
  "warnings": ["<any items mentioned but not found in the pricing guide>"]
}
"""


class LLMService:
    """Translates natural-language project descriptions into structured data."""

    def __init__(self, config: LLMConfig) -> None:
        self._config = config
        self._client = OpenAI(api_key=config.openai_api_key)

    # ------------------------------------------------------------------
    # Prompt building
    # ------------------------------------------------------------------

    def build_context_message(
        self,
        pricing_guide: PricingGuide,
        line_item_names: list[str],
    ) -> str:
        """Build the context message injected into the thread.

        This is regenerated from the live sheet data every time the app
        starts or the user triggers a new estimation, so it's always fresh.
        """
        material_catalog = pricing_guide.to_prompt_text()

        context = (
            "## Available Materials (from pricing guide — use ONLY these names)\n"
            f"{material_catalog}\n\n"
            "## Allowed Line Item Categories\n"
            f"{', '.join(line_item_names)}\n\n"
            "## Output Format\n"
            f"{_EXTRACTION_SCHEMA}\n\n"
            "IMPORTANT RULES:\n"
            "- Only reference materials that appear in the pricing guide above.\n"
            "- Use the *exact* material name as listed.\n"
            "- Choose the most appropriate line item category for each material.\n"
            "- Estimate reasonable quantities based on the description.\n"
            "- If the user mentions an item not in the pricing guide, include it "
            "in the 'warnings' list.\n"
            "- Estimate labor hours and dump runs where appropriate.\n"
        )
        return context

    # ------------------------------------------------------------------
    # Interpretation
    # ------------------------------------------------------------------

    def interpret_description(
        self,
        description: str,
        pricing_guide: PricingGuide,
        line_item_names: list[str],
    ) -> dict[str, Any]:
        """Send the description to the LLM and return parsed JSON.

        Returns:
            Dict with keys 'items' (list of dicts) and 'warnings' (list of str).
        """
        context_msg = self.build_context_message(pricing_guide, line_item_names)

        messages = [
            {"role": "system", "content": self._config.system_prompt},
            {
                "role": "user",
                "content": (
                    "Here is the current pricing guide and configuration "
                    "for this landscaping business:\n\n"
                    f"{context_msg}"
                ),
            },
            {
                "role": "user",
                "content": (
                    "Please interpret the following project description and "
                    "return a structured estimate:\n\n"
                    f"{description}"
                ),
            },
        ]

        response = self._client.chat.completions.create(
            model=self._config.model_name,
            messages=messages,  # type: ignore[arg-type]
            temperature=self._config.temperature,
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content or "{}"
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {"items": [], "warnings": ["LLM returned invalid JSON."]}

        # Normalise keys
        if "items" not in parsed:
            parsed["items"] = []
        if "warnings" not in parsed:
            parsed["warnings"] = []

        return parsed

    # ------------------------------------------------------------------
    # Project writeup generation (client-facing proposal from line items)
    # ------------------------------------------------------------------

    def _estimate_to_writeup_context(self, estimate: ProjectEstimate, config: CostConfig) -> str:
        """Build a structured summary of the estimate for the LLM to turn into a writeup."""
        lines: list[str] = []
        lines.append("## Project")
        lines.append(f"Address: {estimate.address or '(not specified)'}")
        lines.append(f"Budget: ${estimate.project_budget:,.2f}")
        lines.append(f"Site access: {estimate.access_level}")
        lines.append(f"Grand total: ${estimate.grand_total(config):,.2f}")
        lines.append("")
        lines.append("## Sections and line items")
        current_section = ""
        for li in estimate.line_items:
            if li.section and li.section != current_section:
                current_section = li.section
                lines.append(f"\n## {current_section}")
            li_label = li.name
            if li.notes:
                li_label += f" — {li.notes}"
            lines.append(f"### {li_label}")
            if li.element_notes:
                lines.append(f"Description: {li.element_notes}")
            total_labor = li.labor_hours + sum(e.labor_hours for e in li.entries)
            if total_labor > 0 or li.dump_runs > 0:
                parts = []
                if total_labor > 0:
                    parts.append(f"Labor: {total_labor}h (${li.labor_cost(config):,.2f})")
                if li.dump_runs > 0:
                    parts.append(f"Dump runs: {li.dump_runs} (${li.dump_cost(config):,.2f})")
                lines.append("; ".join(parts))
            for e in li.entries:
                if e.length_feet and e.length_feet > 0:
                    u = unit_label(e.unit_hint) if e.unit_hint else "ft"
                    detail = f"- {e.material_name}: {e.quantity} pcs × {e.length_feet} {u}"
                elif e.area_value > 0:
                    u = unit_label(e.unit_hint) if e.unit_hint else "sq ft"
                    detail = f"- {e.material_name}: {e.area_value} {u}"
                    if e.quantity > 0:
                        detail += f", qty {e.quantity}"
                else:
                    detail = f"- {e.material_name}: qty {e.quantity}"
                if e.notes:
                    detail += f" — {e.notes}"
                if e.labor_hours > 0:
                    detail += f" ({e.labor_hours}h labor)"
                lines.append(detail)
            lines.append("")
        return "\n".join(lines).strip()

    def generate_project_writeup(
        self,
        estimate: ProjectEstimate,
        config: CostConfig,
    ) -> str:
        """Generate a client-facing project writeup from the estimate line items.

        Uses the example writeups as style/template; incorporates site access
        when it is not Easy. Returns plain text (no JSON).
        """
        context = self._estimate_to_writeup_context(estimate, config)

        system_content = (
            "You are helping a landscaping company write a friendly, professional "
            "email to a client that accompanies their project estimate. The email "
            "should explain the proposed work in narrative form, walking through "
            "each major element (cleanup, demo, hardscape, plants, irrigation, "
            "lighting, mulch, misc) as relevant to the line items. Match the tone "
            "and structure of the example writeups below: warm greeting, mention "
            "that the estimate is attached and broken into major elements "
            "(materials, labor, taxes), optional design/sketch attachment, then "
            "paragraphs that describe the work in a logical order, and a closing "
            "invitation to share thoughts or questions. Do NOT invent materials or "
            "quantities not in the estimate. Use the client's name only if a "
            "placeholder is provided; otherwise use a generic greeting like "
            "'Hi there,' or address to 'Client'."
        )

        user_content = (
            "Here are three example client writeups from this company:\n\n"
            f"{_WRITEUP_EXAMPLES}\n\n"
            "---\n\n"
            "Using the same tone and structure, write a single client writeup "
            "for the following estimate. "
        )
        if (estimate.access_level or "").strip().lower() not in ("easy", ""):
            user_content += (
                "IMPORTANT: Site access is marked as "
                f"\"{estimate.access_level}\" — include a sentence in the intro "
                "that factors in the difficult or restricted access for hauling "
                "materials (e.g. 'This also factors in the relatively difficult "
                "entryway to the back space for hauling materials etc.'). "
            )
        user_content += (
            "Base the narrative only on the line items and materials listed below. "
            "Use approximate dimensions or quantities from the estimate when they "
            "help (e.g. '~245SF patio', '~6'H fence'). Output only the writeup "
            "text, no preamble or labels.\n\n"
            f"{context}"
        )

        response = self._client.chat.completions.create(
            model=self._config.model_name,
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_content},
            ],
            temperature=self._config.temperature,
        )

        return (response.choices[0].message.content or "").strip()

