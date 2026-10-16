"""Shelby's open nature and climate data: dated, sourced, read only."""

from __future__ import annotations

from typing import Any

import pytest

from spectre.assistant import nature
from spectre.assistant import tools as tools_mod
from spectre.assistant.actions import ActionError
from spectre.assistant.db import Database
from spectre.assistant.governance import Gate

MATCH = {
    "usageKey": 2433451,
    "matchType": "EXACT",
    "scientificName": "Ursus maritimus Phipps, 1774",
    "kingdom": "Animalia",
    "class": "Mammalia",
    "family": "Ursidae",
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


def test_species_sheet(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        nature,
        "_get",
        fake(
            {
                "species/match": MATCH,
                "vernacularNames": {
                    "results": [
                        {"vernacularName": "Ours blanc, Ours polaire", "language": "fra"},
                        {"vernacularName": "ours blanc", "language": "fra"},
                        {"vernacularName": "Polar bear", "language": "eng"},
                    ]
                },
                "iucnRedListCategory": {"code": "VU"},
                "occurrence/search": {"count": 11302},
            }
        ),
    )
    sheet = nature.nature("espece", "Ursus maritimus")
    assert "Ours blanc, Ours polaire —" not in sheet  # names deduplicated, not repeated
    assert "— Ours blanc, Ours polaire\n" in sheet and "VU (vulnérable)" in sheet
    assert "11 302" in sheet and "Source : GBIF" in sheet
    assert "Animalia > Mammalia > Ursidae" in sheet


def test_common_name_goes_through_inaturalist(monkeypatch: pytest.MonkeyPatch) -> None:
    def get(url: str) -> Any:
        if "species/match" in url:
            return MATCH if "Tursiops" in url else {"matchType": "NONE"}
        if "inaturalist" in url:
            return {"results": [{"name": "Tursiops truncatus"}]}
        return {"results": [], "count": 1, "code": "LC"}

    monkeypatch.setattr(nature, "_get", get)
    assert nature._species("grand dauphin")["usageKey"] == 2433451
    monkeypatch.setattr(
        nature,
        "_get",
        lambda url: {"matchType": "NONE", "results": []},
    )
    with pytest.raises(ActionError, match="introuvable"):
        nature.nature("espece", "zzzz")


def test_observations_warn_about_effort(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        nature,
        "_get",
        fake(
            {
                "species/match": MATCH,
                "occurrence/search": {"facets": [{"counts": [{"name": "2020", "count": 55}]}]},
            }
        ),
    )
    text = nature.nature("observations", "Ursus maritimus", "ca")
    assert "en CA" in text and "2020 : 55" in text and "effort d'observation" in text
    with pytest.raises(ActionError, match="code pays"):
        nature.nature("observations", "Ursus maritimus", "France")


def test_marine_weather_and_climate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        nature,
        "_get",
        fake(
            {
                "obis.org": {"records": 11486, "datasets": 21, "yearrange": [1841, 2026]},
                "marine-api": {"current": {"sea_surface_temperature": 22.3, "wave_height": 0.1}},
                "start_date=1991": {
                    "daily": {
                        "time": [f"2000-{m:02d}-{d:02d}" for m in range(1, 13) for d in (1, 15)],
                        "temperature_2m_mean": [10.0] * 24,
                    }
                },
                "archive-api": {"daily": {"temperature_2m_mean": [13.0, 13.0, None]}},
                "api.open-meteo.com": {"current": {"temperature_2m": 21.8, "time": "t"}},
            }
        ),
    )
    assert "11 486 observations, de 1841 à 2026" in nature.nature("marin", "Posidonia oceanica")
    weather = nature.nature("meteo", "43.29,5.37")
    assert "21.8 °C" in weather and "Mer : 22.3 °C" in weather
    climate = nature.nature("climat", "48.85;2.35")
    assert "+3.0 °C" in climate and "ERA5" in climate and "décennies" in climate
    with pytest.raises(ActionError, match="latitude,longitude"):
        nature.nature("meteo", "Paris")
    with pytest.raises(ActionError, match="hors limites"):
        nature.nature("climat", "95,0")


def test_errors_and_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(nature, "_get", fake({"obis.org": OSError("réseau coupé")}))
    with pytest.raises(ActionError, match="indisponibles"):
        nature.nature("marin", "Delphinus delphis")
    with pytest.raises(ActionError, match="opération inconnue"):
        nature.nature("prevision", "x")
    with pytest.raises(ActionError, match="précise"):
        nature.nature("espece", " ")


def test_nature_tool_is_shelbys(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(nature, "nature", lambda op, subject, opt="": f"{op}:{subject}")
    db = Database(tmp_path / "a.db")
    ctx = tools_mod.make_context(db, tmp_path / "assistant", [str(tmp_path)])
    gate = Gate(db)
    ctx.agent = "shelby"
    args = {"operation": "espece", "subject": "Ursus maritimus"}
    assert tools_mod.execute(gate, ctx, "nature", args) == "espece:Ursus maritimus"
    ctx.agent = "lexy"
    assert tools_mod.execute(gate, ctx, "nature", args).startswith("REFUSÉ")
    db.close()
