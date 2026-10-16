"""Spectre's administrative toolbox: offices, companies, identifiers, deadlines; dated, sourced."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest

from spectre.assistant import administration as adm
from spectre.assistant import tools as tools_mod
from spectre.assistant.actions import ActionError
from spectre.assistant.db import Database
from spectre.assistant.governance import Gate

EVRY = {
    "nom": "Évry-Courcouronnes",
    "code": "91228",
    "codesPostaux": ["91000", "91080"],
    "population": 66919,
    "epci": {"nom": "CA Grand Paris Sud"},
    "departement": {"code": "91", "nom": "Essonne"},
    "region": {"nom": "Île-de-France"},
}
CAF = {
    "nom": "Caf de l'Essonne",
    "adresse": json.dumps(
        [
            {
                "type_adresse": "Adresse",
                "numero_voie": "7 rue de la Mare neuve",
                "code_postal": "91000",
                "nom_commune": "Évry-Courcouronnes",
            }
        ]
    ),
    "telephone": json.dumps([{"valeur": "32 30", "description": "du lundi au vendredi"}]),
    "site_internet": json.dumps([{"valeur": "https://www.caf.fr"}]),
    "plage_ouverture": json.dumps(
        [
            {
                "nom_jour_debut": "Lundi",
                "nom_jour_fin": "Mardi",
                "valeur_heure_debut_1": "08:30:00",
                "valeur_heure_fin_1": "16:00:00",
            }
        ]
    ),
    "pivot": json.dumps([{"type_service_local": "caf", "code_insee_commune": ["91228"]}]),
}


def fake(routes: dict[str, Any]) -> Any:
    calls: list[str] = []

    def get(url: str) -> Any:
        calls.append(url)
        for key, value in routes.items():
            if key in url:
                if isinstance(value, Exception):
                    raise value
                return value
        raise AssertionError(f"unexpected url {url}")

    get.calls = calls  # type: ignore[attr-defined]
    return get


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adm, "_today", lambda: date(2026, 10, 16))


def test_commune_sheet(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adm, "_get", fake({"geo.api.gouv.fr": [EVRY]}))
    sheet = adm.administration("commune", "Evry")
    assert "code INSEE 91228" in sheet and "Essonne (91)" in sheet
    assert "consulté le 16/10/2026" in sheet


def test_directory_finds_the_competent_office(monkeypatch: pytest.MonkeyPatch) -> None:
    get = fake({"geo.api.gouv.fr": [EVRY], "api-lannuaire": {"results": [CAF]}})
    monkeypatch.setattr(adm, "_get", get)
    text = adm.administration("annuaire", "91228", "allocations")
    assert "Caf de l'Essonne" in text and "Tél. 32 30" in text
    assert "Lundi-Mardi 08:30-16:00" in text and "DILA" in text
    assert "caf" in get.calls[-1]  # the everyday word became the directory's type


def test_directory_without_type_lists_them(monkeypatch: pytest.MonkeyPatch) -> None:
    mairie = dict(
        CAF,
        nom="Mairie",
        pivot=json.dumps([{"type_service_local": "mairie", "code_insee_commune": ["91228"]}]),
    )
    monkeypatch.setattr(
        adm,
        "_get",
        fake({"geo.api.gouv.fr": [EVRY], "api-lannuaire": {"results": [CAF, mairie]}}),
    )
    text = adm.administration("annuaire", "Évry")
    assert "caf, mairie" in text


def test_directory_reports_a_missing_office(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        adm, "_get", fake({"geo.api.gouv.fr": [EVRY], "api-lannuaire": {"results": []}})
    )
    with pytest.raises(ActionError, match="aucun service"):
        adm.administration("annuaire", "Évry", "ofii")


def test_company_sheet(monkeypatch: pytest.MonkeyPatch) -> None:
    company = {
        "nom_complet": "LA POSTE",
        "siren": "356000000",
        "etat_administratif": "A",
        "siege": {"adresse": "9 RUE DU COLONEL PIERRE AVIA 75015 PARIS", "siret": "35600000000048"},
        "activite_principale": "53.10Z",
        "nature_juridique": "5510",
        "date_creation": "1991-01-01",
        "nombre_etablissements_ouverts": 8862,
        "dirigeants": [{}, {}],
        "complements": {"est_qualiopi": True},
    }
    monkeypatch.setattr(adm, "_get", fake({"recherche-entreprises": {"results": [company]}}))
    text = adm.administration("entreprise", "356 000 000")
    assert "SIREN 356000000 (active)" in text and "Qualiopi" in text and "Sirene" in text


def test_address(monkeypatch: pytest.MonkeyPatch) -> None:
    feature = {
        "geometry": {"coordinates": [2.06, 49.03]},
        "properties": {
            "label": "8 Boulevard du Port 95000 Cergy",
            "city": "Cergy",
            "citycode": "95127",
            "score": 0.9,
            "context": "95, Val-d'Oise",
        },
    }
    monkeypatch.setattr(adm, "_get", fake({"data.geopf.fr": {"features": [feature]}}))
    text = adm.administration("adresse", "8 bd du port cergy")
    assert "INSEE 95127" in text and "90%" in text and "IGN" in text


def test_vat_through_vies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        adm, "_get", fake({"vies": {"isValid": True, "name": "ACME", "address": "1 rue\nParis"}})
    )
    assert "VALIDE dans VIES. ACME — 1 rue, Paris" in adm.administration("tva", "FR40303265045")
    monkeypatch.setattr(
        adm, "_get", fake({"vies": {"isValid": False, "userError": "MS_UNAVAILABLE"}})
    )
    assert "Réessaie" in adm.administration("tva", "FR 40 303 265 045")
    with pytest.raises(ActionError, match="mal formé"):
        adm.administration("tva", "FR00000000000")


def test_identifiers_offline() -> None:
    assert "IBAN" in adm.administration("identifiant", "FR7630006000011234567890189")
    assert "VALIDE" in adm.administration("identifiant", "73282932000074", "fr.siret")
    with pytest.raises(ActionError, match="pas un fr.siret valide"):
        adm.administration("identifiant", "73282932000075", "fr.siret")
    with pytest.raises(ActionError, match="type inconnu"):
        adm.administration("identifiant", "123", "zz.nothing")
    assert "aucun identifiant" in adm.administration("identifiant", "ABC-?")


def test_deadlines_follow_the_french_rules() -> None:
    # months: same day number, or the month's last day
    assert "16/12/2026" in adm.administration("delai", "16/10/2026", "2 mois")
    assert "28/02/2027" in adm.administration("delai", "31/12/2026", "2 mois")
    # a deadline on a holiday moves to the next working day
    moved = adm.administration("delai", "30/10/2026", "2 jours")
    assert "lundi 02/11/2026" in moved and "Toussaint" in moved
    # working days skip weekends and holidays (11 November)
    assert "vendredi 13/11/2026" in adm.administration("delai", "06/11/2026", "4 jours ouvrés")
    # a « délai franc » does not count its last day either
    assert "27/10/2026" in adm.administration("delai", "16/10/2026", "10 jours francs")
    assert "aujourd'hui" not in adm.administration("delai", "aujourd'hui", "1 an")
    with pytest.raises(ActionError, match="options attendues"):
        adm.administration("delai", "16/10/2026", "bientôt")
    with pytest.raises(ActionError, match="date de départ"):
        adm.administration("delai", "demain", "2 mois")


def test_holidays_by_region() -> None:
    alsace = adm.administration("feries", "FR-57", "2026")
    assert "03/04/2026" in alsace and "26/12/2026" in alsace  # Good Friday, St Stephen
    assert "03/04/2026" not in adm.administration("feries", "FR", "2026")
    with pytest.raises(ActionError, match="inconnu"):
        adm.administration("feries", "XX", "2026")


def test_errors_and_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adm, "_get", fake({"geo.api.gouv.fr": OSError("réseau coupé")}))
    with pytest.raises(ActionError, match="indisponibles"):
        adm.administration("commune", "Evry")
    with pytest.raises(ActionError, match="opération inconnue"):
        adm.administration("visa", "x")
    with pytest.raises(ActionError, match="précise"):
        adm.administration("entreprise", " ")


def test_administration_tool_is_spectres(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adm, "administration", lambda op, subject, opt="": f"{op}:{subject}")
    db = Database(tmp_path / "a.db")
    ctx = tools_mod.make_context(db, tmp_path / "assistant", [str(tmp_path)])
    gate = Gate(db)
    args = {"operation": "commune", "subject": "Evry"}
    assert tools_mod.execute(gate, ctx, "administration", args) == "commune:Evry"
    ctx.agent = "cursor"
    assert tools_mod.execute(gate, ctx, "administration", args).startswith("REFUSÉ")
    db.close()
