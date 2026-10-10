"""Greetings: Spectre says hello once a day, as suits the hour, and never twice the same way.

Once it has greeted the user, it does not greet again before the next day, even after a
restart (the day is kept in the database): it starts the conversation instead. Its recent lines
are kept too, so the next one differs. Lines are written by a fast model; if that fails, they
are drawn from varied lists.
"""

from __future__ import annotations

import json
import random
import re
from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Final

from spectre.assistant.db import Database
from spectre.assistant.memory import Memory

if TYPE_CHECKING:  # the brain uses this module for its prompt: import it lazily
    from spectre.assistant.brain import ClaudeCLI

GREETED_KV: Final = "greeted_day"  # the day Spectre last greeted the user (YYYY-MM-DD)
LINES_KV: Final = "recent_lines"  # its last spoken openers, to avoid repeating them
KEEP: Final = 12
MAX_CHARS: Final = 240
GREETING_WORDS: Final = frozenset(
    {"bonjour", "bonsoir", "salut", "coucou", "hello", "hey", "yo", "wesh", "re", "bienvenue"}
)
DAYS: Final = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")

# {name} is dropped with its comma or space when the name is unknown.
FIRST: Final[dict[str, tuple[str, ...]]] = {
    "nuit": (
        "Bonsoir {name}. Encore debout à cette heure-ci ?",
        "Bonsoir {name}, la nuit est calme de mon côté.",
        "Tiens, bonsoir {name}. Une insomnie, ou un projet qui ne peut pas attendre ?",
    ),
    "matin": (
        "Bonjour {name}.",
        "Bonjour {name}, bien dormi ?",
        "Salut {name}, prêt pour la journée ?",
        "Bien le bonjour, {name}.",
        "Bonjour {name}. Le café est passé ?",
    ),
    "midi": (
        "Bonjour {name}, c'est presque l'heure de manger.",
        "Salut {name}, la matinée s'est bien passée ?",
        "Bonjour {name}. Pause de midi ?",
    ),
    "après-midi": (
        "Bonjour {name}, l'après-midi se passe bien ?",
        "Salut {name}.",
        "Bonjour {name}. Qu'est-ce qu'on fait de cet après-midi ?",
    ),
    "soir": (
        "Bonsoir {name}.",
        "Bonsoir {name}, la journée a été bonne ?",
        "Salut {name}, la soirée commence.",
        "Bonsoir {name}. Un peu de temps pour souffler ?",
    ),
    "fin de soirée": (
        "Bonsoir {name}, la journée tire à sa fin.",
        "Bonsoir {name}. Il reste un peu d'énergie ?",
        "Salut {name}, on se fait une fin de soirée tranquille ?",
    ),
}
AGAIN: Final[dict[str, tuple[str, ...]]] = {
    "": (
        "Te revoilà, {name}.",
        "Content de te revoir, {name}.",
        "On reprend où on en était ?",
        "Quoi de neuf depuis tout à l'heure ?",
        "Je suis là si tu as besoin de moi.",
        "Alors, la suite de ta journée ?",
        "Tu tombes bien, j'avais une question pour toi : qu'est-ce qui t'occupe en ce moment ?",
    ),
    "nuit": ("Toujours pas couché, {name} ?", "La nuit porte conseil, paraît-il. Un souci ?"),
    "matin": ("La matinée avance bien ?", "Qu'est-ce qui t'attend ce matin ?"),
    "midi": ("Tu as pensé à manger ?", "La pause de midi se passe bien ?"),
    "après-midi": ("L'après-midi avance bien ?", "Il te reste beaucoup à faire aujourd'hui ?"),
    "soir": ("La soirée se passe bien ?", "Une idée pour ce soir ?"),
    "fin de soirée": ("Tu te poses enfin ?", "On fait le point sur la journée ?"),
}

OPENER: Final = """\
Tu es Spectre, l'IA personnelle de l'utilisateur, avec le caractère de JARVIS : calme, \
chaleureux, une pointe d'humour sec si le moment s'y prête. Écris UNE réplique, courte (une \
phrase, deux au plus), naturelle, à dire à voix haute. Tiens compte de l'heure exacte. Change \
de tournure à chaque fois : jamais deux fois la même formule, ni le même début de phrase que \
tes dernières répliques. Rien d'intrusif (santé, argent, intimité) s'il ne l'a pas abordé \
lui-même, pas de flatterie, pas de Markdown, pas d'emoji. Réponds UNIQUEMENT par la réplique."""


def day_part(now: datetime) -> str:
    hour = now.hour
    if hour < 5:
        return "nuit"
    if hour < 12:
        return "matin"
    if hour < 14:
        return "midi"
    if hour < 18:
        return "après-midi"
    if hour < 22:
        return "soir"
    return "fin de soirée"


def moment(now: datetime) -> str:
    """« mardi 14:05, après-midi » (French whatever the system language)."""
    return f"{DAYS[now.weekday()]} {now:%H:%M}, {day_part(now)}"


def greeted_today(db: Database, now: datetime) -> bool:
    return db.get_kv(GREETED_KV) == f"{now:%Y-%m-%d}"


def mark_greeted(db: Database, now: datetime) -> None:
    db.set_kv(GREETED_KV, f"{now:%Y-%m-%d}")


def recent_lines(db: Database) -> list[str]:
    try:
        lines = json.loads(db.get_kv(LINES_KV) or "[]")
    except ValueError:
        return []
    return [str(line) for line in lines] if isinstance(lines, list) else []


def remember_line(db: Database, text: str) -> None:
    db.set_kv(LINES_KV, json.dumps([*recent_lines(db), text][-KEEP:], ensure_ascii=False))


def is_greeting(text: str) -> bool:
    words = re.findall(r"[a-zà-ÿ]+", text.lower())
    return bool(words) and words[0] in GREETING_WORDS


def fill(template: str, name: str) -> str:
    if not name:
        template = template.replace(", {name}", "").replace(" {name}", "")
    return template.format(name=name)


def pick(pool: Sequence[str], recent: Sequence[str], name: str, rng: random.Random) -> str:
    """A line from `pool` that was not said lately (any of them if all were)."""
    lines = [fill(t, name) for t in pool]
    fresh = [line for line in lines if line not in recent]
    return rng.choice(fresh or lines)


def fallback(db: Database, now: datetime, name: str, rng: random.Random) -> str:
    part = day_part(now)
    pool = FIRST[part] if not greeted_today(db, now) else (*AGAIN[""], *AGAIN[part])
    return pick(pool, recent_lines(db), name, rng)


def greeting_rule(db: Database, now: datetime) -> str:
    """What the brain is told about greeting, in its system prompt and its openers."""
    if greeted_today(db, now):
        return (
            "Tu as déjà salué l'utilisateur aujourd'hui : ne lui redis ni bonjour, ni bonsoir, "
            "ni salut avant demain, même après un redémarrage (s'il te salue, réponds-lui "
            "simplement, sans formule figée). Lance plutôt la conversation : une question, une "
            "remarque sur le moment, une suite à ce qu'il aime ou t'a confié."
        )
    return (
        "Premier contact de la journée : salue-le comme il convient à l'heure (bonjour jusqu'à "
        "18 h, bonsoir ensuite), avec une formule variée, puis tu peux enchaîner sur une courte "
        "question."
    )


def compose(
    cli: ClaudeCLI,
    db: Database,
    now: datetime,
    name: str,
    situation: str,
    *,
    model: str = "haiku",
    rng: random.Random | None = None,
) -> str:
    """A fresh spoken opener for `situation`; it counts as today's greeting."""
    from spectre.assistant.brain import one_shot

    rng = rng or random.Random()
    greeted = greeted_today(db, now)
    recent = recent_lines(db)
    prompt = (
        f"Situation : {situation}.\nMoment exact : {moment(now)}. "
        f"Prénom : {name or 'inconnu'}.\n{greeting_rule(db, now)}\n"
        f"Ce que tu sais de lui :\n{Memory(db).context_block(20)}\n"
        "Tes dernières répliques (ne reprends ni leurs mots ni leur tournure) :\n"
        + ("\n".join(f"- {line}" for line in recent) or "(aucune)")
    )
    reply = one_shot(cli, prompt, OPENER, model=model)
    text = reply.text.strip().strip('"«» ').strip()
    if reply.is_error or not text or len(text) > MAX_CHARS or (greeted and is_greeting(text)):
        text = fallback(db, now, name, rng)
    remember_line(db, text)
    mark_greeted(db, now)
    return text


def opening(db: Database, now: datetime, name: str, rng: random.Random | None = None) -> str:
    """The greeting that opens a briefing, or "" when the user was already greeted today."""
    if greeted_today(db, now):
        return ""
    text = pick(FIRST[day_part(now)], recent_lines(db), name, rng or random.Random())
    remember_line(db, text)
    mark_greeted(db, now)
    return text
