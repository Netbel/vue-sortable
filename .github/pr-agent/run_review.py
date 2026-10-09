"""Trusted host runner for Actions or a Linux CI agent with Python 3.11+ and Docker."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import urllib.request
import uuid

REPOSITORY = "Netbel/vue-sortable"
IMAGE = "pragent/pr-agent:0.47.0@sha256:7d98954c29289846a08faf00aaea0f1f1375b1676cd8a2ed303e0af07010af7a"
ROOT = Path(__file__).resolve().parents[2]


class NotConfigured(ValueError):
    pass


def provider_environment(env):
    model = env.get("PR_AGENT_MODEL", "").strip()
    if not model:
        raise NotConfigured("Falta la variable PR_AGENT_MODEL.")
    if not re.fullmatch(r"(?:gemini|zai)/[A-Za-z0-9._:-]+", model):
        raise ValueError("PR_AGENT_MODEL debe ser gemini/<modelo> o zai/<modelo>.")
    source, target = ("GEMINI_API_KEY", "GOOGLE_AI_STUDIO__GEMINI_API_KEY") if model.startswith("gemini/") else ("ZAI_API_KEY", "ZAI__KEY")
    if not env.get(source, "").strip():
        raise NotConfigured(f"Falta el secreto {source}.")
    return {"CONFIG__MODEL": model, target: env[source]}


def pr_number(value):
    if not re.fullmatch(r"[1-9][0-9]*", str(value)):
        raise ValueError("El número de PR debe ser un entero positivo.")
    return int(value)


def skip_reason(pr, expected_sha=None):
    if pr.get("state") != "open":
        return "La PR está cerrada."
    if pr.get("draft"):
        return "La PR está en borrador."
    if (pr.get("base", {}).get("repo") or {}).get("full_name") != REPOSITORY:
        return "La PR no pertenece al repositorio esperado."
    if not (pr.get("head", {}).get("repo") or {}).get("full_name"):
        return "La rama de la PR ya no está disponible."
    if expected_sha and pr["head"]["sha"] != expected_sha:
        return "La PR fue actualizada; se omite el evento anterior."
    return None


def get_pr(number, token):
    request = urllib.request.Request(
        f"https://api.github.com/repos/{REPOSITORY}/pulls/{number}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "vue-sortable-pr-agent"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def docker_command(trusted, output, name, env):
    args = ["docker", "run", "--rm", "--name", name,
            "--cap-drop=ALL", "--security-opt=no-new-privileges", "--memory=4g", "--cpus=2",
            "--mount", f"type=bind,source={trusted},target=/trusted,readonly",
            "--mount", f"type=bind,source={output},target=/output"]
    if hasattr(os, "getuid") and hasattr(os, "getgid"):
        # Linux temp directories are private to their creator. With DAC capabilities
        # dropped, container root cannot read the runner-owned 0700 bind mount.
        args.extend(["--user", f"{os.getuid()}:{os.getgid()}"])
    for key in sorted(env):
        args.extend(["-e", key])  # Only names in argv; values come from the child environment.
    return args + ["--entrypoint", "python", IMAGE, "/trusted/container_review.py"]


def report(message):
    print(message, flush=True)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as stream:
            stream.write(message + "\n\n")


def execute(number, commands, publish, env, expected_sha):
    output = ROOT / "pr-agent-results" / f"pr-{number}-{uuid.uuid4().hex}"
    output.mkdir(parents=True)
    report(f"Directorio de reportes de esta ejecución: `{output}`.")
    env = {**env, "GITHUB__USER_TOKEN": os.environ["GITHUB_TOKEN"],
           "PR_AGENT_URL": f"https://github.com/{REPOSITORY}/pull/{number}",
           "PR_AGENT_SHA": expected_sha,
           "PR_AGENT_PUBLISH": str(publish).lower()}
    if os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
        # The workflow token cannot GET /user; PR-Agent uses this to identify its bot comments.
        env["GITHUB_ACTIONS"] = "true"
    with tempfile.TemporaryDirectory(prefix="pr-agent-") as folder:
        trusted = Path(folder)
        for source in [ROOT / ".pr_agent.toml", ROOT / "docs/review/project-context.md",
                       ROOT / ".github/pr-agent/review_format.py",
                       ROOT / ".github/pr-agent/container_review.py"]:
            shutil.copy2(source, trusted / source.name)
        for command in commands:
            reason = skip_reason(get_pr(number, env["GITHUB__USER_TOKEN"]), expected_sha)
            if reason:
                report(f"PR-Agent omitido: {reason}")
                return 0
            child_env = {**env, "PR_AGENT_COMMAND": command}
            name = "vue-sortable-pr-agent-" + uuid.uuid4().hex
            try:
                result = subprocess.run(docker_command(trusted, output, name, child_env),
                                        env={**os.environ, **child_env}, timeout=720, check=False)
            finally:
                # Also clean up on timeout: killing docker's client alone leaves the container running.
                subprocess.run(["docker", "rm", "-f", name], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=30, check=False)
            if result.returncode:
                report(f"PR-Agent falló en {command}; revisar los logs. No equivale a una revisión aprobada.")
                return 1
            report(f"PR #{number}: {command} completado. Publicación: {publish}. SHA observado: `{expected_sha}`.")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pr-number", type=pr_number)
    parser.add_argument("--command", choices=["review", "improve", "both"], default="both")
    parser.add_argument("--publish", action="store_true", help="Publicar comentarios en la PR (por defecto: solo reporte local)")
    args = parser.parse_args(argv)
    event_name = os.environ.get("GITHUB_EVENT_NAME", "local")
    event = {}
    if os.environ.get("GITHUB_EVENT_PATH"):
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    automatic = event_name == "pull_request_target"
    if event_name not in {"local", "workflow_dispatch", "pull_request_target"}:
        raise ValueError("Evento no permitido.")
    if os.environ.get("GITHUB_REPOSITORY", REPOSITORY) != REPOSITORY:
        raise ValueError("Repositorio no permitido.")
    if automatic and os.environ.get("PR_AGENT_ENABLED", "").lower() != "true":
        report("PR-Agent omitido: PR_AGENT_ENABLED no es true. Se puede validar manualmente.")
        return 0
    env = provider_environment(os.environ)
    if not os.environ.get("GITHUB_TOKEN"):
        raise ValueError("Falta GITHUB_TOKEN.")
    if automatic:
        number = pr_number(event["number"])
        expected_sha = event["pull_request"]["head"]["sha"]
        command, publish = "both", True
    elif event_name == "workflow_dispatch":
        inputs = event["inputs"]
        number = pr_number(inputs["pr_number"])
        command, publish = inputs.get("command", "both"), str(inputs.get("publish", "false")).lower() == "true"
        expected_sha = None
    else:
        if args.pr_number is None:
            parser.error("--pr-number es obligatorio fuera de GitHub Actions")
        number, command, publish, expected_sha = args.pr_number, args.command, args.publish, None
    if command not in {"review", "improve", "both"}:
        raise ValueError("Comando no permitido.")
    pr = get_pr(number, os.environ["GITHUB_TOKEN"])
    reason = skip_reason(pr, expected_sha)
    if reason:
        report(f"PR-Agent omitido: {reason}")
        return 0
    return execute(number, ["review", "improve"] if command == "both" else [command],
                   publish, env, pr["head"]["sha"])


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        # Do not print request objects, environment, or exception payloads containing credentials.
        report(f"PR-Agent no pudo ejecutarse ({type(error).__name__})." +
               (f" {error}" if isinstance(error, ValueError) else " Revisar configuración, acceso a GitHub y Docker."))
        raise SystemExit(1)
