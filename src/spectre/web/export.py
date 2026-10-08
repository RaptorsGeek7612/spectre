"""Run exports: Markdown transcript and a standalone read-only HTML page (for sharing)."""

from __future__ import annotations

import html
from typing import Any

from spectre.costs import format_cost_table


def to_markdown(run: dict[str, Any]) -> str:
    """Markdown transcript of a run: request, brief, draft, final text and costs."""
    demo = " (démo)" if run.get("demo") else ""
    parts = [
        f"# Spectre — plaque N° {run['number']:04d}{demo}",
        "",
        f"*{run['created_at']}* · statut : {run['status']}",
        "",
        "## Demande",
        "",
        run["request"],
        "",
        "## Texte final (Warden)",
        "",
        run.get("final_text") or "_(aucun)_",
        "",
        "## Brouillon (Scribe)",
        "",
        run.get("draft") or "_(aucun)_",
        "",
        "## Brief (Scout)",
        "",
        run.get("brief") or "_(aucun)_",
    ]
    if run.get("usage"):
        parts += ["", "## Coûts", "", "```", format_cost_table(run["usage"]), "```"]
    if run.get("error"):
        parts += ["", "## Erreur", "", f"[{run.get('error_agent') or '?'}] {run['error']}"]
    return "\n".join(parts) + "\n"


_SHARE_CSS = """
:root{color-scheme:dark;--bg:#121315;--plate:#1b1c1f;--line:#34363b;--bone:#e9e4d8;--ash:#a8a49a;
--cyan:#4fc3f7;--green:#8bd450;--sodium:#ffd23f}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--bone);
font:16px/1.7 "Barlow Semi Condensed","Barlow",system-ui,sans-serif}
main{max-width:72ch;margin:0 auto;padding:48px 20px 80px}
.rail{display:flex;gap:6px;margin:0 0 28px}.rail i{display:block;width:2px;height:36px}
h1{font:600 14px/1.2 inherit;letter-spacing:.32em;text-transform:uppercase;color:var(--ash);
margin:0 0 6px}
h2{font-size:13px;letter-spacing:.24em;text-transform:uppercase;color:var(--ash);margin:40px 0 12px}
.final{background:var(--plate);border:1px solid var(--line);padding:28px;white-space:pre-wrap}
details{margin-top:16px;border-top:1px solid var(--line);padding-top:12px}
summary{cursor:pointer;color:var(--ash);letter-spacing:.18em;text-transform:uppercase;font-size:12px}
pre{white-space:pre-wrap;color:var(--ash)}
footer{margin-top:48px;color:var(--ash);font-size:12px;letter-spacing:.16em;text-transform:uppercase}
"""


def to_share_html(run: dict[str, Any]) -> str:
    """Self-contained read-only page of a run (no script, no external request)."""
    esc = html.escape
    demo = " · démo" if run.get("demo") else ""
    costs = format_cost_table(run["usage"]) if run.get("usage") else ""
    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Spectre — N° {run["number"]:04d}</title><style>{_SHARE_CSS}</style></head>
<body><main>
<div class="rail" aria-hidden="true"><i style="background:var(--cyan)"></i>
<i style="background:var(--green)"></i><i style="background:var(--sodium)"></i></div>
<h1>Spectre · plaque N° {run["number"]:04d}{demo}</h1>
<p>{esc(run["request"])}</p>
<h2>Texte final</h2>
<div class="final">{esc(run.get("final_text") or "")}</div>
<details><summary>Brouillon de Scribe</summary><pre>{esc(run.get("draft") or "")}</pre></details>
<details><summary>Brief de Scout</summary><pre>{esc(run.get("brief") or "")}</pre></details>
<details><summary>Coûts</summary><pre>{esc(costs)}</pre></details>
<footer>Produit par Spectre · Scout → Scribe → Warden · {esc(run["created_at"])}</footer>
</main></body></html>
"""
