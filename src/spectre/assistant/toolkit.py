"""Open-source command-line tools given to the agents, each in its field, through the gate.

Every agent only sees the tools of its trade (`Tool.agents`): Syfer scans for secrets and
vulnerabilities, Octavya and the writers check their prose, Clarke and Simon simulate French
taxes and benefits, everyone can convert a document or read text from an image. A tool is a
fixed program run non-interactively: Spectre builds the command, so the agent never passes a
raw shell line. Scanning a local folder is a read; probing a remote address reaches the
outside, so it waits for the user's approval.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from spectre.assistant.actions import MAX_READ_CHARS, ActionContext, ActionError, resolve_path
from spectre.assistant.governance import Level

TIMEOUT_S = 600.0


def _languagetool_jar() -> Path | None:
    for base in (Path.home() / "Apps", Path.home()):
        found = sorted(base.glob("LanguageTool-*/languagetool-commandline.jar"), reverse=True)
        if found:
            return found[0]
    return None


LANGUAGETOOL = _languagetool_jar() or Path.home() / "Apps" / "none" / "languagetool-commandline.jar"


@dataclass(frozen=True)
class Kit:
    """One command-line tool: how to find it, who may use it, how risky, how to call it."""

    label: str
    agents: tuple[str, ...]  # agent keys allowed (empty = every agent)
    level: Level
    category: str
    argv: Callable[[ActionContext, str, str], list[str]]  # (ctx, target, options) -> command
    bins: tuple[str, ...]  # candidate executables, first found wins
    needs_target: bool = True
    remote: bool = False  # the target is a URL or host (probing it reaches outside)
    output: Callable[[ActionContext, str, str], Path] | None = None  # the file it creates
    timeout: float = TIMEOUT_S


def _bin(names: tuple[str, ...]) -> str | None:
    links = Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Links"
    extra = [
        Path.home() / "Apps" / "bin",
        links,
        Path.home() / "AppData" / "Local" / "Pandoc",
        Path("C:/Program Files/Tesseract-OCR"),
        Path.home() / "AppData" / "Roaming" / "uv" / "tools" / "semgrep" / "Scripts",
        Path.home() / ".local" / "bin",  # uv tools: rembg, whisper-ctranslate2, kokoro-tts
        Path.home() / "Apps" / "realesrgan",
        *sorted(Path("C:/Program Files").glob("ImageMagick-*"), reverse=True),
        *sorted(Path("C:/Program Files/Eclipse Adoptium").glob("*/bin"), reverse=True),
    ]
    for name in names:
        found = shutil.which(name)
        if found:
            return found
        for folder in extra:
            for suffix in ("", ".exe", ".cmd", ".bat"):
                candidate = folder / f"{name}{suffix}"
                if candidate.is_file():
                    return str(candidate)
    return None


def _local(ctx: ActionContext, target: str) -> str:
    """A path the agent is allowed to read, for a tool that scans a file or folder."""
    return str(resolve_path(ctx, target))


# Kyra's ad and communication formats: (width, height) of each social-network frame.
FORMATS = {
    "story": (1080, 1920),  # 9:16 — stories, Reels, TikTok, Shorts
    "fil": (1080, 1350),  # 4:5 — Instagram / Facebook feed
    "carre": (1080, 1080),  # 1:1
    "paysage": (1920, 1080),  # 16:9 — YouTube, screens
}
KOKORO = Path.home() / "Apps" / "kokoro"
KOKORO_VOICE = "ff_siwis"  # the French voice of Kokoro


def _format(options: str) -> tuple[str, int, int]:
    name = options.strip().lower() or "story"
    if name not in FORMATS:
        raise ActionError(f"format inconnu : {name} (au choix : {', '.join(FORMATS)})")
    return name, *FORMATS[name]


def _beside(ctx: ActionContext, target: str, suffix: str, ext: str = "") -> Path:
    """The file a media tool writes: next to its source, `<name>-<suffix><ext>`."""
    source = resolve_path(ctx, target)
    return resolve_path(ctx, str(source.with_name(f"{source.stem}-{suffix}{ext or source.suffix}")))


def _lang(options: str, default: str = "fr") -> str:
    lang = options.strip().lower() or default
    if not re.fullmatch(r"[a-z]{2}", lang):
        raise ActionError(f"langue attendue sur deux lettres (fr, en…) : {lang}")
    return lang


def _speed(options: str) -> str:
    try:
        speed = float(options.strip().replace(",", ".") or 1.0)
    except ValueError as exc:
        raise ActionError("options = la vitesse de la voix, entre 0.5 et 2 (1 par défaut)") from exc
    return str(min(2.0, max(0.5, speed)))


def _subtitle_filter(path: Path) -> str:
    """ffmpeg's `subtitles=` filter wants its path escaped (the drive colon, quotes)."""
    escaped = path.as_posix().replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    return f"subtitles='{escaped}'"


LOUDNESS = {"web": -14, "tv": -23}  # LUFS: streaming platforms; French TV (EBU R128)


def _loudness(options: str) -> int:
    name = options.strip().lower() or "web"
    if name not in LOUDNESS:
        raise ActionError("options = web (-14 LUFS) ou tv (-23 LUFS)")
    return LOUDNESS[name]


def _srt(ctx: ActionContext, target: str, options: str) -> Path:
    if options.strip():
        return resolve_path(ctx, options)
    return resolve_path(ctx, str(resolve_path(ctx, target).with_suffix(".srt")))


KITS: dict[str, Kit] = {
    "gitleaks": Kit(
        "Gitleaks (fuite de secrets)",
        ("mistral",),
        Level.READ,
        "scan",
        lambda ctx, t, o: [
            _bin(("gitleaks",)) or "gitleaks",
            "dir",
            _local(ctx, t),
            "--no-banner",
            "--report-format",
            "json",
            "--report-path",
            "-",
        ],
        ("gitleaks",),
    ),
    "trivy": Kit(
        "Trivy (vulnérabilités et dépendances)",
        ("mistral",),
        Level.READ,
        "scan",
        lambda ctx, t, o: [
            _bin(("trivy",)) or "trivy",
            "fs",
            "--scanners",
            "vuln,secret,misconfig",
            "--no-progress",
            _local(ctx, t),
        ],
        ("trivy",),
    ),
    "semgrep": Kit(
        "Semgrep (analyse de code, SAST)",
        ("mistral", "cursor"),
        Level.READ,
        "scan",
        lambda ctx, t, o: [
            _bin(("semgrep",)) or "semgrep",
            "scan",
            "--config",
            "auto",
            "--quiet",
            "--text",
            _local(ctx, t),
        ],
        ("semgrep",),
    ),
    "nuclei": Kit(
        "Nuclei (scan d'une adresse, autorisé)",
        ("mistral",),
        Level.EXTERNAL,
        "scan_remote",
        lambda ctx, t, o: [_bin(("nuclei",)) or "nuclei", "-u", t.strip(), "-silent", "-nc"],
        ("nuclei",),
        remote=True,
    ),
    "vale": Kit(
        "Vale (style de rédaction)",
        ("cursor", "scribe", "warden", "scout"),
        Level.READ,
        "prose",
        lambda ctx, t, o: [_bin(("vale",)) or "vale", "--no-exit", _local(ctx, t)],
        ("vale",),
    ),
    "languagetool": Kit(
        "LanguageTool (grammaire et orthographe)",
        (),
        Level.READ,
        "prose",
        lambda ctx, t, o: [
            _bin(("java",)) or "java",
            "-jar",
            str(LANGUAGETOOL),
            "--language",
            (o.strip() or "fr"),
            _local(ctx, t),
        ],
        ("java",),
    ),
    "pandoc": Kit(
        "Pandoc (conversion de documents)",
        (),
        Level.WRITE,
        "convert",
        lambda ctx, t, o: [
            _bin(("pandoc",)) or "pandoc",
            _local(ctx, t),
            "-o",
            _local(ctx, o.strip()),
        ],
        ("pandoc",),
    ),
    "ocr": Kit(
        "Tesseract (texte d'une image)",
        ("chatgpt",),
        Level.READ,
        "read",
        lambda ctx, t, o: [
            _bin(("tesseract",)) or "tesseract",
            _local(ctx, t),
            "stdout",
            "-l",
            (o.strip() or "fra"),
        ],
        ("tesseract",),
    ),
    # ---- Kyra: advertising and communication media (each writes a new file beside its source)
    "video_info": Kit(
        "ffprobe (infos d'une vidéo ou d'un son)",
        ("chatgpt",),
        Level.READ,
        "read",
        lambda ctx, t, o: [
            _bin(("ffprobe",)) or "ffprobe",
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            _local(ctx, t),
        ],
        ("ffprobe",),
    ),
    "video_format": Kit(
        "FFmpeg (vidéo recadrée au format d'un réseau)",
        ("chatgpt",),
        Level.WRITE,
        "convert",
        lambda ctx, t, o: [
            _bin(("ffmpeg",)) or "ffmpeg",
            "-n",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            _local(ctx, t),
            "-vf",
            "scale={1}:{2}:force_original_aspect_ratio=increase,crop={1}:{2}".format(*_format(o)),
            "-c:a",
            "copy",
            str(_beside(ctx, t, _format(o)[0])),
        ],
        ("ffmpeg",),
        output=lambda ctx, t, o: _beside(ctx, t, _format(o)[0]),
        timeout=1800.0,
    ),
    "incruster": Kit(
        "FFmpeg (sous-titres gravés dans la vidéo)",
        ("chatgpt",),
        Level.WRITE,
        "convert",
        lambda ctx, t, o: [
            _bin(("ffmpeg",)) or "ffmpeg",
            "-n",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            _local(ctx, t),
            "-vf",
            _subtitle_filter(_srt(ctx, t, o)),
            "-c:a",
            "copy",
            str(_beside(ctx, t, "soustitree")),
        ],
        ("ffmpeg",),
        output=lambda ctx, t, o: _beside(ctx, t, "soustitree"),
        timeout=1800.0,
    ),
    "image_format": Kit(
        "ImageMagick (visuel recadré au format d'un réseau)",
        ("chatgpt",),
        Level.WRITE,
        "convert",
        lambda ctx, t, o: [
            _bin(("magick",)) or "magick",
            _local(ctx, t),
            "-resize",
            "{1}x{2}^".format(*_format(o)),
            "-gravity",
            "center",
            "-extent",
            "{1}x{2}".format(*_format(o)),
            str(_beside(ctx, t, _format(o)[0])),
        ],
        ("magick",),
        output=lambda ctx, t, o: _beside(ctx, t, _format(o)[0]),
    ),
    "sous_titres": Kit(
        "Whisper (sous-titres .srt d'une vidéo ou d'un son)",
        ("chatgpt",),
        Level.WRITE,
        "convert",
        lambda ctx, t, o: [
            _bin(("whisper-ctranslate2",)) or "whisper-ctranslate2",
            _local(ctx, t),
            "--language",
            _lang(o),
            "--model",
            "small",
            "--device",
            "cpu",
            "--compute_type",
            "int8",
            "--output_format",
            "srt",
            "--output_dir",
            str(resolve_path(ctx, t).parent),
        ],
        ("whisper-ctranslate2",),
        output=lambda ctx, t, o: resolve_path(ctx, t).with_suffix(".srt"),
        timeout=3600.0,
    ),
    "detourage": Kit(
        "rembg (détourage : fond transparent)",
        ("chatgpt",),
        Level.WRITE,
        "convert",
        lambda ctx, t, o: [
            _bin(("rembg",)) or "rembg",
            "i",
            _local(ctx, t),
            str(_beside(ctx, t, "detoure", ".png")),
        ],
        ("rembg",),
        output=lambda ctx, t, o: _beside(ctx, t, "detoure", ".png"),
    ),
    "voix_off": Kit(
        "Kokoro (voix off française d'un fichier texte)",
        ("chatgpt",),
        Level.WRITE,
        "convert",
        lambda ctx, t, o: [
            _bin(("kokoro-tts",)) or "kokoro-tts",
            _local(ctx, t),
            str(_beside(ctx, t, "voix", ".wav")),
            "--lang",
            "fr-fr",
            "--voice",
            KOKORO_VOICE,
            "--speed",
            _speed(o),
            "--model",
            str(KOKORO / "kokoro-v1.0.onnx"),
            "--voices",
            str(KOKORO / "voices-v1.0.bin"),
        ],
        ("kokoro-tts",),
        output=lambda ctx, t, o: _beside(ctx, t, "voix", ".wav"),
        timeout=1800.0,
    ),
    "agrandir": Kit(
        "Real-ESRGAN (image agrandie ×4, pour l'impression)",
        ("chatgpt",),
        Level.WRITE,
        "convert",
        lambda ctx, t, o: [
            _bin(("realesrgan-ncnn-vulkan",)) or "realesrgan-ncnn-vulkan",
            "-i",
            _local(ctx, t),
            "-o",
            str(_beside(ctx, t, "x4", ".png")),
            "-n",
            "realesrgan-x4plus",
        ],
        ("realesrgan-ncnn-vulkan",),
        output=lambda ctx, t, o: _beside(ctx, t, "x4", ".png"),
    ),
    # ---- Kyra, producer: screenplay, shots, rushes, sound delivery
    "scenario_pdf": Kit(
        "Screenplain (scénario Fountain mis en page en PDF)",
        ("chatgpt", "scribe", "warden"),
        Level.WRITE,
        "convert",
        lambda ctx, t, o: [
            _bin(("screenplain",)) or "screenplain",
            "--format",
            "pdf",
            _local(ctx, t),
            str(_beside(ctx, t, "scenario", ".pdf")),
        ],
        ("screenplain",),
        output=lambda ctx, t, o: _beside(ctx, t, "scenario", ".pdf"),
    ),
    "plans": Kit(
        "PySceneDetect (liste des plans d'une vidéo, en CSV)",
        ("chatgpt",),
        Level.WRITE,
        "convert",
        lambda ctx, t, o: [
            _bin(("scenedetect",)) or "scenedetect",
            "--input",
            _local(ctx, t),
            "--output",
            str(resolve_path(ctx, t).parent),
            "--quiet",
            "detect-adaptive",
            "list-scenes",
            "--filename",
            f"{resolve_path(ctx, t).stem}-plans.csv",
        ],
        ("scenedetect",),
        output=lambda ctx, t, o: _beside(ctx, t, "plans", ".csv"),
        timeout=3600.0,
    ),
    "derushage": Kit(
        "auto-editor (retire les silences et temps morts d'un rush)",
        ("chatgpt",),
        Level.WRITE,
        "convert",
        lambda ctx, t, o: [
            _bin(("auto-editor",)) or "auto-editor",
            _local(ctx, t),
            "--output",
            str(_beside(ctx, t, "derushe")),
            "--no-open",
        ],
        ("auto-editor",),
        output=lambda ctx, t, o: _beside(ctx, t, "derushe"),
        timeout=3600.0,
    ),
    "loudness": Kit(
        "FFmpeg (son normalisé pour la diffusion : web -14 ou tv -23 LUFS)",
        ("chatgpt",),
        Level.WRITE,
        "convert",
        lambda ctx, t, o: [
            _bin(("ffmpeg",)) or "ffmpeg",
            "-n",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            _local(ctx, t),
            "-af",
            f"loudnorm=I={_loudness(o)}:TP=-1.5:LRA=11",
            "-c:v",
            "copy",
            str(_beside(ctx, t, f"{-_loudness(o)}lufs")),
        ],
        ("ffmpeg",),
        output=lambda ctx, t, o: _beside(ctx, t, f"{-_loudness(o)}lufs"),
        timeout=1800.0,
    ),
}

# Pure financial maths (numpy-financial), for Clarke and Simon: no subprocess, no files.
FINANCE_AGENTS = ("antigravity", "simon")
FINANCE_OPS = {
    "mensualite": "paiement périodique d'un prêt — taux (par période), nombre de périodes, capital",
    "van": "valeur actuelle nette — taux, puis les flux (le premier est l'investissement, négatif)",
    "tri": "taux de rendement interne — les flux (le premier négatif)",
    "valeur_future": "capital futur — taux, nombre de périodes, versement, valeur présente",
}


def finance(operation: str, values: list[float]) -> str:
    """One bounded financial computation; raises ActionError on bad input."""
    import numpy_financial as npf

    op = operation.strip().lower()
    nums = [float(v) for v in values]
    try:
        if op == "mensualite":
            rate, nper, pv = nums
            return f"Mensualité : {-npf.pmt(rate, nper, pv):.2f} par période"
        if op == "van":
            return f"VAN : {npf.npv(nums[0], nums[1:]):.2f}"
        if op == "tri":
            return f"TRI : {npf.irr(nums) * 100:.2f} % par période"
        if op == "valeur_future":
            rate, nper, pmt, pv = nums
            return f"Valeur future : {-npf.fv(rate, nper, pmt, pv):.2f}"
    except (ValueError, ZeroDivisionError) as exc:
        raise ActionError(f"calcul impossible : {exc}") from exc
    raise ActionError(f"opération inconnue : {operation} (au choix : {', '.join(FINANCE_OPS)})")


# Symbolic and numeric maths (SymPy), for Ysyss: no subprocess, no files.
SCIENCE_AGENTS = ("ysyss",)
SCIENCE_OPS = {
    "calculer": "évaluer une expression (ex. sqrt(2)*pi)",
    "simplifier": "simplifier une expression",
    "resoudre": "résoudre une équation en x (ex. x**2 - 4)",
    "deriver": "dériver une expression par rapport à x",
    "integrer": "intégrer une expression par rapport à x",
}


def science(operation: str, expression: str) -> str:
    """One bounded symbolic/numeric computation (SymPy); raises ActionError on bad input."""
    import sympy as sp

    op = operation.strip().lower()
    x = sp.Symbol("x")
    try:
        expr = sp.sympify(expression, locals={"x": x}, evaluate=True)
        if op == "calculer":
            return f"{expression} = {sp.N(expr, 12)}"
        if op == "simplifier":
            return f"{expression} = {sp.simplify(expr)}"
        if op == "resoudre":
            return f"x : {sp.solve(expr, x)}"
        if op == "deriver":
            return f"d/dx = {sp.diff(expr, x)}"
        if op == "integrer":
            return f"∫ dx = {sp.integrate(expr, x)} + C"
    except (sp.SympifyError, ValueError, TypeError, NotImplementedError) as exc:
        raise ActionError(f"expression invalide : {exc}") from exc
    raise ActionError(f"opération inconnue : {operation} (au choix : {', '.join(SCIENCE_OPS)})")


# Betting and probability maths, for Lexy: no network, no promise of gain.
BETTING_AGENTS = ("lexy",)
BETTING_OPS = {
    "probabilite": "probabilité implicite d'une cote décimale (ex. 2.5)",
    "kelly": "mise optimale de Kelly — cote décimale, puis ta probabilité estimée (0 à 1)",
    "arbitrage": "garantie de gain ? les cotes décimales des issues (ex. 2.1 2.0)",
}


def betting(operation: str, values: list[float]) -> str:
    """One bounded betting computation; never a tip or a promise of gain."""
    op = operation.strip().lower()
    nums = [float(v) for v in values]
    try:
        if op == "probabilite":
            cote = nums[0]
            return (
                f"Cote {cote} → probabilité implicite {100 / cote:.1f} % "
                "(marge du bookmaker incluse)"
            )
        if op == "kelly":
            cote, prob = nums
            edge = prob * cote - 1
            fraction = max(0.0, edge / (cote - 1))
            return (
                f"Kelly : {fraction * 100:.1f} % du capital (0 % = pas de valeur). "
                "Beaucoup misent une demie ou un quart de Kelly. Le jeu comporte "
                "un risque de perte."
            )
        if op == "arbitrage":
            total = sum(1 / c for c in nums if c > 0)
            marge = (total - 1) * 100
            verdict = "arbitrage possible" if total < 1 else "pas d'arbitrage (perte attendue)"
            return (
                f"Somme des probabilités implicites : {total * 100:.1f} % → "
                f"{verdict} (marge {marge:.1f} %)"
            )
    except (ValueError, ZeroDivisionError, IndexError) as exc:
        raise ActionError(f"calcul impossible : {exc}") from exc
    raise ActionError(f"opération inconnue : {operation} (au choix : {', '.join(BETTING_OPS)})")


def describe(config: Any) -> list[dict[str, Any]]:
    """Each tool, whether it is installed, and which agents may use it (for the Agents view)."""
    found = []
    for name, kit in KITS.items():
        found.append(
            {
                "name": name,
                "label": kit.label,
                "agents": list(kit.agents),
                "category": kit.category,
                "installed": _bin(kit.bins) is not None
                and (name != "languagetool" or LANGUAGETOOL.is_file()),
            }
        )
    return found


def run(ctx: ActionContext, name: str, target: str = "", options: str = "") -> str:
    """Run one toolkit program and return its output (truncated)."""
    kit = KITS.get(name)
    if kit is None:
        raise ActionError(f"outil inconnu : {name} (au choix : {', '.join(KITS)})")
    if kit.agents and ctx.agent not in ("", "opus", *kit.agents):
        raise ActionError(f"{kit.label} n'est pas un outil de ton domaine")
    if _bin(kit.bins) is None or (name == "languagetool" and not LANGUAGETOOL.is_file()):
        raise ActionError(f"{kit.label} n'est pas installé sur ce PC")
    if kit.needs_target and not target.strip():
        raise ActionError("précise la cible (un fichier, un dossier ou une adresse)")
    if name == "pandoc" and not options.strip():
        raise ActionError("pandoc : indique le fichier de sortie dans options (ex. sortie.docx)")
    command = kit.argv(ctx, target, options)
    runner = ctx.runner or subprocess.run
    try:
        proc = runner(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=kit.timeout,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except FileNotFoundError as exc:
        raise ActionError(f"{kit.label} est introuvable : {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ActionError(f"{kit.label} a dépassé {int(kit.timeout)} s") from exc
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    # scanners report findings with a non-zero exit code: that is a result, not a failure
    if proc.returncode not in (0, 1) and not out:
        raise ActionError(f"{kit.label} (code {proc.returncode}) : {(err or 'échec')[:400]}")
    if kit.output is not None:
        made = kit.output(ctx, target, options)
        if proc.returncode != 0 or not made.is_file():
            detail = (err or out or "aucun fichier produit")[:400]
            raise ActionError(f"{kit.label} (code {proc.returncode}) : {detail}")
        return f"Fichier créé : {made}"
    body = out or err or "(aucune sortie : rien à signaler)"
    if err and out:
        body += f"\n[détails] {err[:400]}"
    return body[:MAX_READ_CHARS]
