"""Localize the enabled review fields of pinned PR-Agent 0.47.0."""
from functools import wraps


LABELS = {
    "### 🧪 No relevant tests": "### 🧪 No se identificaron pruebas relevantes en el diff",
    "### 🧪 PR contains tests": "### 🧪 La PR contiene pruebas",
    "### 🔒 No security concerns identified": "### 🔒 No se identificaron problemas de seguridad",
    "### 🔒 Security concerns": "### 🔒 Observaciones de seguridad",
    "### ⚡ Recommended focus areas for review": "### ⚡ Aspectos a revisar",
    "### ⚡ No major issues detected": "### ⚡ No se detectaron problemas importantes",
}
RISK_LEVELS = {"Low": "Bajo", "Medium": "Medio", "High": "Alto", "Unknown": "No informado"}


def without_review_update_header(original):
    @wraps(original)
    def publish(provider, body, initial_header, update_header=True, *args, **kwargs):
        name = kwargs.get("name", args[0] if args else "review")
        if name == "review":
            update_header = False  # Upstream injects an English sentence after rendering.
        return original(provider, body, initial_header, update_header, *args, **kwargs)
    return publish


def spanish_review_renderer(original):
    @wraps(original)
    def render(output_data, gfm_supported=True, incremental_review=None, git_provider=None, files=None):
        # Use upstream's plain Markdown renderer: findings remain visible, with
        # verified line links, without <details> nested inside an HTML table.
        markdown = original(output_data, False, incremental_review, git_provider=git_provider, files=files)
        lines = []
        fence = None
        no_findings = False
        for line in markdown.splitlines():
            stripped = line.lstrip()
            if stripped.startswith(("```", "~~~")):
                marker = stripped[:3]
                if fence is None:
                    fence = marker
                elif fence == marker:
                    fence = None
                lines.append(line)
                continue
            if fence is not None:
                lines.append(line)
                continue
            if line.strip() == "####":  # Empty heading emitted by upstream.
                continue
            if line == "### ⚡ No major issues detected":
                no_findings = True
            if line.startswith("### ⚠️ Risk level: "):
                value = line.removeprefix("### ⚠️ Risk level: ")
                line = "### ⚠️ Nivel de riesgo: " + RISK_LEVELS.get(value, value)
            lines.append(LABELS.get(line, line))
        result = "\n".join(lines).rstrip()
        focus_heading = "### ⚡ Aspectos a revisar"
        if focus_heading in result and not result.split(focus_heading, 1)[1].strip():
            result = result.split(focus_heading, 1)[0].rstrip()
        if no_findings:
            # PR-Agent uses this literal to suppress no-findings publication.
            # Keep its control marker out of the visible Spanish report.
            result += "\n\n<!-- No major issues detected -->"
        return result + "\n" if result else ""
    return render
