"""Command-line entry point: `spectre`."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from spectre import __version__
from spectre.config import MAX_REVISIONS_LIMIT, check_max_revisions, has_api_key, load_env
from spectre.costs import format_cost_table
from spectre.errors import ConfigurationError, SpectreError
from spectre.graph import SpectreResult, run
from spectre.web.pipeline import stream_run

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_INTERRUPTED = 130  # 128 + SIGINT, the shell convention for Ctrl+C
LABELS = {"scout": "Scout", "scribe": "Scribe", "warden": "Warden"}


def _force_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            with contextlib.suppress(ValueError, OSError):
                stream.reconfigure(encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser of the `spectre` command."""
    parser = argparse.ArgumentParser(
        prog="spectre",
        description="Spectre : Scout (Haiku) → Scribe (Sonnet) → Warden (Opus) "
        "transforment une demande en texte final validé.",
    )
    parser.add_argument("request", nargs="?", help="demande en texte libre")
    parser.add_argument(
        "--file", type=Path, metavar="CHEMIN", help="lit la demande depuis un fichier"
    )
    parser.add_argument(
        "--costs", action="store_true", help="affiche le tableau des coûts sur stderr"
    )
    parser.add_argument(
        "--json", action="store_true", help="écrit le résultat complet en JSON sur stdout"
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        help="affiche en direct le travail de chaque agent sur stderr",
    )
    parser.add_argument(
        "--revisions",
        type=int,
        metavar="N",
        help=f"tours de révision Warden → Scribe au plus, de 0 à {MAX_REVISIONS_LIMIT} "
        "(défaut : SPECTRE_MAX_REVISIONS, sinon 1)",
    )
    parser.add_argument("--version", action="version", version=f"spectre {__version__}")
    return parser


def _read_request(parser: argparse.ArgumentParser, args: argparse.Namespace) -> str:
    """Return the request text; exits with code 2 on usage errors."""
    if args.request is not None and args.file is not None:
        parser.error("fournissez la demande en argument OU via --file, pas les deux")
    if args.file is not None:
        try:
            text = str(args.file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as exc:
            parser.error(f"impossible de lire {args.file} : {exc}")
    elif args.request is not None:
        text = str(args.request)
    else:
        parser.error("aucune demande fournie (argument positionnel ou --file)")
    if not text.strip():
        parser.error("la demande est vide")
    if args.revisions is not None:
        try:
            check_max_revisions(args.revisions, "--revisions")
        except ConfigurationError as exc:
            parser.error(str(exc))
    return text


def _stream(request: str, max_revisions: int | None) -> SpectreResult:
    """Run the pipeline, writing each agent's work to stderr as it is produced."""
    err = sys.stderr
    for event in stream_run(request, demo=False, max_revisions=max_revisions):
        kind = event["type"]
        if kind == "agent_start":
            revision = event.get("revision")
            suffix = f" (révision {revision})" if revision else ""
            err.write(f"\n── {LABELS[event['agent']]}{suffix} ──\n")
        elif kind == "token":
            err.write(event["text"])
        elif kind == "agent_done":
            err.write("\n")
        elif kind == "error":
            raise SpectreError(event["message"], agent=event.get("agent"))
        elif kind == "done":
            err.flush()
            return SpectreResult(
                brief=event["brief"],
                draft=event["draft"],
                final_text=event["final_text"],
                usage=list(event["usage"]),
                approved=event["approved"],
                issues=list(event["issues"]),
                revisions=event["revisions"],
            )
        err.flush()
    raise SpectreError("le flux s'est arrêté avant la fin")  # pragma: no cover - defensive


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return the exit code (0 ok, 1 Spectre/API error, 2 usage, 130 Ctrl+C)."""
    _force_utf8()
    parser = build_parser()
    args = parser.parse_args(argv)
    request = _read_request(parser, args)

    load_env()
    if not has_api_key():
        print(
            "Erreur : clé API introuvable — définissez ANTHROPIC_API_KEY ou créez un fichier .env.",
            file=sys.stderr,
        )
        return EXIT_ERROR

    try:
        if args.stream:
            result = _stream(request, args.revisions)
        else:
            result = run(request, max_revisions=args.revisions)
    except SpectreError as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        print("Interrompu.", file=sys.stderr)
        return EXIT_INTERRUPTED

    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    elif not (args.stream and sys.stdout.isatty() and sys.stderr.isatty()):
        print(result.final_text)  # streamed to the same terminal: already on screen
    if not result.approved:
        points = " ; ".join(result.issues)
        print(
            f"Avertissement : Warden n'a pas validé le texte après {result.revisions} "
            f"révision(s). Points restants : {points}",
            file=sys.stderr,
        )
    if args.costs:
        print(format_cost_table(result.usage), file=sys.stderr)
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
