"""LLM service for interpreting text descriptions into structured estimates."""

from __future__ import annotations

import json
from typing import Any

import streamlit as st
from openai import OpenAI

from config import LLMConfig
from models import PricingGuide


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

