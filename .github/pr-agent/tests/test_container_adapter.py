"""Contract tests with a fake PR-Agent API; no provider/network calls."""
import asyncio
from contextlib import nullcontext
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / ".github/pr-agent"))


class Settings:
    def __init__(self):
        self.values = {}

    def set(self, key, value):
        self.values[key.lower()] = value

    def get(self, key, default=None):
        return self.values.get(key.lower(), default)

    @property
    def config(self):
        return SimpleNamespace(publish_output=self.get("config.publish_output"))


class ContainerAdapterTests(unittest.TestCase):
    def run_adapter(self, publish, success=True):
        settings = Settings()
        calls = []

        class Agent:
            async def handle_request(self, url, commands, **kwargs):
                calls.append((url, commands, kwargs))
                settings.set("data", {"artifact": "Reporte de prueba"})
                return success

        modules = {
            "starlette_context": SimpleNamespace(request_cycle_context=lambda _: nullcontext()),
            "pr_agent.agent.pr_agent": SimpleNamespace(PRAgent=Agent),
            "pr_agent.config_loader": SimpleNamespace(get_settings=lambda: settings),
            "pr_agent.log": SimpleNamespace(setup_logger=lambda _: None),
            "pr_agent.tools": SimpleNamespace(pr_reviewer=SimpleNamespace(convert_to_markdown_v2=lambda *args, **kwargs: "")),
            "pr_agent.git_providers.github_provider": SimpleNamespace(GithubProvider=SimpleNamespace(publish_persistent_comment_full=lambda *args, **kwargs: None)),
        }
        with patch.dict(sys.modules, modules):
            spec = importlib.util.spec_from_file_location("container_adapter", ROOT / ".github/pr-agent/container_review.py")
            adapter = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(adapter)
        with tempfile.TemporaryDirectory() as output:
            paths = {
                "/trusted/.pr_agent.toml": ROOT / ".pr_agent.toml",
                "/trusted/project-context.md": ROOT / "docs/review/project-context.md",
                "/output/review.md": Path(output) / "review.md",
            }
            env = {"PR_AGENT_COMMAND": "review", "PR_AGENT_URL": "https://github.com/Netbel/vue-sortable/pull/123",
                   "CONFIG__MODEL": "zai/test", "PR_AGENT_PUBLISH": publish, "PR_AGENT_SHA": "abc123"}
            with patch.dict(os.environ, env, clear=True), patch.object(adapter, "Path", side_effect=lambda path: paths[path]):
                code = asyncio.run(adapter.main())
            report = paths["/output/review.md"].read_text(encoding="utf-8") if paths["/output/review.md"].exists() else None
        return settings, calls, code, report

    def test_report_only_disables_remote_config_and_propagates_errors(self):
        settings, calls, code, report = self.run_adapter("false")
        self.assertEqual(code, 0)
        self.assertIn("Reporte de prueba", report)
        self.assertIn("abc123", report)
        self.assertIn("/pull/123", report)
        self.assertFalse(settings.get("config.publish_output"))
        for key in ["use_repo_settings_file", "use_global_settings_file", "enable_per_directory_settings", "publish_output_progress", "enable_auto_approval"]:
            self.assertFalse(settings.get(f"config.{key}"), key)
        self.assertEqual(settings.get("config.fallback_models"), [])
        self.assertEqual(settings.get("config.repo_context_files"), [])
        self.assertEqual(settings.get("config.model"), "zai/test")
        self.assertIn("Vue", settings.get("pr_reviewer.extra_instructions"))
        self.assertFalse(settings.get("pr_reviewer.require_estimate_effort_to_review"))
        self.assertEqual(settings.get("pr_reviewer.review_heading"), "Revisión de la PR")
        self.assertEqual(calls[0][1], ["review"])
        self.assertTrue(calls[0][2]["propagate_tool_errors"])

    def test_publication_requires_explicit_true(self):
        settings, _, code, _ = self.run_adapter("true")
        self.assertEqual(code, 0)
        self.assertTrue(settings.get("config.publish_output"))

    def test_tool_failure_returns_failure_without_success_report(self):
        _, _, code, report = self.run_adapter("false", success=False)
        self.assertEqual(code, 1)
        self.assertIsNone(report)


if __name__ == "__main__":
    unittest.main()
