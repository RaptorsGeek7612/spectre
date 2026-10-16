"""Open nature and climate data for Shelby: species, observations, marine life, weather, climate.

Read only, free public APIs without a key: GBIF (species, IUCN status, observations), OBIS
(marine life), Open-Meteo (weather, sea surface, ERA5 reanalysis). Every answer is dated and
names its source, so the agent never quotes a figure from memory.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime, timedelta
from typing import Any

from spectre.assistant.actions import ActionError

NATURE_AGENTS = ("shelby", "ysyss")
NATURE_OPS = {
    "espece": "classification, noms français, statut UICN et observations d'une espèce (nom "
    "latin ou commun)",
    "observations": "observations par année sur 10 ans (options : code pays, FR par défaut)",
    "marin": "données de vie marine d'une espèce (OBIS)",
    "meteo": "météo actuelle d'un point « lat,lon » (et mer en surface si côtier)",
    "climat": "écart des 30 derniers jours à la normale 1991-2020 pour un point « lat,lon »",
}
GBIF = "https://api.gbif.org/v1"
OBIS = "https://api.obis.org/v3"
INAT = "https://api.inaturalist.org/v1"
BACKBONE = "d7dddbf4-2cf0-4f39-9b2a-bb099caae36c"  # the GBIF Backbone Taxonomy
IUCN = {
    "LC": "préoccupation mineure",
    "NT": "quasi menacée",
    "VU": "vulnérable",
    "EN": "en danger",
    "CR": "en danger critique",
    "EW": "éteinte à l'état sauvage",
    "EX": "éteinte",
    "DD": "données insuffisantes",
    "NE": "non évaluée",
}
TIMEOUT_S = 30.0


def _get(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "Spectre"})
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def _q(**params: Any) -> str:
    return urllib.parse.urlencode(params)


def _thousands(n: int) -> str:
    return f"{n:,}".replace(",", " ")  # French narrow space between thousands


def _today() -> date:
    return datetime.now(UTC).date()


def _match(name: str) -> dict[str, Any] | None:
    found = _get(f"{GBIF}/species/match?{_q(name=name, verbose='false')}")
    return dict(found) if found.get("usageKey") and found.get("matchType") != "NONE" else None


def _species(name: str) -> dict[str, Any]:
    """GBIF's taxon for a Latin name, or for a common name through iNaturalist (French first)."""
    found = _match(name)
    if found is None:  # a common name ("abeille", "grand dauphin"): iNaturalist knows them
        hits = _get(f"{INAT}/taxa/autocomplete?{_q(q=name, locale='fr', per_page=1)}")
        results = hits.get("results") or []
        if results and results[0].get("name"):
            found = _match(str(results[0]["name"]))
    if found is None:  # GBIF's own common names, kept only on an exact name ("ours polaire")
        hits = _get(
            f"{GBIF}/species/search?"
            + _q(q=name, qField="VERNACULAR", datasetKey=BACKBONE, limit=3)
        )
        wanted = name.strip().lower()
        for hit in hits.get("results") or []:
            names = {
                str(v.get("vernacularName", "")).lower() for v in hit.get("vernacularNames") or []
            }
            if wanted in names and hit.get("canonicalName"):
                found = _match(str(hit["canonicalName"]))
                break
    if found is None:
        raise ActionError(f"espèce introuvable : {name} (essaie le nom latin)")
    return found


def _point(text: str) -> tuple[float, float]:
    try:
        lat, lon = (float(part) for part in text.replace(";", ",").split(",")[:2])
    except ValueError as exc:
        raise ActionError("donne un point « latitude,longitude » (ex. 48.85,2.35)") from exc
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ActionError("coordonnées hors limites")
    return lat, lon


def _espece(name: str) -> str:
    sp = _species(name)
    key = sp["usageKey"]
    names = _get(f"{GBIF}/species/{key}/vernacularNames?{_q(limit=200)}").get("results") or []
    french: dict[str, str] = {}  # one entry per name, whatever its case; some hold a list
    for entry in names:
        if entry.get("language") == "fra":
            for part in str(entry.get("vernacularName", "")).split(","):
                if part.strip():
                    french.setdefault(part.strip().lower(), part.strip())
    french_names = list(french.values())[:3]
    try:
        red = _get(f"{GBIF}/species/{key}/iucnRedListCategory")
        status = f"{red.get('code', 'NE')} ({IUCN.get(red.get('code', 'NE'), '?')})"
    except OSError:
        status = "inconnu"
    count = _get(f"{GBIF}/occurrence/search?{_q(taxonKey=key, limit=0)}").get("count", 0)
    tree = " > ".join(
        str(sp[k]) for k in ("kingdom", "phylum", "class", "order", "family") if sp.get(k)
    )
    return (
        f"{sp.get('scientificName', name)} — {', '.join(french_names) or 'pas de nom français'}\n"
        f"Classification : {tree}\nListe rouge UICN : {status}\n"
        f"Observations dans GBIF : {_thousands(count)}"
        f"\nSource : GBIF et UICN, consulté le {_today():%d/%m/%Y}."
    )


def _observations(name: str, country: str) -> str:
    sp = _species(name)
    code = (country.strip() or "FR").upper()
    if len(code) != 2 or not code.isalpha():
        raise ActionError("options = code pays sur deux lettres (FR, BE, CA…)")
    end = _today().year - 1
    data = _get(
        f"{GBIF}/occurrence/search?"
        + _q(
            taxonKey=sp["usageKey"],
            country=code,
            limit=0,
            facet="year",
            year=f"{end - 9},{end}",
            facetLimit=20,
        )
    )
    counts = {c["name"]: c["count"] for c in (data.get("facets") or [{}])[0].get("counts", [])}
    years = " · ".join(f"{y} : {counts.get(str(y), 0)}" for y in range(end - 9, end + 1))
    return (
        f"{sp.get('scientificName', name)} en {code}, observations par année : {years}.\n"
        "Attention : ces chiffres suivent surtout l'effort d'observation (de plus en plus de "
        "participants), pas l'abondance réelle de l'espèce.\n"
        f"Source : GBIF, consulté le {_today():%d/%m/%Y}."
    )


def _marin(name: str) -> str:
    stats = _get(f"{OBIS}/statistics?{_q(scientificname=name.strip())}")
    records = int(stats.get("records") or 0)
    if not records:
        raise ActionError(f"aucune donnée marine pour {name} (nom latin exact attendu)")
    span = stats.get("yearrange") or []
    years = f", de {span[0]} à {span[1]}" if len(span) == 2 else ""
    return (
        f"{name.strip()} dans OBIS : {_thousands(records)} observations"
        f"{years}, {stats.get('datasets', '?')} jeux de données.\n"
        f"Source : OBIS (Ocean Biodiversity Information System), consulté le "
        f"{_today():%d/%m/%Y}."
    )


def _meteo(where: str) -> str:
    lat, lon = _point(where)
    now = _get(
        "https://api.open-meteo.com/v1/forecast?"
        + _q(
            latitude=lat,
            longitude=lon,
            current="temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m",
            timezone="auto",
        )
    ).get("current", {})
    text = (
        f"Au point {lat:.2f}, {lon:.2f} ({now.get('time', '?')}, heure locale) : "
        f"{now.get('temperature_2m')} °C, humidité {now.get('relative_humidity_2m')} %, "
        f"pluie {now.get('precipitation')} mm, vent {now.get('wind_speed_10m')} km/h."
    )
    try:
        sea = _get(
            "https://marine-api.open-meteo.com/v1/marine?"
            + _q(latitude=lat, longitude=lon, current="sea_surface_temperature,wave_height")
        ).get("current", {})
        if sea.get("sea_surface_temperature") is not None:
            text += (
                f"\nMer : {sea['sea_surface_temperature']} °C en surface, vagues "
                f"{sea.get('wave_height')} m."
            )
    except OSError:
        pass  # inland point: no marine data
    return text + "\nSource : Open-Meteo."


def _climat(where: str) -> str:
    lat, lon = _point(where)
    end = _today() - timedelta(days=6)  # the reanalysis lags a few days
    start = end - timedelta(days=29)
    recent = _get(
        "https://archive-api.open-meteo.com/v1/archive?"
        + _q(
            latitude=lat,
            longitude=lon,
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            daily="temperature_2m_mean",
        )
    )
    normal = _get(
        "https://archive-api.open-meteo.com/v1/archive?"
        + _q(
            latitude=lat,
            longitude=lon,
            start_date="1991-01-01",
            end_date="2020-12-31",
            daily="temperature_2m_mean",
        )
    )
    now_vals = [v for v in recent.get("daily", {}).get("temperature_2m_mean", []) if v is not None]
    window = {(start + timedelta(days=i)).strftime("%m-%d") for i in range(30)}
    days = normal.get("daily", {})
    ref_vals = [
        v
        for t, v in zip(days.get("time", []), days.get("temperature_2m_mean", []), strict=False)
        if v is not None and t[5:] in window
    ]
    if not now_vals or not ref_vals:
        raise ActionError("pas de données climatiques pour ce point")
    now_mean = sum(now_vals) / len(now_vals)
    ref_mean = sum(ref_vals) / len(ref_vals)
    return (
        f"Au point {lat:.2f}, {lon:.2f}, du {start:%d/%m/%Y} au {end:%d/%m/%Y} : moyenne "
        f"{now_mean:.1f} °C, contre {ref_mean:.1f} °C en moyenne sur les mêmes jours de "
        f"1991-2020, soit un écart de {now_mean - ref_mean:+.1f} °C.\n"
        "Un mois isolé est de la météo ; le climat se lit sur des décennies.\n"
        "Source : réanalyse ERA5 (Copernicus) via Open-Meteo."
    )


def nature(operation: str, subject: str, options: str = "") -> str:
    """One read-only query to open nature or climate data; raises ActionError on failure."""
    op = operation.strip().lower()
    subject = subject.strip()
    if not subject:
        raise ActionError("précise l'espèce ou le point « lat,lon »")
    handlers = {
        "espece": lambda: _espece(subject),
        "observations": lambda: _observations(subject, options),
        "marin": lambda: _marin(subject),
        "meteo": lambda: _meteo(subject),
        "climat": lambda: _climat(subject),
    }
    if op not in handlers:
        raise ActionError(f"opération inconnue : {operation} (au choix : {', '.join(NATURE_OPS)})")
    try:
        return handlers[op]()
    except ActionError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ActionError(f"données indisponibles pour le moment : {exc}") from exc
