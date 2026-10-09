"""Command-line entry point: `spectre` (and `spectre batch`, `spectre eval`)."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from spectre import __version__
from spectre.config import (
    MAX_REVISIONS_LIMIT,
    check_max_revisions,
    has_api_key,
    load_client_settings,
    load_env,
    load_specs,
)
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
    parser.epilog = (
        "Autres commandes : « spectre batch FICHIER » (plusieurs demandes) et "
        "« spectre eval CAS » (évaluation). Ajoutez --help pour leurs options."
    )
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
    for event in stream_run(request, demo=False, max_revisions=max_revisions, include_extras=True):
        kind = event["type"]
        if kind == "agent_start":
            revision = event.get("revision")
            suffix = f" (révision {revision})" if revision else ""
            label = LABELS.get(event["agent"], event["agent"].capitalize())
            err.write(f"\n── {label}{suffix} ──\n")
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


def _revisions_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--revisions",
        type=int,
        metavar="N",
        help=f"tours de révision Warden → Scribe au plus, de 0 à {MAX_REVISIONS_LIMIT}",
    )


def _check_revisions(parser: argparse.ArgumentParser, value: int | None) -> None:
    if value is not None:
        try:
            check_max_revisions(value, "--revisions")
        except ConfigurationError as exc:
            parser.error(str(exc))


def _require_key() -> bool:
    load_env()
    if has_api_key():
        return True
    print(
        "Erreur : clé API introuvable — définissez ANTHROPIC_API_KEY ou créez un fichier .env.",
        file=sys.stderr,
    )
    return False


def _note(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def batch_main(argv: Sequence[str]) -> int:
    """`spectre batch FILE`: many requests, through the Message Batches API or one by one."""
    from spectre.batch import AnthropicBatches, BatchRun, read_requests, run_direct, write_results

    parser = argparse.ArgumentParser(
        prog="spectre batch",
        description="Traite plusieurs demandes : une par ligne (texte) ou en JSON Lines "
        '({"id": ..., "request": ...}). Par défaut via l\'API Message Batches (50 % moins cher, '
        "résultats en quelques minutes à quelques heures, reprise automatique si on relance).",
    )
    parser.add_argument("file", type=Path, help="fichier des demandes")
    parser.add_argument(
        "--out",
        type=Path,
        metavar="CHEMIN",
        help="résultats JSON Lines (défaut : <fichier>.results.jsonl)",
    )
    parser.add_argument(
        "--direct", action="store_true", help="traite les demandes tout de suite, une par une"
    )
    parser.add_argument(
        "--poll", type=float, default=30.0, metavar="SECONDES", help="intervalle de suivi des lots"
    )
    _revisions_arg(parser)
    args = parser.parse_args(argv)
    _check_revisions(parser, args.revisions)
    out: Path = args.out or args.file.with_name(args.file.stem + ".results.jsonl")
    try:
        items = read_requests(args.file)
        if not _require_key():
            return EXIT_ERROR
        if args.direct:
            items = run_direct(items, max_revisions=args.revisions, notify=_note)
        else:
            state = out.with_name(out.name + ".state.json")
            runner = BatchRun(
                AnthropicBatches(load_client_settings()),
                state,
                max_revisions=args.revisions,
                poll_s=args.poll,
                notify=_note,
            )
            items = runner.run(items)
    except SpectreError as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        print(
            "Interrompu. Les lots déjà envoyés continuent côté serveur : relancez la même "
            "commande pour reprendre.",
            file=sys.stderr,
        )
        return EXIT_INTERRUPTED
    write_results(out, items)
    failed = [item for item in items if item.error]
    costs = [c for item in items if (c := item.result()["total_cost_usd"]) is not None]
    total = f"{sum(costs):.4f} $" if costs else "n/d"
    _note(f"{len(items) - len(failed)}/{len(items)} demande(s) traitée(s), coût {total} → {out}")
    for item in failed:
        _note(f"  échec {item.id} : {item.error}")
    return EXIT_ERROR if failed else EXIT_OK


def eval_main(argv: Sequence[str]) -> int:
    """`spectre eval CASES`: run test cases and grade the texts."""
    from dataclasses import replace

    from spectre.evaluation import format_report, load_cases, run_eval
    from spectre.llm import make_chat_model

    parser = argparse.ArgumentParser(
        prog="spectre eval",
        description="Évalue Spectre sur des cas de test (JSON Lines) : contrôles automatiques "
        "(mots, termes, validation, coût) et, avec --judge, critères notés par un juge.",
    )
    parser.add_argument("file", type=Path, help="fichier des cas")
    parser.add_argument(
        "--judge", action="store_true", help="fait noter les critères par le modèle de Warden"
    )
    parser.add_argument("--json", action="store_true", help="rapport complet en JSON sur stdout")
    parser.add_argument(
        "--demo", action="store_true", help="modèles de démonstration, sans clé ni coût"
    )
    _revisions_arg(parser)
    args = parser.parse_args(argv)
    _check_revisions(parser, args.revisions)
    if args.demo and args.judge:
        parser.error("--judge n'est pas disponible en démonstration")
    try:
        cases = load_cases(args.file)
        kwargs: dict[str, Any] = {"max_revisions": args.revisions}
        judge_model = None
        judge_name = ""
        if args.demo:
            from spectre.web.pipeline import build_models

            kwargs["models"] = build_models(demo=True, overrides={})
        else:
            if not _require_key():
                return EXIT_ERROR
            if args.judge:
                spec = load_specs()["warden"]
                spec = replace(spec, name="juge", effort="low" if spec.effort else None)
                judge_model, judge_name = make_chat_model(spec, load_client_settings()), spec.model
        results = run_eval(
            cases, judge_model=judge_model, judge_name=judge_name, notify=_note, **kwargs
        )
    except SpectreError as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        print("Interrompu.", file=sys.stderr)
        return EXIT_INTERRUPTED
    if args.json:
        print(json.dumps([r.to_dict() for r in results], ensure_ascii=False, indent=2))
    else:
        print(format_report(results))
    if args.demo:
        _note("Démonstration : textes préenregistrés et coûts simulés, rien n'a été facturé.")
    return EXIT_OK if all(r.passed for r in results) else EXIT_ERROR


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return the exit code (0 ok, 1 Spectre/API error, 2 usage, 130 Ctrl+C)."""
    _force_utf8()
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["batch"]:
        return batch_main(arguments[1:])
    if arguments[:1] == ["eval"]:
        return eval_main(arguments[1:])
    parser = build_parser()
    args = parser.parse_args(arguments)
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
