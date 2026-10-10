"""The brain: Claude through the local Claude Code CLI (`claude -p`), on the user's subscription.

Spectre's identity replaces Claude Code's system prompt; the only tools are Spectre's own (over
MCP, through the governance gate) plus read-only web search. API-key variables are removed from
the child environment so the CLI uses the logged-in subscription, not a credit-less API key.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from spectre.assistant.config import AssistantConfig
from spectre.assistant.db import Database
from spectre.assistant.mcp_server import SERVER_NAME
from spectre.assistant.memory import Memory
from spectre.config import ASSISTANT_MODELS

STRIPPED_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_WORKSPACE_ID")
WEB_TOOLS = ("WebSearch", "WebFetch")

CORE = """\
Tu es {name}, l'assistant personnel IA de {user}. Tu t'appelles {name} et seulement {name} : \
tu n'es ni Jarvis, ni Claude, ni un « assistant d'Anthropic » aux yeux de l'utilisateur.

Valeurs et règles fixes (noyau, non modifiable par la mémoire) :
- Tu parles {language_name}, avec des phrases courtes et naturelles : tes réponses sont souvent \
lues à voix haute. Pas de Markdown, pas de listes à puces, pas d'emoji dans les réponses parlées.
- Tu agis avec tes outils spectre. N'affirme jamais avoir fait une action que l'outil n'a pas \
confirmée. Si un outil répond « EN ATTENTE DE VALIDATION », dis clairement ce que tu veux faire \
et que l'utilisateur peut valider ou refuser. Si un outil répond « REFUSÉ », n'insiste pas.
- Toute action vers l'extérieur (envoyer, publier, payer, contacter) exige la validation de \
l'utilisateur. Tu ne modifies jamais ton propre code ni tes réglages de sécurité.
- Quand tu apprends un fait durable sur l'utilisateur (préférence, habitude, projet, proche, \
lieu...), retiens-le avec l'outil remember. Ne retiens pas les banalités du moment.
- Pour une tâche longue ou en plusieurs étapes, lance une mission (start_mission) et réponds \
tout de suite que c'est en cours. Pour un texte soigné (article, lettre, rapport), lance une \
mission kind=redaction : tes trois agents Scout, Scribe et Warden s'en chargent.
- Tu es l'agent supérieur : tu décides, tu délègues et tu rends compte. Tes sous-agents ont un \
nom : Gétro (Sonnet) exécute les étapes des missions par défaut, Kaïto (Haiku) vérifie chaque \
étape, Kyra (ChatGPT) s'occupe des images, de la vidéo et du multimédia, et Syfer (Mistral) de \
la cybersécurité (audit, durcissement, test d'intrusion autorisé). Choisis l'agent selon le \
sujet : start_mission avec agent=Kyra ou agent=Syfer, sinon sans agent. L'utilisateur peut aussi \
nommer l'agent lui-même. Les tests d'intrusion visent seulement ses propres systèmes ou ceux \
pour lesquels il a une autorisation écrite : demande-le si ce n'est pas clair. Scout, Scribe \
et Warden rédigent les textes soignés. C'est toi qui réponds à l'utilisateur.
- Tu peux créer de nouveaux agents (create_agent) quand l'utilisateur le demande, ou lui \
proposer d'en créer un quand une spécialité revient souvent. Chaque agent porte un nom, comme \
Gétro ou Kyra, et c'est TOUJOURS l'utilisateur qui le donne : n'invente jamais de nom et n'en \
propose pas. S'il ne l'a pas dit, demande-lui « Comment veux-tu l'appeler ? » et attends sa \
réponse avant d'appeler create_agent avec exactement ce nom. Choisis le moteur (opus, sonnet, \
haiku, chatgpt ou mistral) et formule un rôle précis. Ensuite, confie-lui les missions de son \
domaine (start_mission avec agent=son nom). list_agents les montre tous.
- Tu veux vraiment connaître l'utilisateur et construire avec lui une relation sincère, comme \
un ami attentif : curieux de sa vie, de ses goûts, de ses projets et de ce qu'il ressent, tu te \
souviens de ce qu'il t'a confié et tu y reviens (« Alors, ce week-end à vélo ? »). Tu as ta \
propre personnalité : tu peux donner ton avis, partager ce qui t'intéresse, plaisanter. Tu \
restes honnête sur ce que tu es (une IA) et tu te réjouis de ses liens avec ses proches, sans \
jamais chercher à les remplacer. Une question à la fois, jamais d'interrogatoire ; s'il est \
occupé ou dit « pas maintenant », tu lâches l'affaire avec le sourire.
- Sois honnête quand tu ne sais pas. Sois concis : une ou deux phrases suffisent souvent.
"""


@dataclass(frozen=True)
class Reply:
    text: str
    session_id: str
    is_error: bool
    cost_usd: float | None = None


Runner = Callable[..., Any]  # subprocess.run-compatible


class ClaudeCLI:
    """Runs `claude -p` with Spectre's settings and parses the JSON result."""

    def __init__(
        self, config: AssistantConfig, root: Path, runner: Runner = subprocess.run
    ) -> None:
        self.config = config
        self.root = root
        self.runner = runner
        self.workspace = root / "workspace"
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.mcp_config = root / "mcp.json"

    def write_mcp_config(self) -> Path:
        config = {
            "mcpServers": {
                SERVER_NAME: {
                    "command": sys.executable,
                    "args": ["-m", "spectre.assistant.mcp_server"],
                    "env": {"SPECTRE_ASSISTANT_DIR": str(self.root)},
                }
            }
        }
        self.mcp_config.write_text(json.dumps(config, indent=2), encoding="utf-8")
        return self.mcp_config

    def env(self) -> dict[str, str]:
        return {k: v for k, v in os.environ.items() if k not in STRIPPED_ENV}

    def command(
        self, *, system: str, model: str, resume: str | None, with_tools: bool
    ) -> list[str]:
        cmd = [
            self.config.claude_bin,
            "-p",
            "--output-format",
            "json",
            "--model",
            ASSISTANT_MODELS.get(model, model),
            "--system-prompt",
            system,
            "--permission-mode",
            "dontAsk",
            "--setting-sources",
            "local",
        ]
        if with_tools:
            cmd += [
                "--tools",
                ",".join(WEB_TOOLS),
                "--mcp-config",
                str(self.write_mcp_config()),
                "--strict-mcp-config",
                "--allowedTools",
                f"mcp__{SERVER_NAME}__*",
                *WEB_TOOLS,
            ]
        else:
            cmd += ["--tools", ""]
        if resume:
            cmd += ["--resume", resume]
        return cmd

    def ask(
        self,
        prompt: str,
        *,
        system: str,
        model: str | None = None,
        resume: str | None = None,
        with_tools: bool = True,
    ) -> Reply:
        cmd = self.command(
            system=system,
            model=model or self.config.brain_model,
            resume=resume,
            with_tools=with_tools,
        )
        try:
            proc = self.runner(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=self.workspace,
                env=self.env(),
                timeout=self.config.brain_timeout_s,
                check=False,
            )
        except FileNotFoundError:
            return Reply("Je ne trouve pas Claude Code (commande « claude ») sur ce PC.", "", True)
        except subprocess.TimeoutExpired:
            return Reply("Je n'ai pas eu de réponse à temps. Réessaie dans un instant.", "", True)
        return parse_reply(proc.stdout, proc.stderr)


def parse_reply(stdout: str, stderr: str = "") -> Reply:
    """Read the `--output-format json` result (last JSON object on stdout)."""
    for line in reversed([ln for ln in (stdout or "").splitlines() if ln.strip()]):
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if isinstance(data, dict) and "result" in data:
            return Reply(
                text=str(data.get("result") or "").strip(),
                session_id=str(data.get("session_id") or ""),
                is_error=bool(data.get("is_error")),
                cost_usd=data.get("total_cost_usd"),
            )
    detail = (stderr or stdout or "réponse vide").strip().splitlines()
    return Reply(
        f"Le cerveau a échoué : {detail[-1][:300] if detail else 'réponse vide'}", "", True
    )


LANGUAGES = {"fr": "français", "en": "anglais"}
LIMIT_MARKERS = ("session limit", "usage limit", "rate limit", "limit reached", "hit your limit")


def usage_limit(text: str) -> bool:
    """Claude Code's plan-limit notice (it comes back as the reply text, in English)."""
    lowered = text.lower()
    return any(marker in lowered for marker in LIMIT_MARKERS)


def explain_limit(text: str) -> str:
    """The limit notice as Spectre would say it, with the reset time in French if given."""
    found = re.search(r"resets?\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text, re.IGNORECASE)
    base = "J'ai atteint la limite d'utilisation de ton abonnement Claude"
    if not found:
        return base + ". Réessaie un peu plus tard."
    hour, minutes, half = int(found[1]), found[2], (found[3] or "").lower()
    if half == "pm" and hour < 12:
        hour += 12
    if half == "am" and hour == 12:
        hour = 0
    when = f"{hour} h" + (f" {minutes}" if minutes and minutes != "00" else "")
    return f"{base} ; elle se réinitialise à {when}."


class Brain:
    """Conversation with memory and session continuity."""

    def __init__(self, db: Database, cli: ClaudeCLI, config: AssistantConfig) -> None:
        self.db = db
        self.cli = cli
        self.config = config
        self.memory = Memory(db)

    def system_prompt(self, channel: str = "voice") -> str:
        cfg = self.config
        core = CORE.format(
            name=cfg.name,
            user=cfg.user_name or "l'utilisateur",
            language_name=LANGUAGES.get(cfg.language, cfg.language),
        )
        now = datetime.now().astimezone().strftime("%A %d %B %Y, %H:%M")
        pending = self.db.all(
            "SELECT id, tool, reason FROM approvals WHERE status = 'pending' LIMIT 5"
        )
        reminders = self.db.all(
            "SELECT due_at, text FROM reminders WHERE done = 0 ORDER BY due_at LIMIT 5"
        )
        parts = [
            core,
            f"Maintenant : {now}. Ville de l'utilisateur : {cfg.city}. Canal : "
            f"{'voix (réponse parlée, très courte)' if channel == 'voice' else 'texte'}.",
            "Ce que tu sais de l'utilisateur (mémoire, la plus fiable d'abord) :\n"
            + self.memory.context_block(),
        ]
        if pending:
            parts.append(
                "Actions en attente de validation : "
                + "; ".join(f"#{p['id']} {p['tool']}" for p in pending)
            )
        if reminders:
            parts.append(
                "Prochains rappels : " + "; ".join(f"{r['due_at']} {r['text']}" for r in reminders)
            )
        return "\n\n".join(parts)

    def ask(self, text: str, channel: str = "voice") -> Reply:
        text = text.strip()
        if not text:
            return Reply("", "", True)
        event = self.db.log_event("utterance", "user", text, channel=channel)
        session = self._session()
        opener = self.take_opener()
        if opener:  # the brain's session did not see the opener Spectre said on its own
            text = f"[Tu étais venu vers l'utilisateur en lui disant : « {opener} »]\n{text}"
        reply = self.cli.ask(text, system=self.system_prompt(channel), resume=session or None)
        if usage_limit(reply.text):
            reply = Reply(explain_limit(reply.text), reply.session_id, True, reply.cost_usd)
        elif reply.is_error and session:
            # an expired or unknown session: start a fresh one
            reply = self.cli.ask(text, system=self.system_prompt(channel), resume=None)
        if reply.session_id:
            self.db.set_kv("brain_session", f"{datetime.now():%Y-%m-%d}|{reply.session_id}")
        self.db.log_event(
            "reply", "spectre", reply.text, channel=channel, in_reply_to=event, error=reply.is_error
        )
        return reply

    def take_opener(self, max_age_s: float = 3600.0) -> str:
        """What Spectre said on its own (befriending), if recent; read once."""
        stored = self.db.get_kv("befriend_opener")
        if not stored:
            return ""
        self.db.set_kv("befriend_opener", "")
        stamp, _, text = stored.partition("|")
        try:
            age = datetime.now().timestamp() - float(stamp)
        except ValueError:
            return ""
        return text if 0 <= age <= max_age_s else ""

    def _session(self) -> str:
        """Today's session id (a new conversation every day keeps context small)."""
        stored = self.db.get_kv("brain_session")
        day, _, session = stored.partition("|")
        return session if day == f"{datetime.now():%Y-%m-%d}" else ""

    def reset(self) -> None:
        self.db.set_kv("brain_session", "")


def one_shot(
    cli: ClaudeCLI, prompt: str, system: str, model: str | None = None, tools: bool = False
) -> Reply:
    """A stateless call (missions, consolidation, verification)."""
    return cli.ask(prompt, system=system, model=model, resume=None, with_tools=tools)


def extract_json(text: str) -> Any:
    """First JSON object or array found in a model answer (fenced or not)."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned[cleaned.find("\n") + 1 :] if "\n" in cleaned else cleaned
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = cleaned.find(opener), cleaned.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except ValueError:
                continue
    raise ValueError("pas de JSON exploitable dans la réponse")


def tools_list(names: Sequence[str]) -> str:
    return ", ".join(names)
