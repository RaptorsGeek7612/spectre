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
from spectre.config import has_api_key, load_env
from spectre.costs import format_cost_table
from spectre.errors import SpectreError
from spectre.graph import run

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2


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
    return text


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return the process exit code (0 ok, 1 Spectre/API error, 2 usage)."""
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
        result = run(request)
    except SpectreError as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return EXIT_ERROR

    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(result.final_text)
    if args.costs:
        print(format_cost_table(result.usage), file=sys.stderr)
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
