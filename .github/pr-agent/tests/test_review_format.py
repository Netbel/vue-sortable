import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("review_format", ROOT / ".github/pr-agent/review_format.py")
formatter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(formatter)


class ReviewFormatTests(unittest.TestCase):
    def test_uses_open_markdown_and_translates_fixed_labels(self):
        original = Mock(return_value=(
            "## Revisión de la PR 🔍\n\n"
            "### ⚠️ Risk level: Medium\n\n"
            "### 🧪 No relevant tests\n\n"
            "### 🔒 No security concerns identified\n\n"
            "### ⚡ Recommended focus areas for review\n\n#### \n"
            "[**Bloqueo de MCP**](https://github.com/example/pull/1/files#L23)\n\n"
            "El cambio impide procesar cobranzas en QA.\n"))
        render = formatter.spanish_review_renderer(original)
        result = render({"review": {}}, True, None, git_provider="provider", files=["file"])
        original.assert_called_once_with({"review": {}}, False, None, git_provider="provider", files=["file"])
        self.assertIn("Nivel de riesgo: Medio", result)
        self.assertIn("Aspectos a revisar", result)
        self.assertIn("Bloqueo de MCP", result)
        self.assertIn("El cambio impide procesar cobranzas en QA.", result)
        self.assertIn("https://github.com/example/pull/1/files#L23", result)
        for unwanted in ["Risk level", "No relevant tests", "No security concerns", "Recommended focus", "#### ", "<table", "<details"]:
            self.assertNotIn(unwanted, result)

    def test_preserves_model_prose_and_code_even_if_they_contain_english_labels(self):
        prose = 'El campo "Risk level" del contrato es obligatorio.'
        original = Mock(return_value="### 🔒 Security concerns\n\n" + prose + '\n\n```c#\nvar label = "No relevant tests";\n```\n')
        result = formatter.spanish_review_renderer(original)({"review": {}})
        self.assertIn("### 🔒 Observaciones de seguridad", result)
        self.assertIn(prose, result)
        self.assertIn('var label = "No relevant tests";', result)

    def test_removes_focus_heading_when_no_issues_were_rendered(self):
        original = Mock(return_value="## Revisión\n\n### ⚡ Recommended focus areas for review\n\n#### \n")
        result = formatter.spanish_review_renderer(original)({"review": {}})
        self.assertNotIn("Aspectos a revisar", result)

    def test_translates_other_risk_levels_and_presence_of_tests(self):
        for source, target in [("Low", "Bajo"), ("High", "Alto"), ("Unknown", "No informado")]:
            original = Mock(return_value=f"### ⚠️ Risk level: {source}\n\n### 🧪 PR contains tests\n")
            result = formatter.spanish_review_renderer(original)({"review": {}})
            self.assertIn(f"Nivel de riesgo: {target}", result)
            self.assertIn("La PR contiene pruebas", result)

    def test_preserves_internal_no_findings_publication_control(self):
        original = Mock(return_value="### ⚡ No major issues detected\n")
        result = formatter.spanish_review_renderer(original)({"review": {}})
        self.assertIn("No se detectaron problemas importantes", result)
        self.assertIn("<!-- No major issues detected -->", result)

    def test_empty_review_stays_empty(self):
        self.assertEqual(formatter.spanish_review_renderer(Mock(return_value=""))({}), "")

    def test_persistent_review_does_not_inject_english_update_header(self):
        original = Mock(return_value="updated")
        publish = formatter.without_review_update_header(original)
        result = publish("provider", "body", "header", update_header=True,
                         identity_marker="review-marker", require_agent_authorship=True)
        self.assertEqual(result, "updated")
        original.assert_called_once_with("provider", "body", "header", False,
                                         identity_marker="review-marker", require_agent_authorship=True)

    def test_other_persistent_comment_types_keep_their_header_behavior(self):
        original = Mock()
        formatter.without_review_update_header(original)("provider", "body", "header", True, "suggestions", False)
        original.assert_called_once_with("provider", "body", "header", True, "suggestions", False)
