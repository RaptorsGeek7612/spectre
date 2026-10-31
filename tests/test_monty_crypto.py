"""Monty, the cryptography expert: wiring, his toolkit (OpenSSL, GnuPG, age, TLS audits) and
his number-theory maths."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from spectre.assistant import competences, toolkit
from spectre.assistant import tools as tools_mod
from spectre.assistant.actions import ActionError
from spectre.assistant.db import Database
from spectre.assistant.governance import Level


class Runner:
    def __init__(self, make: Path | None = None) -> None:
        self.calls: list[list[str]] = []
        self.make = make

    def __call__(self, cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(cmd)
        if self.make is not None:  # the program « writes » its output file
            self.make.parent.mkdir(parents=True, exist_ok=True)
            self.make.write_text("x", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "ok", "")


@pytest.fixture
def ctx(tmp_path: Path) -> Any:
    db = Database(tmp_path / "a.db")
    home = tmp_path / "home"
    home.mkdir()
    (home / "cert.pem").write_text("-----BEGIN CERTIFICATE-----\n", encoding="utf-8")
    (home / "cle.der").write_bytes(b"\x30\x82\x01\x0a")
    (home / "paquet.zip").write_bytes(b"PK")
    (home / "paquet.zip.asc").write_text("sig", encoding="utf-8")
    context = tools_mod.make_context(db, tmp_path / "assistant", [str(home)])
    context.runner = Runner()
    context.agent = "monty"
    yield context
    db.close()


@pytest.fixture(autouse=True)
def installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(toolkit, "_bin", lambda names: "C:/bin/" + names[0])
    monkeypatch.setattr(toolkit, "_missing", lambda name: False)


def test_monty_is_wired_on_mistral() -> None:
    from spectre.assistant.config import AGENT_NAMES, AGENT_ORDER, HOSTED_AGENTS
    from spectre.assistant.missions import SPECIALTIES
    from spectre.config import AGENT_DEFAULT_ENGINES

    assert AGENT_NAMES["monty"] == "Monty" and "monty" in AGENT_ORDER and "monty" in HOSTED_AGENTS
    assert AGENT_DEFAULT_ENGINES["monty"] == "mistral"
    assert "spectre-cryptographie" in SPECIALTIES["monty"]
    names = {c.name for c in competences.available(competences.skills_dir())}
    assert "spectre-cryptographie" in names


def test_crypto_maths() -> None:
    assert toolkit.crypto_maths("pgcd", ["33", "55"]).startswith("PGCD = 11")
    assert toolkit.crypto_maths("inverse", ["3", "11"]).endswith("= 4")
    assert toolkit.crypto_maths("puissance", ["4", "13", "497"]).endswith("= 445")
    assert "premier" in toolkit.crypto_maths("premier", [str(2**127 - 1)])
    assert toolkit.crypto_maths("factoriser", ["0x1001"]) == "4097 = 17 × 241"
    assert toolkit.crypto_maths("entropie", ["26", "10"]).startswith("47.0 bits")
    assert "50 %" in toolkit.crypto_maths("anniversaire", ["64", "1000000"])
    assert "ans" in toolkit.crypto_maths("force_brute", ["128", "1e12"])
    with pytest.raises(ActionError, match="80 bits"):
        toolkit.crypto_maths("factoriser", [str(2**100 + 1)])
    with pytest.raises(ActionError, match="pas d'inverse"):
        toolkit.crypto_maths("inverse", ["2", "4"])
    with pytest.raises(ActionError, match="opération inconnue"):
        toolkit.crypto_maths("casser_rsa", ["1"])
    with pytest.raises(ActionError, match="entiers"):
        toolkit.crypto_maths("pgcd", ["a", "b"])


def test_certificates_digest_and_asn1(ctx: Any, tmp_path: Path) -> None:
    home = tmp_path / "home"
    toolkit.run(ctx, "certificat", str(home / "cert.pem"))
    assert ctx.runner.calls[-1][1:3] == ["x509", "-in"]
    toolkit.run(ctx, "empreinte", str(home / "cert.pem"), "sha3-256")
    assert ctx.runner.calls[-1][1:3] == ["dgst", "-sha3-256"]
    with pytest.raises(ActionError, match="algorithme"):
        toolkit.run(ctx, "empreinte", str(home / "cert.pem"), "crc32")
    toolkit.run(ctx, "asn1", str(home / "cle.der"))
    assert ctx.runner.calls[-1][2:4] == ["-inform", "DER"]
    toolkit.run(ctx, "asn1", str(home / "cert.pem"))
    assert "-inform" not in ctx.runner.calls[-1]
    toolkit.run(ctx, "algos_crypto")
    assert "-kem-algorithms" in ctx.runner.calls[-1]


def test_test_keys_stay_in_the_workspace(ctx: Any) -> None:
    out = toolkit._test_key_out(ctx, "demo", "ml-dsa-65")
    assert out == ctx.workspace / "crypto-test" / "TEST-ml-dsa-65-demo.pem"
    assert toolkit._test_key_out(ctx, "../../etc", "ed25519").parent == out.parent
    ctx.runner = Runner(make=out)
    assert toolkit.run(ctx, "cle_test", "demo", "ml-dsa-65").startswith("Fichier créé")
    assert ctx.runner.calls[-1][1:4] == ["genpkey", "-algorithm", "ML-DSA-65"]
    with pytest.raises(ActionError, match="algorithme"):
        toolkit.run(ctx, "cle_test", "demo", "rsa-512")


def test_gpg_and_age(ctx: Any, tmp_path: Path) -> None:
    home = tmp_path / "home"
    toolkit.run(ctx, "gpg_verif", str(home / "paquet.zip"))
    assert ctx.runner.calls[-1][-2:] == [str(home / "paquet.zip.asc"), str(home / "paquet.zip")]
    with pytest.raises(ActionError, match="clé PUBLIQUE"):
        toolkit.run(ctx, "age_chiffrer", str(home / "paquet.zip"), "AGE-SECRET-KEY-1ABC")
    ctx.runner = Runner(make=home / "paquet.zip.age")
    recipient = "age1" + "q" * 58
    assert toolkit.run(ctx, "age_chiffrer", str(home / "paquet.zip"), recipient).endswith(".age")
    assert ctx.runner.calls[-1][1:3] == ["-r", recipient]


def test_tls_audits_are_remote_and_need_a_host(ctx: Any) -> None:
    assert toolkit.KITS["sslyze"].level is Level.EXTERNAL and toolkit.KITS["sslyze"].remote
    toolkit.run(ctx, "sslyze", "https://exemple.fr:443/")
    assert ctx.runner.calls[-1][-1] == "exemple.fr:443"
    for bad in ("-oA x", "exemple.fr; rm", "exemple.fr/chemin?x"):
        with pytest.raises(ActionError, match="nom de serveur"):
            toolkit.run(ctx, "sslyze", bad)


def test_other_agents_cannot_use_montys_tools(ctx: Any) -> None:
    ctx.agent = "celya"
    with pytest.raises(ActionError, match="pas un outil de ton domaine"):
        toolkit.run(ctx, "cle_test", "demo", "ed25519")
