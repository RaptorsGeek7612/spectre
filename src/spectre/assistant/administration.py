"""Administrative toolbox for Spectre: public bodies, companies, identifiers, deadlines.

Free public sources without a key: the Service-Public.gouv.fr directory (DILA), the
Recherche d'entreprises API (Sirene, RNE), the Géo API, the Géoplateforme geocoder (IGN, which
replaced api-adresse.data.gouv.fr in January 2026) and the European Commission's VIES. Offline,
python-stdnum checks hundreds of identifiers worldwide and holidays knows public holidays of
about 250 countries. Every answer names its source and date, so Spectre never quotes an office,
a number or a deadline from memory.
"""

from __future__ import annotations

import calendar
import importlib
import json
import re
import urllib.parse
import urllib.request
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from typing import Any

from spectre.assistant.actions import ActionError

ADMIN_AGENTS = ("opus",)
ADMIN_OPS = {
    "annuaire": "guichets publics d'une commune (mairie, CAF, CPAM, préfecture, impôts, France "
    "Travail, tribunal…) ; options = type de service",
    "entreprise": "fiche d'une entreprise ou d'une association (SIREN, SIRET ou nom)",
    "commune": "code INSEE, codes postaux, département, région, intercommunalité, population",
    "adresse": "normaliser une adresse française (BAN) et trouver sa commune",
    "tva": "vérifier un numéro de TVA intracommunautaire dans VIES",
    "identifiant": "vérifier un identifiant (IBAN, SIREN, SIRET, TVA, numéros étrangers…)",
    "delai": "calculer un délai (date de départ ; options « 2 mois », « 15 jours ouvrés »…)",
    "feries": "jours fériés d'un pays ou d'une région (FR, FR-57, DE-BY…) ; options = année",
}
ANNUAIRE = (
    "https://api-lannuaire.service-public.gouv.fr/api/explore/v2.1/catalog/datasets/"
    "api-lannuaire-administration/records"
)
ENTREPRISES = "https://recherche-entreprises.api.gouv.fr/search"
GEO = "https://geo.api.gouv.fr/communes"
GEOCODAGE = "https://data.geopf.fr/geocodage/search"
VIES = "https://ec.europa.eu/taxation_customs/vies/rest-api/ms"
TIMEOUT_S = 30.0

# Everyday words for the directory's service types ("pivot"); unknown words pass as typed.
SERVICES = {
    "impots": "sip",
    "impot": "sip",
    "finances publiques": "sip",
    "pole emploi": "france_travail",
    "chomage": "france_travail",
    "police": "commissariat_police",
    "commissariat": "commissariat_police",
    "tribunal": "tgi",
    "tribunal judiciaire": "tgi",
    "prud'hommes": "prudhommes",
    "prudhommes": "prudhommes",
    "securite sociale": "cpam",
    "assurance maladie": "cpam",
    "allocations": "caf",
    "notaire": "chambre_notaires",
    "notaires": "chambre_notaires",
    "avocats": "ordre_avocats",
    "handicap": "maison_handicapees",
    "mdph": "maison_handicapees",
    "conciliateur": "point_justice",
    "acces au droit": "point_justice",
    "logement": "adil",
    "renovation": "fr_renov",
    "douane": "bureau_de_douane",
    "naturalisation": "plateforme_naturalisation",
    "etrangers": "prefecture",
    "titre de sejour": "prefecture",
}
ETATS = {"A": "active", "F": "fermée", "C": "cessée"}
UNITS = {
    "jour": "jours",
    "jours": "jours",
    "j": "jours",
    "semaine": "semaines",
    "semaines": "semaines",
    "mois": "mois",
    "an": "ans",
    "ans": "ans",
    "annee": "ans",
    "annees": "ans",
}
ACCENTS = str.maketrans("àâäéèêëîïôöùûüç", "aaaeeeeiioouuuc")


def _get(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "Spectre"})
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def _q(**params: Any) -> str:
    return urllib.parse.urlencode(params)


def _today() -> date:
    return datetime.now(UTC).date()


def _plain(text: str) -> str:
    return text.strip().lower().translate(ACCENTS)


def _stamp(source: str) -> str:
    return f"Source : {source}, consulté le {_today():%d/%m/%Y}."


def _json_list(value: Any) -> list[dict[str, Any]]:
    """The directory stores its lists as JSON text."""
    if not value:
        return []
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except ValueError:
        return []
    return [p for p in parsed if isinstance(p, dict)] if isinstance(parsed, list) else []


def _commune(text: str) -> dict[str, Any]:
    """A commune from its name, postal code or INSEE code; the most populated name match wins."""
    text = text.strip()
    fields = "nom,code,codesPostaux,departement,region,epci,population"
    found: list[dict[str, Any]]
    if re.fullmatch(r"\d[\dAB]\d{3}", text, re.IGNORECASE):  # INSEE code (2A/2B for Corsica)
        found = _get(f"{GEO}?{_q(code=text.upper(), fields=fields)}")
        if not found:  # five digits may also be a postal code
            found = _get(f"{GEO}?{_q(codePostal=text, fields=fields)}")
    else:
        found = _get(f"{GEO}?{_q(nom=text, fields=fields, boost='population', limit=5)}")
    if not found:
        raise ActionError(f"commune introuvable : {text}")
    if text.isdigit():  # a postal code shared by several communes: the most populated
        return max(found, key=lambda c: int(c.get("population") or 0))
    return found[0]


def _commune_sheet(text: str) -> str:
    c = _commune(text)
    epci = (c.get("epci") or {}).get("nom", "aucune")
    pop = c.get("population")
    return (
        f"{c['nom']} — code INSEE {c['code']}, codes postaux "
        f"{', '.join(c.get('codesPostaux') or []) or '?'}\n"
        f"Département : {(c.get('departement') or {}).get('nom', '?')} "
        f"({(c.get('departement') or {}).get('code', '?')}), région "
        f"{(c.get('region') or {}).get('nom', '?')}\nIntercommunalité : {epci}\n"
        f"Population : {pop if pop is not None else '?'} habitants\n"
        + _stamp("Géo API (INSEE, IGN) via geo.api.gouv.fr")
    )


def _service(word: str) -> str:
    plain = _plain(word)
    return SERVICES.get(plain, plain.replace(" ", "_"))


def _office(record: dict[str, Any]) -> str:
    lines = [f"• {record.get('nom', '?')}"]
    for addr in _json_list(record.get("adresse"))[:2]:
        parts = [addr.get(k, "") for k in ("numero_voie", "service_distribution")]
        place = " ".join(p for p in parts if p)
        town = f"{addr.get('code_postal', '')} {addr.get('nom_commune', '')}".strip()
        lines.append(f"  {addr.get('type_adresse', 'Adresse')} : {place}, {town}".rstrip(", "))
    for phone in _json_list(record.get("telephone"))[:2]:
        note = f" ({phone['description']})" if phone.get("description") else ""
        lines.append(f"  Tél. {phone.get('valeur', '?')}{note}")
    if record.get("adresse_courriel"):
        lines.append(f"  Courriel : {record['adresse_courriel']}")
    sites = [s.get("valeur") for s in _json_list(record.get("site_internet")) if s.get("valeur")]
    if sites:
        lines.append(f"  Site : {sites[0]}")
    hours = []
    for slot in _json_list(record.get("plage_ouverture")):
        span = slot.get("nom_jour_debut", "")
        if slot.get("nom_jour_fin") and slot["nom_jour_fin"] != span:
            span += f"-{slot['nom_jour_fin']}"
        times = [
            f"{slot[f'valeur_heure_debut_{i}'][:5]}-{slot.get(f'valeur_heure_fin_{i}', '')[:5]}"
            for i in (1, 2)
            if slot.get(f"valeur_heure_debut_{i}")
        ]
        if times:
            hours.append(f"{span} {' / '.join(times)}")
    if hours:
        lines.append(f"  Horaires : {' ; '.join(hours)}")
    return "\n".join(lines)


def _annuaire(where: str, kind: str) -> str:
    c = _commune(where)
    pivot = f'pivot like "%{c["code"]}%"'
    fields = "nom,adresse,telephone,adresse_courriel,site_internet,plage_ouverture,pivot"
    if not kind.strip():  # no type: list what the commune is attached to, then its town hall
        data = _get(f"{ANNUAIRE}?{_q(where=pivot, select='pivot', limit=100)}")
        kinds: Counter[str] = Counter()
        for record in data.get("results") or []:
            for p in _json_list(record.get("pivot")):
                if c["code"] in (p.get("code_insee_commune") or []):
                    kinds[str(p.get("type_service_local"))] += 1
        kind = "mairie"
        listing = ", ".join(sorted(kinds)) or "aucun"
        header = f"Services publics compétents pour {c['nom']} ({c['code']}) : {listing}.\n\n"
    else:
        header = ""
    wanted = _service(kind)
    data = _get(
        f"{ANNUAIRE}?"
        + _q(where=f'{pivot} and pivot like "%\\"{wanted}\\"%"', select=fields, limit=5)
    )
    records = data.get("results") or []
    if not records:
        raise ActionError(
            f"aucun service « {wanted} » compétent pour {c['nom']} ; lance annuaire sans "
            "options pour voir les types disponibles"
        )
    return (
        header
        + f"{wanted} compétent(e) pour {c['nom']} ({c['code']}) :\n"
        + "\n".join(_office(r) for r in records)
        + "\n"
        + _stamp("Annuaire de l'administration, Service-Public.gouv.fr (DILA)")
    )


def _entreprise(query: str) -> str:
    digits = re.sub(r"\s", "", query)
    data = _get(f"{ENTREPRISES}?{_q(q=digits if digits.isdigit() else query, per_page=3)}")
    results = data.get("results") or []
    if not results:
        raise ActionError(f"aucune entreprise trouvée pour « {query} »")
    blocks = []
    for e in results[: 1 if digits.isdigit() else 3]:
        siege = e.get("siege") or {}
        complements = e.get("complements") or {}
        managers = e.get("dirigeants") or []
        labels = [
            name
            for key, name in (
                ("est_association", "association"),
                ("est_ess", "ESS"),
                ("est_entrepreneur_individuel", "entrepreneur individuel"),
                ("est_service_public", "service public"),
                ("est_rge", "RGE"),
                ("est_qualiopi", "Qualiopi"),
            )
            if complements.get(key)
        ]
        blocks.append(
            f"{e.get('nom_complet', '?')} — SIREN {e.get('siren', '?')} "
            f"({ETATS.get(str(e.get('etat_administratif')), e.get('etat_administratif', '?'))})\n"
            f"  Siège : {siege.get('adresse', '?')} (SIRET {siege.get('siret', '?')})\n"
            f"  Activité (NAF) : {e.get('activite_principale', '?')} ; nature juridique "
            f"{e.get('nature_juridique', '?')} ; créée le {e.get('date_creation', '?')}\n"
            f"  Établissements ouverts : {e.get('nombre_etablissements_ouverts', '?')} ; "
            f"dirigeants connus : {len(managers)}"
            + (f"\n  Particularités : {', '.join(labels)}" if labels else "")
        )
    return (
        "\n".join(blocks)
        + "\n"
        + _stamp("API Recherche d'entreprises (INSEE Sirene, INPI RNE), annuaire-entreprises")
    )


def _adresse(text: str) -> str:
    data = _get(f"{GEOCODAGE}?{_q(q=text, limit=3, index='address')}")
    features = data.get("features") or []
    if not features:
        raise ActionError(f"adresse introuvable : {text}")
    lines = []
    for f in features:
        p = f.get("properties") or {}
        lon, lat = (f.get("geometry") or {}).get("coordinates", [None, None])
        lines.append(
            f"• {p.get('label', '?')} — commune {p.get('city', '?')} (INSEE {p.get('citycode')}), "
            f"{p.get('context', '')} ; fiabilité {float(p.get('score') or 0):.0%} ; "
            f"point {lat},{lon}"
        )
    return (
        "\n".join(lines)
        + "\n"
        + _stamp("Base Adresse Nationale, géocodeur de la Géoplateforme (IGN)")
    )


def _tva(number: str) -> str:
    from stdnum.eu import vat

    try:
        clean = vat.validate(number)
    except Exception as exc:  # stdnum raises its own ValidationError family
        raise ActionError(f"numéro de TVA mal formé : {exc}") from exc
    country, rest = clean[:2], clean[2:]
    data = _get(f"{VIES}/{'EL' if country == 'GR' else country}/vat/{rest}")
    if data.get("userError") not in (None, "VALID", "INVALID"):
        return (
            f"{clean} : forme et clé correctes, mais VIES n'a pas pu interroger l'État membre "
            f"({data['userError']}). Réessaie dans quelques minutes.\n" + _stamp("VIES")
        )
    if not data.get("isValid"):
        return (
            f"{clean} : forme correcte mais NON valide dans VIES (numéro non activé pour les "
            "échanges intracommunautaires, ou radié).\n" + _stamp("VIES (Commission européenne)")
        )
    who = " — ".join(
        str(data[k]).replace("\n", ", ").strip()
        for k in ("name", "address")
        if data.get(k) and data[k] != "---"
    )
    return f"{clean} : VALIDE dans VIES. {who}\n" + _stamp("VIES (Commission européenne)")


def _identifiant(number: str, kind: str) -> str:
    from stdnum import util

    kind = _plain(kind).replace(" ", ".").replace("-", ".")
    if kind:
        try:
            module = importlib.import_module(f"stdnum.{kind}")
        except ImportError as exc:
            raise ActionError(
                f"type inconnu : {kind} (ex. iban, bic, fr.siren, fr.siret, fr.nir, eu.vat, "
                "de.vat, es.nif, it.codicefiscale, be.vat, ch.uid, us.ein)"
            ) from exc
        try:
            clean = module.validate(number)
        except Exception as exc:
            raise ActionError(f"{number} n'est pas un {kind} valide : {exc}") from exc
        desc = (module.__doc__ or kind).strip().splitlines()[0]
        return f"{clean} : {desc} — VALIDE (forme et clé de contrôle).\nVérifié hors ligne."
    hits = []
    for candidate in util.get_number_modules():
        try:
            if candidate.is_valid(number):
                hits.append((candidate.__doc__ or str(candidate)).strip().splitlines()[0])
        except Exception:  # noqa: S112 - a module that chokes on this input simply does not match
            continue
    if not hits:
        return f"{number} : ne correspond à aucun identifiant connu (forme ou clé fausse)."
    shown = "\n".join(f"• {h}" for h in hits[:10])
    more = f"\n… et {len(hits) - 10} autres" if len(hits) > 10 else ""
    return (
        f"{number} a une forme et une clé valides pour :\n{shown}{more}\n"
        "Précise le type (options) pour trancher. Vérifié hors ligne : une clé juste ne prouve "
        "pas que le numéro existe."
    )


def _region(code: str) -> tuple[str, str | None]:
    code = (code.strip() or "FR").upper()
    country, _, subdiv = code.partition("-")
    if len(country) != 2 or not country.isalpha():
        raise ActionError("pays = code sur deux lettres, éventuellement suivi d'une région (FR-57)")
    return country, subdiv or None


def _holidays(code: str, years: list[int]) -> dict[date, str]:
    import holidays

    country, subdiv = _region(code)
    try:
        return dict(holidays.country_holidays(country, subdiv=subdiv, years=years, language="fr"))
    except (NotImplementedError, KeyError) as exc:
        raise ActionError(f"pays ou région inconnu : {code}") from exc


def _start(text: str) -> date:
    text = _plain(text)
    if text in ("", "aujourd'hui", "aujourdhui", "today"):
        return _today()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ActionError("date de départ attendue : JJ/MM/AAAA ou AAAA-MM-JJ")


def _add_months(start: date, months: int) -> date:
    """Same day number months later, or the month's last day (art. 641 CPC)."""
    year, month = divmod(start.month - 1 + months, 12)
    year += start.year
    month += 1
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))


def _delai(start_text: str, spec: str) -> str:
    start = _start(start_text)
    m = re.search(
        r"(\d+)\s*(jours?|j|semaines?|mois|ans?|annees?)\s*(ouvrables?|ouvres?|francs?)?",
        _plain(spec),
    )
    if not m:
        raise ActionError("options attendues : « 2 mois », « 15 jours », « 10 jours ouvrés »… ")
    count, unit, kind = int(m.group(1)), UNITS[m.group(2)], m.group(3) or ""
    code = next((t for t in spec.split() if re.fullmatch(r"[A-Z]{2}(-[A-Z0-9]+)?", t)), "FR")
    span = {"ans": count, "mois": count // 12}.get(unit, count // 200)  # years covered, roughly
    feries = _holidays(code, list(range(start.year, start.year + span + 3)))
    working = kind.startswith("ouvr")
    if working:  # ouvrables: Monday-Saturday; ouvrés: Monday-Friday; holidays never count
        last_weekday = 5 if kind.startswith("ouvrable") else 4
        day, left = start, count
        while left:
            day += timedelta(days=1)
            if day.weekday() <= last_weekday and day not in feries:
                left -= 1
        end = day
    elif unit == "jours":
        end = start + timedelta(days=count)  # the starting day does not count (art. 641 CPC)
        if kind.startswith("franc"):  # nor does the last one in a « délai franc »
            end += timedelta(days=1)
    elif unit == "semaines":
        end = start + timedelta(weeks=count)
    else:
        end = _add_months(start, count * (12 if unit == "ans" else 1))
    note = ""
    moved = end
    if not working:  # a deadline ending on a weekend or holiday moves to the next working day
        while moved.weekday() >= 5 or moved in feries:
            moved += timedelta(days=1)
        if moved != end:
            reason = feries.get(end, "week-end")
            note = (
                f"\nLe {end:%d/%m/%Y} tombe un jour non ouvrable ({reason}) : le délai est "
                f"prorogé au {moved:%d/%m/%Y} (art. 642 CPC ; même règle devant la "
                "plupart des administrations françaises)."
            )
    days_fr = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    kind_txt = {"ouvrable": " ouvrables", "ouvre": " ouvrés", "franc": " francs"}.get(
        kind.rstrip("s"), ""
    )
    return (
        f"Départ le {start:%d/%m/%Y} + {count} {unit}{kind_txt} : échéance le "
        f"{days_fr[moved.weekday()]} {moved:%d/%m/%Y} à minuit.{note}\n"
        + "Le jour de départ (notification, réception, publication) ne compte pas. Vérifie "
        "que le texte applicable ne fixe pas une autre règle (délai franc, préavis, "
        f"délai à l'étranger allongé). Jours fériés : {code.upper()}."
    )


def _feries(code: str, year_text: str) -> str:
    year = int(year_text) if year_text.strip().isdigit() else _today().year
    days = _holidays(code, [year])
    if not days:
        raise ActionError(f"aucun jour férié connu pour {code} en {year}")
    lines = "\n".join(f"• {d:%d/%m/%Y} : {name}" for d, name in sorted(days.items()))
    return (
        f"Jours fériés {code.upper() or 'FR'} en {year} ({len(days)}) :\n{lines}\n"
        "Source : bibliothèque holidays (calendriers officiels), calcul hors ligne. Vérifie un "
        "jour férié décidé récemment par décret."
    )


def administration(operation: str, subject: str, options: str = "") -> str:
    """One administrative lookup or computation; raises ActionError on failure."""
    op = _plain(operation)
    subject = subject.strip()
    if not subject and op not in ("delai", "feries"):
        raise ActionError("précise ce qu'il faut chercher (commune, entreprise, numéro…)")
    handlers = {
        "annuaire": lambda: _annuaire(subject, options),
        "entreprise": lambda: _entreprise(subject),
        "commune": lambda: _commune_sheet(subject),
        "adresse": lambda: _adresse(subject),
        "tva": lambda: _tva(subject),
        "identifiant": lambda: _identifiant(subject, options),
        "delai": lambda: _delai(subject, options),
        "feries": lambda: _feries(subject or "FR", options),
    }
    if op not in handlers:
        raise ActionError(f"opération inconnue : {operation} (au choix : {', '.join(ADMIN_OPS)})")
    try:
        return handlers[op]()
    except ActionError:
        raise
    except ImportError as exc:
        raise ActionError(
            "bibliothèques absentes : installe l'extra administration (python-stdnum, holidays)"
        ) from exc
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ActionError(f"données indisponibles pour le moment : {exc}") from exc
