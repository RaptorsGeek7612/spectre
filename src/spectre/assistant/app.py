"""`spectre-assistant` / `python -m spectre.assistant`: the voice assistant with its web UI."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import threading
import webbrowser
from collections.abc import Sequence
from pathlib import Path

from spectre import __version__
from spectre.assistant.config import AssistantConfig, assistant_dir
from spectre.assistant.service import AssistantService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spectre-assistant",
        description=(
            "Spectre, l'assistant personnel : voix, actions sous contrôle, mémoire, missions."
        ),
    )
    parser.add_argument(
        "--voice", action="store_true", help="active la voix (mot d'éveil « Spectre »)"
    )
    parser.add_argument(
        "--camera", action="store_true", help="reconnaissance des visages enregistrés (webcam)"
    )
    parser.add_argument("--host", default="127.0.0.1", help="adresse d'écoute (défaut 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="port de l'interface (défaut 8765)")
    parser.add_argument(
        "--allow-host",
        action="append",
        default=[],
        metavar="NOM",
        help="nom d'hôte accepté derrière un relais (ex. tailscale serve) ; exige un mot de passe",
    )
    parser.add_argument("--dir", type=Path, help="dossier des données de l'assistant")
    parser.add_argument("--no-browser", action="store_true", help="n'ouvre pas le navigateur")
    parser.add_argument("--version", action="version", version=f"spectre-assistant {__version__}")
    return parser


def start_voice(service: AssistantService) -> str:  # pragma: no cover - needs audio devices
    """Load the voice stack and start the loop; return a status line."""
    from spectre.assistant.voice import engines
    from spectre.assistant.voice.loop import VoiceLoop

    models = service.root / "models"
    print("Chargement de la voix (premier lancement : téléchargement des modèles)…", flush=True)
    device, mic_name = engines.pick_microphone(service.config.mic_device)
    print(f"Micro : {mic_name}", flush=True)
    mic = engines.Microphone(device=device, on_level=service.set_level)
    wake = engines.VoskWake(models, service.config.wake_word)
    stt = engines.WhisperSTT(service.config.stt_model, service.config.language)
    tts = engines.make_tts(
        models,
        service.config.tts_voice,
        service.config.tts_speaker,
        service.config.tts_effect,
        service.config.tts_pace,
    )
    tts.on_level = service.set_level
    loop = VoiceLoop(
        mic,
        wake,
        stt,
        tts,
        service.voice_reply,
        service.set_voice_state,
        play=lambda pcm, rate: engines.play_pcm(pcm, rate),
    )
    service.attach_voice(loop)

    def run() -> None:
        with mic:
            loop.run()

    threading.Thread(target=run, name="spectre-voice", daemon=True).start()
    return f"Voix active : dis « {service.config.wake_word.capitalize()} » pour lui parler."


def start_camera(service: AssistantService) -> str:  # pragma: no cover - needs a webcam
    """Load YuNet + SFace and start watching; return a status line."""
    from spectre.assistant.vision.camera import Camera, FaceEngine

    engine = FaceEngine(service.root / "models")
    camera = Camera(engine, service.on_faces, index=service.config.camera_index)
    service.attach_camera(camera)
    camera.start()
    people = ", ".join(p["name"] for p in service.faces.people()) or "personne encore"
    return f"Caméra active (visages connus : {people}). Rien n'est enregistré sans ton accord."


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    root = args.dir or assistant_dir()
    os.environ["SPECTRE_ASSISTANT_DIR"] = str(root)  # read by the MCP tool process
    config = AssistantConfig.load(root)
    config.save(root)  # writes defaults on first run
    if shutil.which(config.claude_bin) is None:
        print(
            f"Erreur : la commande « {config.claude_bin} » (Claude Code) est introuvable.",
            file=sys.stderr,
        )
        return 1

    from spectre.web.auth import PASSWORD_ENV, Auth
    from spectre.web.server import LOCAL_HOSTS, make_server
    from spectre.web.store import Store

    password = os.environ.get(PASSWORD_ENV, "").strip() or None
    if (args.host not in LOCAL_HOSTS or args.allow_host) and password is None:
        print(
            f"Erreur : définissez {PASSWORD_ENV} avant d'ouvrir l'assistant au réseau.",
            file=sys.stderr,
        )
        return 2
    service = AssistantService(root, config)
    service.start()
    store = Store()
    try:
        server = make_server(
            args.host,
            args.port,
            store=store,
            auth=Auth(password, store.root / "secret.key"),
            assistant=service,
            extra_hosts=args.allow_host,
        )
    except OSError as exc:
        print(
            f"Erreur : impossible d'écouter sur {args.host}:{args.port} ({exc}).", file=sys.stderr
        )
        return 1
    url = f"http://127.0.0.1:{args.port}/assistant.html"
    print(f"Spectre est prêt : {url}", flush=True)
    if args.voice:  # pragma: no cover - needs audio devices
        try:
            print(start_voice(service), flush=True)
        except Exception as exc:  # noqa: BLE001 - the UI still works without voice
            print(f"Voix indisponible : {exc}", file=sys.stderr, flush=True)
    if args.camera or config.camera:  # pragma: no cover - needs a webcam
        try:
            print(start_camera(service), flush=True)
        except Exception as exc:  # noqa: BLE001 - the assistant still works without it
            print(f"Caméra indisponible : {exc}", file=sys.stderr, flush=True)
    if not args.no_browser and args.host in LOCAL_HOSTS:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt de Spectre.")
    finally:
        service.stop()
        server.server_close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
