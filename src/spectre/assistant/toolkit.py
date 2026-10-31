"""Open-source command-line tools given to the agents, each in its field, through the gate.

Every agent only sees the tools of its trade (`Tool.agents`): Syfer scans for secrets and
vulnerabilities, Octavya and the writers check their prose, Clarke and Simon simulate French
taxes and benefits, everyone can convert a document or read text from an image. A tool is a
fixed program run non-interactively: Spectre builds the command, so the agent never passes a
raw shell line. Scanning a local folder is a read; probing a remote address reaches the
outside, so it waits for the user's approval.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
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
    report: Callable[[ActionContext, str, str], Path] | None = None  # where long stdout is kept
    env: Callable[[ActionContext, str, str], dict[str, str]] | None = None  # extra env vars


def _bin(names: tuple[str, ...]) -> str | None:
    links = Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Links"
    extra = [
        Path.home() / "Apps" / "bin",
        links,
        Path.home() / "AppData" / "Local" / "Pandoc",
        Path("C:/Program Files/Tesseract-OCR"),
        Path("C:/Program Files (x86)/Nmap"),
        Path.home() / "AppData" / "Roaming" / "uv" / "tools" / "semgrep" / "Scripts",
        Path.home() / ".local" / "bin",  # uv tools: rembg, whisper-ctranslate2, kokoro-tts
        Path.home() / "Apps" / "realesrgan",
        Path("C:/Program Files/Inkscape/bin"),
        Path.home() / ".cargo" / "bin",  # Rust (rustup): cargo, rustc, vtracer
        Path.home() / "AppData" / "Local" / "Programs" / "Microsoft VS Code" / "bin",
        Path("C:/Program Files/Calibre2"),
        Path("C:/Program Files/FontForgeBuilds/bin"),
        Path("C:/Program Files/OpenSSL-Win64/bin"),
        Path("C:/Program Files/GnuPG/bin"),
        # Chromium (open source) as installed by Playwright: Kyra renders her HTML designs
        *sorted(
            (Path.home() / "AppData" / "Local" / "ms-playwright").glob("chromium-*/chrome-win*"),
            reverse=True,
        ),
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


def _uv_tool(name: str, module: str) -> list[str]:
    """Run a uv-installed tool through its own Python: Windows' Smart App Control can block
    the freshly generated `.exe` launcher while the interpreter itself is trusted."""
    python = Path.home() / "AppData" / "Roaming" / "uv" / "tools" / name / "Scripts" / "python.exe"
    if python.is_file():
        return [str(python), "-m", module]
    return [_bin((name,)) or name]


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


def _page(ctx: ActionContext, target: str, kinds: tuple[str, ...] = (".html", ".htm")) -> Path:
    """The design file a renderer opens: a local HTML (or SVG) page the agent may read."""
    page = resolve_path(ctx, target)
    if page.suffix.lower() not in kinds:
        raise ActionError(f"fichier attendu : {' ou '.join(kinds)} ({page.name})")
    return page


def _headless(*flags: str) -> list[str]:
    """Headless Chromium, given time for fonts, images and entrance animations to settle."""
    return [
        _bin(("chrome",)) or "chrome",
        "--headless",
        "--disable-gpu",
        "--virtual-time-budget=5000",
        *flags,
    ]


def _vector(options: str) -> str:
    kind = options.strip().lower() or "pdf"
    if kind not in ("pdf", "png"):
        raise ActionError("options = pdf (vectoriel, pour l'impression) ou png")
    return kind


# Syfer's reverse engineering: REA (github.com/morluto/rea, MIT). Static inspections read the
# file without running it. Native commands decompile machine code through Ghidra (open source,
# NSA). Runtime capture, debuggers, Frida and adb are deliberately left out.
REA_COMMANDS = {
    "inspect-artifact": "vue d'ensemble d'un fichier (format, archive, membres, pistes suivantes)",
    "inspect-pe-resources": "ressources d'un .exe/.dll Windows (icônes, versions, manifestes)",
    "inspect-managed-artifact": "assembly .NET : identité, métadonnées, dépendances",
    "inspect-managed-members": "assembly .NET : types, méthodes, signatures, chaînes",
    "inspect-managed-native-boundaries": "assembly .NET : appels natifs (P/Invoke)",
    "inspect-go-binary": "binaire Go : version du compilateur, modules, réglages de build",
    "inspect-rust-binary": "binaire Rust : dépendances embarquées (cargo-auditable)",
    "inspect-electron-fuses": "appli Electron : fusibles de sécurité de l'exécutable",
    "analyze-javascript-application": "appli JavaScript/Electron (dossier ou .asar) : modules, IPC",
    "inspect-sqlite-database": "base SQLite : schéma et tables",
    "identify-flutter-build": "APK Flutter : version de Dart et du moteur",
}
# Native commands (binaire natif C/C++) run through Ghidra: each takes one extra argument after
# the file (except `analyze`): a fonction, une adresse (0x…) ou un terme à chercher.
REA_NATIVE = {
    "analyze": ("vue d'ensemble du binaire natif (Ghidra)", False),
    "search": ("cherche une chaîne ou un nom de fonction (Ghidra)", True),
    "function": ("décompile une fonction par son nom (Ghidra)", True),
    "decompile": ("décompile le code à une adresse 0x… (Ghidra)", True),
    "xrefs": ("références vers une adresse 0x… (Ghidra)", True),
    "trace": ("suit un terme à travers les références (Ghidra)", True),
}
REA_JS = (
    Path.home()
    / "AppData"
    / "Roaming"
    / "npm"
    / "node_modules"
    / "rea-agents"
    / "scripts"
    / "rea.mjs"
)


def _newest(pattern: str, *bases: Path) -> Path | None:
    """The newest directory matching `pattern` under any base (Ghidra, a JDK…)."""
    for base in bases:
        found = sorted(base.glob(pattern), reverse=True)
        if found:
            return found[0]
    return None


def ghidra_dir() -> Path | None:
    return _newest("ghidra_*_PUBLIC", Path.home() / "Apps" / "ghidra")


def _jdk_dir() -> Path | None:
    return _newest("jdk-21*", Path("C:/Program Files/Eclipse Adoptium")) or _newest(
        "jdk-2[2-9]*", Path("C:/Program Files/Eclipse Adoptium")
    )


def _rea_parse(options: str) -> tuple[str, str]:
    """(command, extra argument). A static command takes none; a native one may need a function,
    an address or a search term."""
    parts = options.strip().split(maxsplit=1)
    command = (parts[0] if parts else "inspect-artifact").lower()
    extra = parts[1] if len(parts) > 1 else ""
    if command in REA_COMMANDS:
        return command, ""
    if command in REA_NATIVE:
        if REA_NATIVE[command][1] and not extra:
            raise ActionError(f"« {command} » attend un argument (fonction, adresse 0x… ou terme)")
        return command, extra
    allowed = ", ".join((*REA_COMMANDS, *REA_NATIVE))
    raise ActionError(f"commande REA inconnue : {command} (au choix : {allowed})")


def _rea_argv(ctx: ActionContext, target: str, options: str) -> list[str]:
    command, extra = _rea_parse(options)
    argv = [_bin(("node",)) or "node", str(REA_JS), command, _local(ctx, target)]
    if command in REA_NATIVE:
        if ghidra_dir() is None or _jdk_dir() is None:
            raise ActionError(
                "l'analyse native a besoin de Ghidra (~/Apps/ghidra) et d'un JDK 21 ; "
                "installe-les, ou utilise une commande statique (inspect-artifact…)"
            )
        if extra:
            argv.append(extra)
        argv += ["--provider", "ghidra"]
    return [*argv, "--json"]


def _rea_env(ctx: ActionContext, target: str, options: str) -> dict[str, str]:
    """Point REA at Ghidra and its JDK for a native command, without touching the global
    environment: both tools are found under the user's Apps folder."""
    command, _ = _rea_parse(options)
    gh, jdk = ghidra_dir(), _jdk_dir()
    if command in REA_NATIVE and gh is not None and jdk is not None:
        return {
            "GHIDRA_INSTALL_DIR": str(gh),
            "JAVA_HOME": str(jdk),
            # let Ghidra import and analyze a big binary before REA gives up, just under the
            # kit's own 900 s hard limit (a CPU-only machine is slow on large files)
            "REA_GHIDRA_STARTUP_TIMEOUT_MS": "840000",
        }
    return {}


def _rea_report(ctx: ActionContext, target: str, options: str) -> Path:
    """REA's full Evidence JSON, kept in the workspace: it can run to hundreds of thousands
    of characters, far more than one answer holds."""
    name = resolve_path(ctx, target).name
    return ctx.workspace / "retro" / f"{name}-{_rea_parse(options)[0]}.json"


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


# ---- Rust for every agent: cargo on a project folder (its Cargo.toml) ------------------------
CARGO_COMMANDS = {
    "check": "vérifie que le code compile (rapide)",
    "clippy": "lint : erreurs courantes et code non idiomatique",
    "test": "lance les tests",
    "fmt": "met le code en forme (rustfmt)",
    "build": "compile le projet",
    "doc": "génère la documentation",
    "new": "crée un projet (la cible = le nouveau dossier)",
    "tree": "arbre des dépendances",
}


def _cargo_argv(ctx: ActionContext, target: str, options: str) -> list[str]:
    words = options.split()
    sub = (words[0] if words else "check").lower()
    if sub not in CARGO_COMMANDS:
        raise ActionError(f"cargo : commande au choix {', '.join(CARGO_COMMANDS)}")
    cargo = _bin(("cargo",)) or "cargo"
    flags = [w for w in words[1:] if re.fullmatch(r"--?[a-z][a-z0-9-]*", w)]
    if sub == "new":
        return [cargo, "new", *flags, _local(ctx, target)]
    folder = resolve_path(ctx, target)
    manifest = folder if folder.name == "Cargo.toml" else folder / "Cargo.toml"
    if not manifest.is_file():
        raise ActionError(f"pas de Cargo.toml dans {folder}")
    argv = [cargo, sub, "--manifest-path", str(manifest), *flags]
    if sub == "clippy":
        argv += ["--", "-D", "warnings"] if "--strict" in words else []
        argv = [a for a in argv if a != "--strict"]
    return argv


# ---- VS Code: open a file at a line, a folder, or a diff in the user's editor -----------------
_SHELL_META = re.compile(r'[&|<>^%"!]')  # `code` is a .cmd script: cmd.exe re-reads its line


def _vscode_argv(ctx: ActionContext, target: str, options: str) -> list[str]:
    code = _bin(("code",)) or "code"
    path = resolve_path(ctx, target)
    wanted = options.strip()
    paths = [str(path)]
    if wanted.lower().startswith("diff:"):
        other = resolve_path(ctx, wanted[5:].strip())
        argv = [code, "--reuse-window", "--diff", str(path), str(other)]
        paths.append(str(other))
    elif wanted.lower().startswith("ligne:") or wanted.lower().startswith("line:"):
        line = wanted.split(":", 1)[1].strip()
        if not line.isdigit():
            raise ActionError("vscode : options ligne:<numéro>")
        argv = [code, "--reuse-window", "--goto", f"{path}:{line}"]
    else:
        argv = [code, "--reuse-window", str(path)]
    if any(_SHELL_META.search(p) for p in paths):
        raise ActionError('vscode : ce chemin contient un caractère spécial (& | < > ^ % " !)')
    return argv


# ---- Charlotte: raster to vector, an image's palette, print layout with Typst ----------------
def _vtracer_out(ctx: ActionContext, target: str, options: str) -> Path:
    return _beside(ctx, target, "vecteur", ".svg")


def _vtracer_argv(ctx: ActionContext, target: str, options: str) -> list[str]:
    mode = options.strip().lower() or "couleur"
    if mode not in ("couleur", "noir"):
        raise ActionError("vectoriser : options couleur (par défaut) ou noir (un logo au trait)")
    return [
        _bin(("vtracer",)) or "vtracer",
        "--input",
        _local(ctx, target),
        "--output",
        str(_vtracer_out(ctx, target, options)),
        "--colormode",
        "color" if mode == "couleur" else "bw",
    ]


def _palette_count(options: str) -> str:
    raw = options.strip() or "8"
    if not raw.isdigit() or not 2 <= int(raw) <= 24:
        raise ActionError("palette : options = le nombre de couleurs, de 2 à 24")
    return raw


def _typst_out(ctx: ActionContext, target: str, options: str) -> Path:
    return resolve_path(ctx, str(resolve_path(ctx, target).with_suffix(".pdf")))


def _typst_argv(ctx: ActionContext, target: str, options: str) -> list[str]:
    source = _page(ctx, target, (".typ",))
    return [
        _bin(("typst",)) or "typst",
        "compile",
        str(source),
        str(_typst_out(ctx, target, options)),
    ]


# ---- Célya: French grammar (Grammalecte), EPUB check (EPUBCheck), e-books (Calibre) ----------
def _grammalecte_cli() -> Path:
    found = _newest("grammalecte*/grammalecte-cli.py", Path.home() / "Apps")
    return found or Path.home() / "Apps" / "grammalecte" / "grammalecte-cli.py"


def _epubcheck_jar() -> Path:
    found = _newest("epubcheck*/epubcheck.jar", Path.home() / "Apps")
    return found or Path.home() / "Apps" / "epubcheck" / "epubcheck.jar"


# ---- Monty: OpenSSL 4 (certificates, digests, post-quantum test keys), GnuPG, age, SSLyze ----
OPENSSL_WIN = Path("C:/Program Files/OpenSSL-Win64/bin")
DIGESTS = ("sha256", "sha384", "sha512", "sha3-256", "sha3-512", "blake2b512", "sha1", "md5")
# test key algorithm -> genpkey arguments (OpenSSL >= 3.5 has the post-quantum ones built in)
TEST_KEYS = {
    "ml-kem-512": ["-algorithm", "ML-KEM-512"],
    "ml-kem-768": ["-algorithm", "ML-KEM-768"],
    "ml-kem-1024": ["-algorithm", "ML-KEM-1024"],
    "ml-dsa-44": ["-algorithm", "ML-DSA-44"],
    "ml-dsa-65": ["-algorithm", "ML-DSA-65"],
    "ml-dsa-87": ["-algorithm", "ML-DSA-87"],
    "slh-dsa-sha2-128s": ["-algorithm", "SLH-DSA-SHA2-128s"],
    "slh-dsa-shake-128f": ["-algorithm", "SLH-DSA-SHAKE-128f"],
    "ed25519": ["-algorithm", "ED25519"],
    "x25519": ["-algorithm", "X25519"],
    "ed448": ["-algorithm", "ED448"],
    "x448": ["-algorithm", "X448"],
    "ec-p256": ["-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:P-256"],
    "ec-p384": ["-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:P-384"],
    "rsa-3072": ["-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:3072"],
    "rsa-4096": ["-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:4096"],
}
HOST = re.compile(r"^(https?://)?[A-Za-z0-9][A-Za-z0-9.-]*(:\d{1,5})?/?$")
AGE_RECIPIENT = re.compile(r"^(age1[0-9a-z]{20,}|ssh-ed25519 [A-Za-z0-9+/=]+)$")


def _openssl() -> str:
    """The Windows OpenSSL (4.x, post-quantum); Git's own copy only as a fallback."""
    own = OPENSSL_WIN / "openssl.exe"
    return str(own) if own.is_file() else _bin(("openssl",)) or "openssl"


def _host(target: str) -> str:
    """A server to audit: a host name or address, an optional port (no path, no options)."""
    raw = target.strip()
    if not HOST.match(raw):
        raise ActionError("cible : un nom de serveur, ex. exemple.fr ou exemple.fr:443")
    return raw.split("://")[-1].rstrip("/")


def _digest_argv(ctx: ActionContext, target: str, options: str) -> list[str]:
    algo = options.strip().lower() or "sha256"
    if algo not in DIGESTS:
        raise ActionError(f"empreinte : options = un algorithme parmi {', '.join(DIGESTS)}")
    return [_openssl(), "dgst", f"-{algo}", _local(ctx, target)]


def _pem(path: str) -> bool:
    try:
        with open(path, "rb") as fh:
            return b"-----BEGIN" in fh.read(4096)
    except OSError:
        return True


def _asn1_argv(ctx: ActionContext, target: str, options: str) -> list[str]:
    path = _local(ctx, target)
    form = [] if _pem(path) else ["-inform", "DER"]
    return [_openssl(), "asn1parse", *form, "-in", path, "-i"]


def _test_key(options: str) -> str:
    algo = options.strip().lower() or "ml-kem-768"
    if algo not in TEST_KEYS:
        raise ActionError(f"cle_test : options = un algorithme parmi {', '.join(TEST_KEYS)}")
    return algo


def _test_key_out(ctx: ActionContext, target: str, options: str) -> Path:
    """Test keys live in the workspace, named TEST so nobody takes them for real ones."""
    name = re.sub(r"[^A-Za-z0-9_-]", "", target.strip())[:40] or "cle"
    return ctx.workspace / "crypto-test" / f"TEST-{_test_key(options)}-{name}.pem"


def _test_key_argv(ctx: ActionContext, target: str, options: str) -> list[str]:
    out = _test_key_out(ctx, target, options)
    out.parent.mkdir(parents=True, exist_ok=True)
    return [_openssl(), "genpkey", *TEST_KEYS[_test_key(options)], "-out", str(out)]


def _gpg_argv(ctx: ActionContext, target: str, options: str) -> list[str]:
    signed = _local(ctx, target)
    if options.strip():
        signature = _local(ctx, options)
    else:
        found = [
            f"{signed}{ext}" for ext in (".asc", ".sig", ".gpg") if Path(f"{signed}{ext}").is_file()
        ]
        if not found:
            raise ActionError("gpg_verif : options = le fichier de signature (.asc ou .sig)")
        signature = found[0]
    return [_bin(("gpg",)) or "gpg", "--batch", "--verify", signature, signed]


def _age_out(ctx: ActionContext, target: str, options: str) -> Path:
    source = resolve_path(ctx, target)
    return resolve_path(ctx, str(source.with_name(f"{source.name}.age")))


def _age_argv(ctx: ActionContext, target: str, options: str) -> list[str]:
    recipient = options.strip()
    if not AGE_RECIPIENT.match(recipient):
        raise ActionError(
            "age_chiffrer : options = la clé PUBLIQUE du destinataire (age1… ou ssh-ed25519 …)"
        )
    out = _age_out(ctx, target, options)
    return [_bin(("age",)) or "age", "-r", recipient, "-o", str(out), _local(ctx, target)]


def _ebook_out(ctx: ActionContext, target: str, options: str) -> Path:
    kind = options.strip().lower().lstrip(".") or "epub"
    if kind not in ("epub", "azw3", "pdf", "docx", "odt", "txt", "mobi"):
        raise ActionError("ebook : options = le format voulu (epub, azw3, pdf, docx, odt, txt)")
    return _beside(ctx, target, "livre", f".{kind}")


KITS: dict[str, Kit] = {
    "gitleaks": Kit(
        "Gitleaks (fuite de secrets)",
        ("mistral", "monty"),
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
        ("mistral", "cursor", "monty"),
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
    "nmap": Kit(
        "Nmap (ports et services d'une cible autorisée)",
        ("mistral",),
        Level.EXTERNAL,
        "scan_remote",
        # -sT -sV -Pn: connect scan (no raw socket on Windows), service versions, no ping;
        #  -T4 timing, --top-ports 200 to stay quick and non-aggressive.
        lambda ctx, t, o: [
            _bin(("nmap",)) or "nmap",
            "-sT",
            "-sV",
            "-Pn",
            "-T4",
            "--top-ports",
            "200",
            t.strip(),
        ],
        ("nmap",),
        remote=True,
    ),
    "subfinder": Kit(
        "Subfinder (sous-domaines d'un domaine autorisé)",
        ("mistral",),
        Level.EXTERNAL,
        "scan_remote",
        lambda ctx, t, o: [_bin(("subfinder",)) or "subfinder", "-d", t.strip(), "-silent"],
        ("subfinder",),
        remote=True,
    ),
    "httpx": Kit(
        "httpx (sonde HTTP d'une adresse autorisée)",
        ("mistral",),
        Level.EXTERNAL,
        "scan_remote",
        lambda ctx, t, o: [
            _bin(("httpx",)) or "httpx",
            "-u",
            t.strip(),
            "-silent",
            "-title",
            "-status-code",
            "-tech-detect",
            "-no-color",
        ],
        ("httpx",),
        remote=True,
    ),
    "trufflehog": Kit(
        "TruffleHog (secrets et clés dans un dossier local)",
        ("mistral",),
        Level.READ,
        "scan",
        lambda ctx, t, o: [
            _bin(("trufflehog",)) or "trufflehog",
            "filesystem",
            _local(ctx, t),
            "--no-update",
            "--no-verification",
        ],
        ("trufflehog",),
    ),
    "vale": Kit(
        "Vale (style de rédaction)",
        ("cursor", "celya", "scribe", "warden", "scout"),
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
        ("chatgpt", "charlotte"),
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
        ("chatgpt", "charlotte"),
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
        ("chatgpt", "charlotte"),
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
            *_uv_tool("scenedetect", "scenedetect"),
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
    # ---- Kyra, designer: render an HTML design to print, capture it to check it, export vectors
    "maquette_pdf": Kit(
        "Chromium (maquette HTML en PDF : une page par slide ou par @page)",
        ("chatgpt", "charlotte"),
        Level.WRITE,
        "convert",
        lambda ctx, t, o: _headless(
            "--no-pdf-header-footer",
            f"--print-to-pdf={_beside(ctx, t, 'maquette', '.pdf')}",
            _page(ctx, t).as_uri(),
        ),
        ("chrome",),
        output=lambda ctx, t, o: _beside(ctx, t, "maquette", ".pdf"),
        timeout=300.0,
    ),
    "maquette_png": Kit(
        "Chromium (capture PNG d'une maquette HTML, pour la relire)",
        ("chatgpt", "charlotte"),
        Level.WRITE,
        "convert",
        lambda ctx, t, o: _headless(
            "--hide-scrollbars",
            "--window-size={1},{2}".format(*_format(o.strip() or "paysage")),
            f"--screenshot={_beside(ctx, t, _format(o.strip() or 'paysage')[0], '.png')}",
            _page(ctx, t).as_uri(),
        ),
        ("chrome",),
        output=lambda ctx, t, o: _beside(ctx, t, _format(o.strip() or "paysage")[0], ".png"),
        timeout=300.0,
    ),
    "vectoriel": Kit(
        "Inkscape (export d'un SVG en PDF vectoriel ou en PNG)",
        ("chatgpt", "charlotte"),
        Level.WRITE,
        "convert",
        lambda ctx, t, o: [
            _bin(("inkscape",)) or "inkscape",
            str(_page(ctx, t, (".svg",))),
            f"--export-type={_vector(o)}",
            f"--export-filename={_beside(ctx, t, 'export', '.' + _vector(o))}",
        ],
        ("inkscape",),
        output=lambda ctx, t, o: _beside(ctx, t, "export", "." + _vector(o)),
    ),
    # ---- Syfer: reverse engineering of a local file with REA (static; or native through Ghidra)
    "retro": Kit(
        "REA (rétro-ingénierie d'un fichier : exe, dll, .NET, Go, Rust, Electron, et natif Ghidra)",
        ("mistral",),
        Level.READ,
        "scan",
        _rea_argv,  # node, not rea.cmd: cmd.exe would re-parse the path
        ("node",),
        report=_rea_report,
        env=_rea_env,
        timeout=900.0,  # a native Ghidra analysis imports and analyzes before answering
    ),
    # ---- every agent: Rust (cargo) and the user's VS Code
    "cargo": Kit(
        "Cargo (Rust : check, clippy, test, fmt, build, doc, new, tree)",
        (),
        Level.WRITE,
        "write_file",
        _cargo_argv,
        ("cargo",),
        timeout=900.0,
    ),
    "vscode": Kit(
        "VS Code (ouvrir un fichier, une ligne, un dossier ou un diff)",
        (),
        Level.UI,
        "open",
        _vscode_argv,
        ("code",),
        timeout=60.0,
    ),
    # ---- Charlotte, graphic designer
    "vectoriser": Kit(
        "VTracer (image matricielle en SVG vectoriel)",
        ("charlotte", "chatgpt"),
        Level.WRITE,
        "convert",
        _vtracer_argv,
        ("vtracer",),
        output=_vtracer_out,
    ),
    "palette": Kit(
        "ImageMagick (palette de couleurs d'une image, en hexadécimal)",
        ("charlotte", "chatgpt"),
        Level.READ,
        "read",
        lambda ctx, t, o: [
            _bin(("magick",)) or "magick",
            _local(ctx, t),
            "-colors",
            _palette_count(o),
            "-unique-colors",
            "txt:-",
        ],
        ("magick",),
    ),
    "mise_en_page": Kit(
        "Typst (mise en page .typ en PDF : affiche, plaquette, carte)",
        ("charlotte",),
        Level.WRITE,
        "convert",
        _typst_argv,
        ("typst",),
        output=_typst_out,
    ),
    # ---- Célya, novelist
    "livre_pdf": Kit(
        "Typst (manuscrit ou livre .typ en PDF)",
        ("celya",),
        Level.WRITE,
        "convert",
        _typst_argv,
        ("typst",),
        output=_typst_out,
    ),
    "grammalecte": Kit(
        "Grammalecte (grammaire et typographie françaises)",
        ("celya", "cursor", "scribe", "warden"),
        Level.READ,
        "prose",
        lambda ctx, t, o: [
            _bin(("python", "py")) or "python",
            str(_grammalecte_cli()),
            "-ff",
            _local(ctx, t),
            "-owe",
            "-off",
            "apos",
        ],
        ("python", "py"),
    ),
    "epub_verif": Kit(
        "EPUBCheck (validité d'un EPUB, norme W3C)",
        ("celya",),
        Level.READ,
        "read",
        lambda ctx, t, o: [
            _bin(("java",)) or "java",
            "-jar",
            str(_epubcheck_jar()),
            _local(ctx, t),
        ],
        ("java",),
    ),
    "ebook": Kit(
        "Calibre (conversion de livre numérique : EPUB, AZW3, PDF, DOCX)",
        ("celya",),
        Level.WRITE,
        "convert",
        lambda ctx, t, o: [
            _bin(("ebook-convert",)) or "ebook-convert",
            _local(ctx, t),
            str(_ebook_out(ctx, t, o)),
        ],
        ("ebook-convert",),
        output=_ebook_out,
        timeout=900.0,
    ),
    # ---- Monty, cryptography
    "algos_crypto": Kit(
        "OpenSSL (algorithmes disponibles ici : KEM et signatures, post-quantique compris)",
        ("monty",),
        Level.READ,
        "read",
        lambda ctx, t, o: [_openssl(), "list", "-kem-algorithms", "-signature-algorithms"],
        ("openssl",),
        needs_target=False,
    ),
    "certificat": Kit(
        "OpenSSL (lire un certificat X.509 : émetteur, validité, algorithmes, extensions)",
        ("monty", "mistral"),
        Level.READ,
        "read",
        lambda ctx, t, o: [_openssl(), "x509", "-in", _local(ctx, t), "-noout", "-text"],
        ("openssl",),
    ),
    "certificat_lint": Kit(
        "step (contrôle d'un certificat selon les règles des autorités de certification)",
        ("monty",),
        Level.READ,
        "read",
        lambda ctx, t, o: [_bin(("step",)) or "step", "certificate", "lint", _local(ctx, t)],
        ("step",),
    ),
    "asn1": Kit(
        "OpenSSL (structure ASN.1 d'une clé publique, d'un certificat ou d'une signature)",
        ("monty",),
        Level.READ,
        "read",
        _asn1_argv,
        ("openssl",),
    ),
    "empreinte": Kit(
        "OpenSSL (empreinte d'un fichier : sha256, sha3-256, blake2b512…)",
        ("monty", "mistral"),
        Level.READ,
        "read",
        _digest_argv,
        ("openssl",),
    ),
    "cle_test": Kit(
        "OpenSSL (clé de TEST dans le workspace : ML-KEM, ML-DSA, SLH-DSA, Ed25519, EC, RSA)",
        ("monty",),
        Level.WRITE,
        "convert",
        _test_key_argv,
        ("openssl",),
        needs_target=False,
        output=_test_key_out,
    ),
    "gpg_verif": Kit(
        "GnuPG (vérifier la signature OpenPGP d'un fichier)",
        ("monty", "mistral"),
        Level.READ,
        "read",
        _gpg_argv,
        ("gpg",),
    ),
    "age_chiffrer": Kit(
        "age (chiffrer un fichier pour la clé publique d'un destinataire)",
        ("monty",),
        Level.WRITE,
        "convert",
        _age_argv,
        ("age",),
        output=_age_out,
    ),
    "sslyze": Kit(
        "SSLyze (configuration TLS d'un serveur autorisé)",
        ("monty", "mistral"),
        Level.EXTERNAL,
        "scan_remote",
        lambda ctx, t, o: [*_uv_tool("sslyze", "sslyze"), _host(t)],
        ("sslyze",),
        remote=True,
        timeout=600.0,
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
SCIENCE_AGENTS = ("ysyss", "monty")
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


# Number theory and security sizing, for Monty: bounded, no subprocess, no files.
CRYPTO_AGENTS = ("monty",)
CRYPTO_OPS = {
    "pgcd": "PGCD de deux entiers (ex. deux modules RSA qui partagent un facteur)",
    "inverse": "inverse modulaire — a, puis le module n",
    "puissance": "exponentiation modulaire — base, exposant, module",
    "premier": "test de primalité d'un entier",
    "factoriser": "factorisation d'un entier de 80 bits au plus (exercices)",
    "entropie": "entropie d'un secret aléatoire — taille de l'alphabet, longueur",
    "anniversaire": "probabilité de collision — bits de l'empreinte, nombre d'éléments",
    "force_brute": "durée d'une recherche exhaustive — bits de sécurité, essais par seconde",
}
MAX_INT_DIGITS = 2000  # big enough for RSA-4096 and beyond, small enough to stay instant


def _ints(raw: list[str], count: int, op: str) -> list[int]:
    if len(raw) != count:
        raise ActionError(f"{op} : {count} nombre(s) attendu(s)")
    try:
        nums = [int(str(v).strip().replace(" ", ""), 0) for v in raw]
    except ValueError as exc:
        raise ActionError(f"{op} : des entiers (décimal ou 0x…)") from exc
    if any(len(str(abs(n))) > MAX_INT_DIGITS for n in nums):
        raise ActionError(f"{op} : nombre trop grand")
    return nums


def crypto_maths(operation: str, values: list[str]) -> str:
    """One bounded number-theory or sizing computation (SymPy for primes); never a key."""
    import math

    import sympy as sp

    op = operation.strip().lower()
    if op == "pgcd":
        a, b = _ints(values, 2, op)
        g = math.gcd(a, b)
        return f"PGCD = {g}" + (" (facteur commun : les deux modules sont cassés)" if g > 1 else "")
    if op == "inverse":
        a, n = _ints(values, 2, op)
        try:
            return f"{a}⁻¹ mod {n} = {pow(a, -1, n)}"
        except ValueError as exc:
            raise ActionError("pas d'inverse : a et n ne sont pas premiers entre eux") from exc
    if op == "puissance":
        b, e, n = _ints(values, 3, op)
        if n <= 0 or e < 0:
            raise ActionError("puissance : module > 0 et exposant ≥ 0")
        return f"{b}^{e} mod {n} = {pow(b, e, n)}"
    if op == "premier":
        (n,) = _ints(values, 1, op)
        return f"{n} est {'premier' if sp.isprime(n) else 'composé'} ({n.bit_length()} bits)"
    if op == "factoriser":
        (n,) = _ints(values, 1, op)
        if n.bit_length() > 80 or n < 2:
            raise ActionError(
                "factoriser : un entier de 2 à 80 bits (au-delà, c'est le but de RSA)"
            )
        parts = sp.factorint(n)
        return f"{n} = " + " × ".join(f"{p}^{k}" if k > 1 else str(p) for p, k in parts.items())
    try:
        nums = [float(str(v).replace(",", ".")) for v in values]
    except ValueError as exc:
        raise ActionError(f"{op} : des nombres") from exc
    if op == "entropie" and len(nums) == 2 and nums[0] >= 2 and nums[1] >= 1:
        bits = nums[1] * math.log2(nums[0])
        return f"{bits:.1f} bits d'entropie (si chaque caractère est tiré au hasard)"
    if op == "anniversaire" and len(nums) == 2 and 1 <= nums[0] <= 1024 and nums[1] >= 1:
        space = 2.0 ** nums[0]
        p = -math.expm1(-nums[1] * (nums[1] - 1) / (2 * space))
        return f"collision : {p:.3g} ; 50 % vers {math.sqrt(2 * space * math.log(2)):.3g} éléments"
    if op == "force_brute" and len(nums) == 2 and 1 <= nums[0] <= 1024 and nums[1] > 0:
        years = 2.0 ** (nums[0] - 1) / nums[1] / 31_557_600
        return f"en moyenne {years:.3g} ans (moitié de l'espace de 2^{nums[0]:g})"
    if op in CRYPTO_OPS:
        raise ActionError(f"{op} : {CRYPTO_OPS[op]}")
    raise ActionError(f"opération inconnue : {operation} (au choix : {', '.join(CRYPTO_OPS)})")


# Betting and probability maths, for Lexy: no network, no promise of gain.
BETTING_AGENTS = ("lexy",)
BETTING_OPS = {
    "probabilite": "probabilité implicite d'une cote décimale (ex. 2.5)",
    "kelly": "mise optimale de Kelly — cote décimale, puis ta probabilité estimée (0 à 1)",
    "arbitrage": "garantie de gain ? les cotes décimales des issues (ex. 2.1 2.0)",
    "esperance": "espérance d'un pari pour 1 € misé — cote décimale, puis la probabilité (0 à 1)",
    "marge": "marge du bookmaker et cotes « justes » — les cotes décimales de toutes les issues",
    "martingale": "risque de ruine — mise de départ, capital, probabilité de gain d'un coup",
    "avantage_maison": "avantage de la maison — probabilité de gain, gain net pour 1 € (ex. 35)",
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
        if op == "esperance":
            cote, prob = nums[:2]
            if not 0 <= prob <= 1 or cote <= 1:
                raise ValueError("cote > 1 et probabilité entre 0 et 1")
            ev = prob * cote - 1
            juste = 1 / prob if prob else float("inf")
            return (
                f"Espérance : {ev:+.3f} € par euro misé ({ev:+.1%}) ; cote juste {juste:.2f}. "
                + (
                    "Positive seulement si ta probabilité est vraiment meilleure que celle du "
                    "marché — c'est rare et ça se vérifie sur des centaines de paris."
                    if ev > 0
                    else "Négative : sur la durée, ce pari fait perdre."
                )
            )
        if op == "marge":
            odds = [c for c in nums if c > 1]
            if len(odds) < 2:
                raise ValueError("au moins deux cotes décimales > 1")
            total = sum(1 / c for c in odds)
            fair = ", ".join(f"{c} → {c * total:.2f} ({100 / (c * total):.1f} %)" for c in odds)
            return (
                f"Marge du bookmaker : {(total - 1) * 100:.1f} % (retour au joueur "
                f"{100 / total:.1f} %). Cotes justes (marge retirée, répartie au prorata) : {fair}"
            )
        if op == "martingale":
            mise, capital, prob = nums[:3]
            if mise <= 0 or capital < mise or not 0 < prob < 1:
                raise ValueError("mise > 0, capital ≥ mise, probabilité entre 0 et 1")
            pertes, engage = 0, mise
            while engage + mise * 2**pertes * 2 <= capital:
                pertes += 1
                engage += mise * 2**pertes
            pertes += 1  # coups perdus d'affilée que le capital absorbe
            ruine = (1 - prob) ** pertes
            series = 1 - (1 - ruine) ** 100
            return (
                f"Avec {capital:g} € et une mise de départ de {mise:g} €, tu tiens {pertes} pertes "
                f"d'affilée (dernière mise {mise * 2 ** (pertes - 1):g} €). Risque de tout perdre "
                f"sur une série : {ruine:.2%} ; sur 100 séries : {series:.0%}. Chaque série "
                f"gagnée rapporte seulement {mise:g} €. La martingale ne change pas l'espérance "
                "(négative au casino) : elle échange beaucoup de petits gains contre une grosse "
                "perte rare, et les plafonds de table la bloquent avant."
            )
        if op == "avantage_maison":
            prob, gain = nums[:2]
            if not 0 < prob < 1 or gain <= 0:
                raise ValueError("probabilité entre 0 et 1, gain net > 0")
            edge = 1 - prob * (gain + 1)
            return (
                f"Avantage de la maison : {edge:.2%} (retour au joueur {1 - edge:.2%}). "
                "Ex. : plein à la roulette européenne = probabilité 1/37, gain 35 → 2,70 %."
            )
    except (ValueError, ZeroDivisionError, IndexError) as exc:
        raise ActionError(f"calcul impossible : {exc}") from exc
    raise ActionError(f"opération inconnue : {operation} (au choix : {', '.join(BETTING_OPS)})")


# Trading maths, for Simon (and Lexy): sizing, expectancy, risk/reward. Never a signal.
TRADING_AGENTS = ("simon", "lexy")
TRADING_OPS = {
    "taille_position": "capital, risque en % du capital, prix d'entrée, prix du stop",
    "esperance": "taux de réussite (0 à 1 ou en %), gain moyen, perte moyenne (positive)",
    "gain_risque": "prix d'entrée, prix du stop, objectif",
    "drawdown": "la suite des valeurs du capital (au moins deux)",
}
RISK_NOTE = "Rappel : un calcul n'est pas un conseil ; le trading comporte un risque de perte."


def trading(operation: str, values: list[float]) -> str:
    """One bounded trading computation; raises ActionError on bad input."""
    op = operation.strip().lower()
    nums = [float(v) for v in values]
    try:
        if op == "taille_position":
            capital, risk_pct, entry, stop = nums
            risk = capital * risk_pct / 100
            per_unit = abs(entry - stop)
            qty = risk / per_unit
            return (
                f"Risque accepté : {risk:.2f} ({risk_pct:g} % du capital) ; écart au stop "
                f"{per_unit:g} par unité → taille {qty:.6g} unités, soit {qty * entry:.2f} "
                f"engagés. Perte maximale au stop : {risk:.2f} (hors glissement et frais)."
            )
        if op == "esperance":
            win, gain, loss = nums
            win = win / 100 if win > 1 else win
            loss = abs(loss)
            expectancy = win * gain - (1 - win) * loss
            in_r = expectancy / loss
            verdict = "positive" if expectancy > 0 else "négative ou nulle"
            return (
                f"Espérance par trade : {expectancy:.2f} ({in_r:+.2f} R), {verdict}. "
                f"Seuil de réussite pour être à l'équilibre : {loss / (gain + loss) * 100:.1f} %. "
                + RISK_NOTE
            )
        if op == "gain_risque":
            entry, stop, target = nums
            ratio = abs(target - entry) / abs(entry - stop)
            return (
                f"Rapport gain/risque : {ratio:.2f} R ; il faut gagner plus de "
                f"{100 / (1 + ratio):.1f} % des trades pour être rentable (hors frais)."
            )
        if op == "drawdown":
            if len(nums) < 2:
                raise ActionError("au moins deux valeurs du capital")
            peak, worst = nums[0], 0.0
            for value in nums:
                peak = max(peak, value)
                worst = min(worst, value / peak - 1)
            return (
                f"Drawdown maximal : {worst * 100:.1f} % ; il faut "
                f"{(1 / (1 + worst) - 1) * 100:.1f} % de gain pour revenir au plus haut."
            )
    except (ValueError, ZeroDivisionError) as exc:
        raise ActionError(f"calcul impossible : {exc}") from exc
    raise ActionError(f"opération inconnue : {operation} (au choix : {', '.join(TRADING_OPS)})")


# Market data, read only: crypto from an exchange (real time), the rest from Yahoo (delayed).
MARKET_OPS = {
    "prix": "dernier prix (crypto « BTC/EUR » en temps réel ; action, indice ou forex : AAPL, "
    "^FCHI, EURUSD=X — parfois 15 min de retard)",
    "analyse": "tendance et indicateurs sur une période (options : 1mo, 3mo, 6mo, 1y, 2y, 5y)",
    "carnet": "carnet d'ordres d'une crypto (5 meilleurs prix de chaque côté)",
}
PERIODS = {"1mo": 30, "3mo": 90, "6mo": 180, "1y": 365, "2y": 730, "5y": 1825}
CRYPTO_EXCHANGE = "kraken"


def _exchange() -> Any:
    import ccxt

    return getattr(ccxt, CRYPTO_EXCHANGE)({"enableRateLimit": True, "timeout": 15000})


def _crypto_ticker(symbol: str) -> dict[str, Any]:
    return dict(_exchange().fetch_ticker(symbol))


def _crypto_book(symbol: str) -> dict[str, Any]:
    return dict(_exchange().fetch_order_book(symbol, limit=5))


def _crypto_daily(symbol: str, days: int) -> list[list[float]]:
    return [list(c) for c in _exchange().fetch_ohlcv(symbol, "1d", limit=min(days, 720))]


def _yahoo_daily(symbol: str, period: str) -> list[list[float]]:
    """[timestamp ms, open, high, low, close, volume] per day, like ccxt."""
    from datetime import UTC, datetime

    import yfinance as yf

    frame = yf.Ticker(symbol).history(period=period, interval="1d", auto_adjust=True)
    # Yahoo stamps a session at local midnight (Paris = the day before in UTC): keep its date.
    return [
        [
            datetime(ts.year, ts.month, ts.day, 12, tzinfo=UTC).timestamp() * 1000,
            row["Open"],
            row["High"],
            row["Low"],
            row["Close"],
            row["Volume"],
        ]
        for ts, row in frame.iterrows()
    ]


def _when(ms: float | None) -> str:
    from datetime import UTC, datetime

    moment = datetime.fromtimestamp(ms / 1000, UTC) if ms else datetime.now(UTC)
    return moment.strftime("%Y-%m-%d %H:%M UTC")


def _sma(values: list[float], n: int) -> float | None:
    return sum(values[-n:]) / n if len(values) >= n else None


def _rsi(closes: list[float], n: int = 14) -> float | None:
    if len(closes) <= n:
        return None
    gains = losses = 0.0
    for prev, cur in zip(closes[-n - 1 : -1], closes[-n:], strict=True):
        change = cur - prev
        gains += max(change, 0.0)
        losses += max(-change, 0.0)
    if losses == 0:
        return 100.0
    return 100 - 100 / (1 + gains / losses)


def indicators(candles: list[list[float]]) -> dict[str, float | None]:
    """Trend, volatility and drawdown from daily candles [ts, open, high, low, close, vol]."""
    import math

    closes = [float(c[4]) for c in candles]
    if len(closes) < 2:
        raise ActionError("pas assez de données sur cette période")
    returns = [b / a - 1 for a, b in zip(closes, closes[1:], strict=False) if a]
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / max(1, len(returns) - 1)
    peak, worst = closes[0], 0.0
    for value in closes:
        peak = max(peak, value)
        worst = min(worst, value / peak - 1)
    trs = [
        max(float(c[2]) - float(c[3]), abs(float(c[2]) - p), abs(float(c[3]) - p))
        for c, p in zip(candles[1:], closes, strict=False)
    ]
    return {
        "dernier": closes[-1],
        "performance": closes[-1] / closes[0] - 1,
        "volatilite": math.sqrt(var) * math.sqrt(365 if len(closes) > 300 else 252),
        "drawdown": worst,
        "sma20": _sma(closes, 20),
        "sma50": _sma(closes, 50),
        "sma200": _sma(closes, 200),
        "rsi14": _rsi(closes),
        "atr14": sum(trs[-14:]) / min(14, len(trs)) if trs else None,
    }


def market(operation: str, symbol: str, options: str = "") -> str:
    """Read-only market data, always dated and sourced; raises ActionError when unreachable."""
    op = operation.strip().lower()
    sym = symbol.strip().upper()
    if not sym:
        raise ActionError("précise le symbole (BTC/EUR, AAPL, ^FCHI, EURUSD=X…)")
    crypto = "/" in sym
    source = (
        f"{CRYPTO_EXCHANGE.capitalize()} (temps réel)"
        if crypto
        else "Yahoo Finance (peut avoir 15 min de retard ou plus)"
    )
    try:
        if op == "prix":
            if crypto:
                t = _crypto_ticker(sym)
                change = t.get("percentage")
                return (
                    f"{sym} : {t.get('last')} (achat {t.get('bid')} / vente {t.get('ask')}"
                    + (f", 24 h {change:+.2f} %" if change is not None else "")
                    + f") — {_when(t.get('timestamp'))}, source {source}."
                )
            candles = _yahoo_daily(sym, "5d")
            if not candles:
                raise ActionError(f"symbole introuvable : {sym}")
            last, prev = candles[-1], candles[-2] if len(candles) > 1 else candles[-1]
            return (
                f"{sym} : {last[4]:.4g} (veille {prev[4]:.4g}, {last[4] / prev[4] - 1:+.2%}) — "
                f"séance du {_when(last[0])[:10]}, source {source}."
            )
        if op == "carnet":
            if not crypto:
                raise ActionError("le carnet d'ordres n'est disponible que pour une crypto")
            book = _crypto_book(sym)
            bids, asks = book.get("bids") or [], book.get("asks") or []
            if not bids or not asks:
                raise ActionError("carnet vide")
            spread = asks[0][0] - bids[0][0]
            side = " | ".join
            return (
                f"{sym} — vente : {side(f'{p:g}×{q:g}' for p, q, *_ in asks[:5])}\n"
                f"achat : {side(f'{p:g}×{q:g}' for p, q, *_ in bids[:5])}\n"
                f"écart {spread:g} ({spread / asks[0][0]:.3%}) — {_when(book.get('timestamp'))}, "
                f"source {source}."
            )
        if op == "analyse":
            period = options.strip().lower() or "6mo"
            if period not in PERIODS:
                raise ActionError(f"période : {', '.join(PERIODS)}")
            candles = _crypto_daily(sym, PERIODS[period]) if crypto else _yahoo_daily(sym, period)
            if not candles:
                raise ActionError(f"symbole introuvable : {sym}")
            ind = indicators(candles)

            def fmt(key: str) -> str:
                value = ind[key]
                return "n/d" if value is None else f"{value:.4g}"

            close = ind["dernier"] or 0.0
            trend = [
                f"{name} {'au-dessus' if close > (ind[key] or 0) else 'en dessous'}"
                for name, key in (("MM20", "sma20"), ("MM50", "sma50"), ("MM200", "sma200"))
                if ind[key] is not None
            ]
            return (
                f"{sym} sur {period} (jusqu'au {_when(candles[-1][0])[:10]}) : dernier "
                f"{fmt('dernier')}, performance {(ind['performance'] or 0):+.1%}, volatilité "
                f"annualisée {(ind['volatilite'] or 0):.1%}, drawdown max "
                f"{(ind['drawdown'] or 0):.1%}.\nMoyennes mobiles : MM20 {fmt('sma20')}, MM50 "
                f"{fmt('sma50')}, MM200 {fmt('sma200')} (prix {', '.join(trend) or 'n/d'}). "
                f"RSI14 {fmt('rsi14')}, ATR14 {fmt('atr14')}.\nSource {source}. Des indicateurs "
                "décrivent le passé ; ce n'est pas un signal d'achat ou de vente."
            )
    except ActionError:
        raise
    except ImportError as exc:
        raise ActionError("données de marché indisponibles : installer l'extra markets") from exc
    except Exception as exc:  # noqa: BLE001 - network and exchange errors of every library
        raise ActionError(f"marché injoignable ou symbole invalide ({sym}) : {exc}") from exc
    raise ActionError(f"opération inconnue : {operation} (au choix : {', '.join(MARKET_OPS)})")


def _missing(name: str) -> bool:
    """A kit run by an interpreter whose program file is absent."""
    needed = {
        "languagetool": LANGUAGETOOL,
        "retro": REA_JS,
        "grammalecte": _grammalecte_cli(),
        "epub_verif": _epubcheck_jar(),
    }
    return name in needed and not needed[name].is_file()


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
                "installed": _bin(kit.bins) is not None and not _missing(name),
            }
        )
    return found


def _grammalecte(command: list[str], runner: Callable[..., Any]) -> str:
    """Grammalecte writes its findings to <file>.res.txt, never to the console: check a copy
    in a temporary folder (the manuscript's folder stays untouched) and return what it found."""
    source = Path(command[3])
    if not source.is_file():
        raise ActionError(f"fichier introuvable : {source}")
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / f"texte{source.suffix or '.txt'}"
        shutil.copyfile(source, copy)
        try:
            proc = runner(
                [*command[:3], str(copy), *command[4:]],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=TIMEOUT_S,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired as exc:
            raise ActionError(f"Grammalecte a dépassé {int(TIMEOUT_S)} s") from exc
        found = copy.with_suffix(".res.txt")
        if proc.returncode != 0 or not found.is_file():
            detail = ((proc.stderr or "") + (proc.stdout or "")).strip() or "pas de résultat"
            raise ActionError(f"Grammalecte (code {proc.returncode}) : {detail[:400]}")
        text = found.read_text(encoding="utf-8", errors="replace").strip()
    return (text or "Aucune faute trouvée par Grammalecte.")[:MAX_READ_CHARS]


def run(ctx: ActionContext, name: str, target: str = "", options: str = "") -> str:
    """Run one toolkit program and return its output (truncated)."""
    kit = KITS.get(name)
    if kit is None:
        from spectre.assistant import agent_tools

        if agent_tools.load(ctx.root, name) is not None:  # a tool Spectre gave its agents
            return agent_tools.run(ctx, name, target, options)
        raise ActionError(
            f"outil inconnu : {name} (au choix : {', '.join(KITS)}, ou ceux de outils_agents)"
        )
    if kit.agents and ctx.agent not in ("", "opus", *kit.agents):
        raise ActionError(f"{kit.label} n'est pas un outil de ton domaine")
    if _bin(kit.bins) is None or _missing(name):
        raise ActionError(f"{kit.label} n'est pas installé sur ce PC")
    if kit.needs_target and not target.strip():
        raise ActionError("précise la cible (un fichier, un dossier ou une adresse)")
    if name == "pandoc" and not options.strip():
        raise ActionError("pandoc : indique le fichier de sortie dans options (ex. sortie.docx)")
    command = kit.argv(ctx, target, options)
    runner = ctx.runner or subprocess.run
    if name == "grammalecte":
        return _grammalecte(command, runner)
    extra_env = kit.env(ctx, target, options) if kit.env is not None else {}
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
            env={**os.environ, **extra_env} if extra_env else None,
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
    if kit.report is not None and out:
        if proc.returncode != 0:  # REA answers its errors in JSON on stdout
            raise ActionError(f"{kit.label} (code {proc.returncode}) : {out[:400]}")
        kept = kit.report(ctx, target, options)
        kept.parent.mkdir(parents=True, exist_ok=True)
        kept.write_text(out, encoding="utf-8")
        preview = 4000
        more = (
            f"\n[… {len(out) - preview} caractères de plus dans le rapport]"
            if len(out) > preview
            else ""
        )
        return f"Rapport complet : {kept}\n{out[:preview]}{more}"
    body = out or err or "(aucune sortie : rien à signaler)"
    if err and out:
        body += f"\n[détails] {err[:400]}"
    return body[:MAX_READ_CHARS]
