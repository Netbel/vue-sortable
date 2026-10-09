"""Adapter for the pinned PR-Agent 0.47.0 API; executed inside its container only."""
import asyncio
import copy
import os
from pathlib import Path
import tomllib

from starlette_context import request_cycle_context
from pr_agent.agent.pr_agent import PRAgent
from pr_agent.config_loader import get_settings
from pr_agent.log import setup_logger
from pr_agent.tools import pr_reviewer
from pr_agent.git_providers.github_provider import GithubProvider
from review_format import spanish_review_renderer, without_review_update_header


async def main():
    setup_logger("INFO")
    pr_reviewer.convert_to_markdown_v2 = spanish_review_renderer(pr_reviewer.convert_to_markdown_v2)
    GithubProvider.publish_persistent_comment_full = without_review_update_header(GithubProvider.publish_persistent_comment_full)
    command = os.environ["PR_AGENT_COMMAND"]
    if command not in {"review", "improve"}:
        raise ValueError("Unsupported command")
    with request_cycle_context({"settings": copy.deepcopy(get_settings())}):
        settings = get_settings()
        config = tomllib.loads(Path("/trusted/.pr_agent.toml").read_text(encoding="utf-8"))
        for section, values in config.items():
            for key, value in values.items():
                settings.set(f"{section}.{key}", value)
        context = Path("/trusted/project-context.md").read_text(encoding="utf-8")
        for section in ("pr_reviewer", "pr_code_suggestions"):
            key = f"{section}.extra_instructions"
            settings.set(key, settings.get(key, "") + "\n\nContexto del proyecto:\n" + context)
        # Host controls these values. Never load settings/prompts from the PR being reviewed.
        for key, value in {
            "config.model": os.environ["CONFIG__MODEL"], "config.fallback_models": [],
            "config.use_repo_settings_file": False, "config.use_global_settings_file": False,
            "config.enable_per_directory_settings": False, "config.extra_config_url": "",
            "config.repo_context_files": [], "config.cli_mode": True,
            "config.publish_output": os.environ["PR_AGENT_PUBLISH"] == "true",
            "config.publish_output_progress": False, "config.enable_auto_approval": False,
        }.items():
            settings.set(key, value)
        success = await PRAgent().handle_request(os.environ["PR_AGENT_URL"], [command],
                                                 propagate_tool_errors=True)
        if not success:
            return 1
        published = settings.config.publish_output
        artifact = settings.get("data", {}).get("artifact", "")
        text = str(artifact) if artifact else (
            "Ejecución completada. Consultar los comentarios de la PR si hubo hallazgos."
            if published else "Ejecución completada sin contenido de reporte. Consultar la cobertura y los logs; no implica ausencia de defectos.")
        header = (f"# PR-Agent: {command}\n\nPR: {os.environ['PR_AGENT_URL']}\n\n"
                  f"SHA observado al iniciar: `{os.environ['PR_AGENT_SHA']}`\n\n"
                  f"Publicación habilitada: {published}\n\n")
        Path(f"/output/{command}.md").write_text(header + text + "\n", encoding="utf-8")
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
