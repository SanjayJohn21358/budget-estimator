"""Unit tests for LLM service request/response handling."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from config import CostConfig, LLMConfig
from models import LineItem, LineItemEntry, Material, PricingGuide, ProjectEstimate
from services.llm import LLMService


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, payloads: list[str]) -> None:
        self._payloads = payloads
        self.calls: list[dict] = []

    def create(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(kwargs)
        return _FakeResponse(self._payloads.pop(0))


class _FakeChat:
    def __init__(self, payloads: list[str]) -> None:
        self.completions = _FakeCompletions(payloads)


class _FakeOpenAI:
    def __init__(self, api_key: str, payloads: list[str] | None = None) -> None:
        self.api_key = api_key
        self.chat = _FakeChat(payloads or ["{}"])


class LLMServiceTests(unittest.TestCase):
    @patch("services.llm.OpenAI")
    def test_interpret_description_normalizes_missing_keys(self, mock_openai) -> None:
        fake = _FakeOpenAI("k", payloads=['{"items":[{"line_item":"Cleanup"}]}'])
        mock_openai.return_value = fake
        svc = LLMService(LLMConfig(openai_api_key="k"))

        out = svc.interpret_description(
            description="test",
            pricing_guide=PricingGuide(categories={}),
            line_item_names=["Cleanup"],
        )
        self.assertIn("items", out)
        self.assertIn("warnings", out)
        self.assertEqual(out["warnings"], [])

    @patch("services.llm.OpenAI")
    def test_interpret_description_invalid_json_fallback(self, mock_openai) -> None:
        fake = _FakeOpenAI("k", payloads=["not-json"])
        mock_openai.return_value = fake
        svc = LLMService(LLMConfig(openai_api_key="k"))

        out = svc.interpret_description(
            description="test",
            pricing_guide=PricingGuide(categories={}),
            line_item_names=["Cleanup"],
        )
        self.assertEqual(out["items"], [])
        self.assertTrue(out["warnings"])

    @patch("services.llm.OpenAI")
    def test_generate_pdf_line_descriptions_coerces_values_to_strings(self, mock_openai) -> None:
        fake = _FakeOpenAI("k", payloads=['{"Cleanup":123,"Design":true}'])
        mock_openai.return_value = fake
        svc = LLMService(LLMConfig(openai_api_key="k"))
        estimate = ProjectEstimate(
            line_items=[LineItem(name="Cleanup", entries=[LineItemEntry(material_name="Mulch", quantity=1)])]
        )
        out = svc.generate_pdf_line_descriptions(estimate, CostConfig())
        self.assertEqual(out["Cleanup"], "123")
        self.assertEqual(out["Design"], "True")

    @patch("services.llm.OpenAI")
    def test_build_context_message_includes_categories_and_materials(self, mock_openai) -> None:
        fake = _FakeOpenAI("k")
        mock_openai.return_value = fake
        svc = LLMService(LLMConfig(openai_api_key="k"))
        guide = PricingGuide(
            categories={"Plants": [Material(name="Mulch", category="Plants", retail_with_tax=2.0)]}
        )
        ctx = svc.build_context_message(guide, ["Cleanup", "Design"])
        self.assertIn("Allowed Line Item Categories", ctx)
        self.assertIn("Cleanup, Design", ctx)
        self.assertIn("Mulch", ctx)

    @patch("services.llm.OpenAI")
    def test_generate_writeup_adds_access_instruction_for_non_easy(self, mock_openai) -> None:
        fake = _FakeOpenAI("k", payloads=["Generated writeup"])
        mock_openai.return_value = fake
        svc = LLMService(LLMConfig(openai_api_key="k"))

        estimate = ProjectEstimate(access_level="Difficult", line_items=[LineItem(name="Cleanup")])
        out = svc.generate_project_writeup(estimate, CostConfig())
        self.assertEqual(out, "Generated writeup")
        call = fake.chat.completions.calls[0]
        user_message = call["messages"][1]["content"]
        self.assertIn("Site access is marked as", user_message)


if __name__ == "__main__":
    unittest.main()
