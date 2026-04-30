"""Unit tests for app-level state helper functions."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import app
from models import ProjectEstimate


class AppHelpersTests(unittest.TestCase):
    def test_get_estimate_falls_back_on_invalid_session_payload(self) -> None:
        with patch.dict(app.st.session_state, {"estimate": {"bad": "shape"}}, clear=True):
            est = app._get_estimate([])
            self.assertIsInstance(est, ProjectEstimate)

    def test_request_load_estimate_sets_pending_import_when_selected(self) -> None:
        with patch.dict(app.st.session_state, {"load_estimate_select": "Estimate - Test"}, clear=True):
            app._request_load_estimate()
            self.assertEqual(app.st.session_state["_pending_import"], "Estimate - Test")

    def test_clear_estimate_session_state_removes_prefixed_keys(self) -> None:
        initial = {
            "estimate": {"line_items": []},
            "li_notes_abc": "x",
            "li_elem_def": "y",
            "cart_notes_x": "z",
            "unrelated_key": "keep",
        }
        with patch.dict(app.st.session_state, initial, clear=True):
            app._clear_estimate_session_state()
            self.assertNotIn("estimate", app.st.session_state)
            self.assertNotIn("li_notes_abc", app.st.session_state)
            self.assertNotIn("li_elem_def", app.st.session_state)
            self.assertNotIn("cart_notes_x", app.st.session_state)
            self.assertEqual(app.st.session_state["unrelated_key"], "keep")


if __name__ == "__main__":
    unittest.main()
