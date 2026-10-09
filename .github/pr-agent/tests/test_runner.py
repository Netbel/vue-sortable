import importlib.util
import pathlib
import os
import json
import tempfile
import unittest
from unittest.mock import patch, Mock

ROOT = pathlib.Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("runner", ROOT / ".github/pr-agent/run_review.py")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class PreflightTests(unittest.TestCase):
    def test_provider_selection(self):
        for model, secret, target in [
            ("gemini/example", "GEMINI_API_KEY", "GOOGLE_AI_STUDIO__GEMINI_API_KEY"),
            ("zai/example", "ZAI_API_KEY", "ZAI__KEY"),
        ]:
            env = runner.provider_environment({"PR_AGENT_MODEL": model, secret: "test-secret"})
            self.assertEqual(env[target], "test-secret")
            self.assertEqual(env["CONFIG__MODEL"], model)
            self.assertNotIn("OPENAI_KEY", env)

    def test_missing_configuration_is_explicit(self):
        for env in [{}, {"PR_AGENT_MODEL": "gemini/example"}]:
            with self.assertRaises(runner.NotConfigured):
                runner.provider_environment(env)

    def test_rejects_unsupported_or_injected_model(self):
        for model in ["openai/test", "gemini/test\n--flag", "zai/test;echo secret"]:
            with self.assertRaises(ValueError):
                runner.provider_environment({"PR_AGENT_MODEL": model})

    def test_pr_number_cannot_inject_a_command_or_url(self):
        for number in ["0", "-1", "../1", "1;echo test", "1\n2"]:
            with self.assertRaises(ValueError):
                runner.pr_number(number)
        self.assertEqual(runner.pr_number("123"), 123)

    def test_only_current_open_ready_pr_targeting_this_repository_is_eligible(self):
        pr = {"state": "open", "draft": False,
              "base": {"repo": {"full_name": runner.REPOSITORY}},
              "head": {"sha": "abc", "repo": {"full_name": runner.REPOSITORY}}}
        self.assertIsNone(runner.skip_reason(pr, "abc"))
        self.assertIn("actualizada", runner.skip_reason(pr, "old"))
        pr["draft"] = True
        self.assertIn("borrador", runner.skip_reason(pr, "abc"))
        pr["draft"] = False
        pr["head"]["repo"] = {"full_name": "someone/fork"}
        self.assertIsNone(runner.skip_reason(pr, "abc"))
        pr["base"]["repo"]["full_name"] = "someone/other"
        self.assertIn("repositorio esperado", runner.skip_reason(pr, "abc"))
        pr["base"]["repo"]["full_name"] = runner.REPOSITORY
        pr["head"]["repo"] = None
        self.assertIsNotNone(runner.skip_reason(pr, "abc"))
        pr["state"] = "closed"
        self.assertIn("cerrada", runner.skip_reason(pr, "abc"))

    def test_docker_argv_contains_no_secrets_or_pr_checkout(self):
        args = runner.docker_command(ROOT, ROOT / "report", "review-test", {
            "GITHUB__USER_TOKEN": "very-secret", "ZAI__KEY": "also-secret"})
        self.assertNotIn("very-secret", " ".join(args))
        self.assertNotIn("also-secret", " ".join(args))
        self.assertIn(runner.IMAGE, args)
        self.assertTrue(any("/trusted,readonly" in arg for arg in args))
        self.assertNotIn("--privileged", args)
        self.assertNotIn("/var/run/docker.sock", " ".join(args))

    def test_linux_container_uses_runner_identity_for_private_bind_mounts(self):
        # TemporaryDirectory is 0700 on Linux. Root with all capabilities dropped
        # cannot traverse a directory owned by the runner's different UID.
        with patch.object(runner.os, "getuid", return_value=1001, create=True), \
                patch.object(runner.os, "getgid", return_value=1002, create=True):
            args = runner.docker_command(ROOT, ROOT / "report", "test", {})
        self.assertIn("--user", args)
        self.assertEqual(args[args.index("--user") + 1], "1001:1002")
        self.assertIn("--cap-drop=ALL", args)

    def test_automatic_disabled_never_reads_pr_or_starts_docker(self):
        with patch.dict(os.environ, {"GITHUB_EVENT_NAME": "pull_request_target"}, clear=True), \
                patch.object(runner, "get_pr") as get_pr, patch.object(runner.subprocess, "run") as run:
            self.assertEqual(runner.main([]), 0)
            get_pr.assert_not_called()
            run.assert_not_called()

    def test_missing_key_fails_instead_of_reporting_a_successful_skip(self):
        env = {"GITHUB_EVENT_NAME": "pull_request_target", "PR_AGENT_ENABLED": "true",
               "PR_AGENT_MODEL": "gemini/test"}
        with patch.dict(os.environ, env, clear=True), patch.object(runner, "get_pr") as get_pr:
            with self.assertRaises(runner.NotConfigured):
                runner.main([])
            get_pr.assert_not_called()
            os.environ["GITHUB_EVENT_NAME"] = "local"
            with self.assertRaises(runner.NotConfigured):
                runner.main(["--pr-number", "123"])

    def test_local_defaults_to_report_only_and_both_commands(self):
        env = {"GITHUB_TOKEN": "fake-token", "PR_AGENT_MODEL": "gemini/test", "GEMINI_API_KEY": "fake-key"}
        pr = {"state": "open", "draft": False,
              "base": {"repo": {"full_name": runner.REPOSITORY}},
              "head": {"sha": "abc", "repo": {"full_name": runner.REPOSITORY}}}
        with patch.dict(os.environ, env, clear=True), patch.object(runner, "get_pr", return_value=pr), \
                patch.object(runner, "execute", return_value=0) as execute:
            self.assertEqual(runner.main(["--pr-number", "123"]), 0)
            self.assertEqual(execute.call_args.args[:3], (123, ["review", "improve"], False))

    def test_failed_container_fails_job_and_is_cleaned_up(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.dict(os.environ, {"GITHUB_TOKEN": "fake"}, clear=True), \
                patch.object(runner, "get_pr", return_value={}), \
                patch.object(runner, "skip_reason", return_value=None), \
                patch.object(runner, "ROOT", pathlib.Path(folder)), \
                patch.object(runner.shutil, "copy2"), \
                patch.object(runner.subprocess, "run", return_value=Mock(returncode=1)) as run:
            self.assertEqual(runner.execute(123, ["review", "improve"], False, {}, "abc"), 1)
            self.assertEqual(run.call_count, 2)  # review + cleanup, never improve after failure
            self.assertEqual(run.call_args_list[1].args[0][:3], ["docker", "rm", "-f"])

    def test_actions_bot_identity_is_forwarded_to_container(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.dict(os.environ, {"GITHUB_TOKEN": "fake", "GITHUB_ACTIONS": "true"}, clear=True), \
                patch.object(runner, "get_pr", return_value={}), \
                patch.object(runner, "skip_reason", return_value=None), \
                patch.object(runner, "ROOT", pathlib.Path(folder)), \
                patch.object(runner.shutil, "copy2"), \
                patch.object(runner.subprocess, "run", return_value=Mock(returncode=0)) as run:
            self.assertEqual(runner.execute(123, ["review"], True, {}, "abc"), 0)
            docker_args = run.call_args_list[0].args[0]
            self.assertIn("GITHUB_ACTIONS", docker_args)
            self.assertEqual(run.call_args_list[0].kwargs["env"]["GITHUB_ACTIONS"], "true")

    def test_runs_use_separate_output_directories(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.dict(os.environ, {"GITHUB_TOKEN": "fake"}, clear=True), \
                patch.object(runner, "get_pr", return_value={}), \
                patch.object(runner, "skip_reason", return_value=None), \
                patch.object(runner, "ROOT", pathlib.Path(folder)), \
                patch.object(runner.shutil, "copy2"), \
                patch.object(runner.subprocess, "run", return_value=Mock(returncode=0)) as run:
            runner.execute(123, ["review"], False, {}, "abc")
            runner.execute(456, ["review"], False, {}, "def")
            mounts = [next(arg for arg in call.args[0] if "target=/output" in arg)
                      for call in run.call_args_list if call.args[0][1] == "run"]
            self.assertNotEqual(mounts[0], mounts[1])

    def test_dispatch_false_string_does_not_publish(self):
        with tempfile.TemporaryDirectory() as folder:
            event = pathlib.Path(folder) / "event.json"
            event.write_text(json.dumps({"inputs": {"pr_number": "123", "command": "review", "publish": "false"}}))
            env = {"GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_EVENT_PATH": str(event),
                   "GITHUB_TOKEN": "fake", "PR_AGENT_MODEL": "zai/test", "ZAI_API_KEY": "fake"}
            with patch.dict(os.environ, env, clear=True), \
                    patch.object(runner, "get_pr", return_value={"head": {"sha": "abc"}}), \
                    patch.object(runner, "skip_reason", return_value=None), \
                    patch.object(runner, "execute", return_value=0) as execute:
                self.assertEqual(runner.main([]), 0)
                self.assertIs(execute.call_args.args[2], False)

    def test_automatic_events_review_ready_prs_but_never_drafts_or_stale_heads(self):
        for action in ["opened", "reopened", "ready_for_review", "synchronize", "edited"]:
            for draft, current_sha in [(False, "abc"), (True, "abc"), (False, "new")]:
                with self.subTest(action=action, draft=draft, sha=current_sha), tempfile.TemporaryDirectory() as folder:
                    event = pathlib.Path(folder) / "event.json"
                    event.write_text(json.dumps({"action": action, "number": 123,
                                                 "pull_request": {"head": {"sha": "abc"}}}))
                    env = {"GITHUB_EVENT_NAME": "pull_request_target", "GITHUB_EVENT_PATH": str(event),
                           "PR_AGENT_ENABLED": "true", "GITHUB_TOKEN": "fake",
                           "PR_AGENT_MODEL": "gemini/test", "GEMINI_API_KEY": "fake"}
                    pr = {"state": "open", "draft": draft,
                          "base": {"repo": {"full_name": runner.REPOSITORY}},
                          "head": {"sha": current_sha, "repo": {"full_name": runner.REPOSITORY}}}
                    with patch.dict(os.environ, env, clear=True), \
                            patch.object(runner, "get_pr", return_value=pr), \
                            patch.object(runner, "execute", return_value=0) as execute:
                        self.assertEqual(runner.main([]), 0)
                        if draft or current_sha != "abc":
                            execute.assert_not_called()
                        else:
                            self.assertEqual(execute.call_args.args[:3], (123, ["review", "improve"], True))
                            self.assertEqual(execute.call_args.args[4], "abc")

    def test_returning_to_draft_between_tools_stops_further_analysis(self):
        ready = {"state": "open", "draft": False,
                 "base": {"repo": {"full_name": runner.REPOSITORY}},
                 "head": {"sha": "abc", "repo": {"full_name": runner.REPOSITORY}}}
        with tempfile.TemporaryDirectory() as folder, \
                patch.dict(os.environ, {"GITHUB_TOKEN": "fake"}, clear=True), \
                patch.object(runner, "get_pr", side_effect=[ready, {**ready, "draft": True}]), \
                patch.object(runner, "ROOT", pathlib.Path(folder)), \
                patch.object(runner.shutil, "copy2"), \
                patch.object(runner.subprocess, "run", return_value=Mock(returncode=0)) as run:
            self.assertEqual(runner.execute(123, ["review", "improve"], True, {}, "abc"), 0)
            self.assertEqual(run.call_count, 2)  # review and cleanup; no improve


if __name__ == "__main__":
    unittest.main()
