#!/usr/bin/env python3
"""
upload_eu_to_supabase.py — Radar Incentivi EU

Legge eu_calls_raw.json (prodotto da fetch_eu_calls.py, formato normalizzato)
e carica/aggiorna le call EU nella tabella Supabase `incentivi_eu`.

CHANGELOG (v2):
- programma: fallback dal prefisso dell'identifier (es. CEF-DIG-2026-… → CEF),
  perché programmeAbbreviation spesso non è presente nel grantsTenders.json
- budget: parser robusto (gestisce "EUR 10 000 000", "10,000,000", liste, dict)
  e più chiavi candidate nel _raw
- descrizione: più chiavi candidate nel _raw (description/objective/summary/…)

Richiede:
    pip install requests supabase

Variabili d'ambiente:
    SUPABASE_URL          URL del progetto Supabase
    SUPABASE_SERVICE_KEY  Service Role Key
    INPUT_FILE            (opzionale) default: eu_calls_raw.json
"""

import json
import os
import re
import sys
import datetime

from supabase import create_client, Client

# ── CONFIGURAZIONE ───────────────────────────────────────────────────────────
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://ncfpbqoforedqwzgsqql.supabase.co")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
INPUT_FILE = os.environ.get("INPUT_FILE", "eu_calls_raw.json")
TABLE = "incentivi_eu"
CHUNK_SIZE = 100
# ─────────────────────────────────────────────────────────────────────────────

# Mappa dei valori status EU verso i valori normalizzati del DB.
# I valori non riconosciuti diventano "forthcoming" (più sicuro di "open").
STATUS_MAP = {
    "open": "open",
    "forthcoming": "forthcoming",
    "closed": "closed",
    "expired": "closed",
    "under evaluation": "closed",
    "signed": "closed",
    "cancelled": "closed",
    "withdrawn": "closed",
}

# Prefisso identifier plausibile come sigla di programma (CEF, CERV, HORIZON…)
PROG_PREFIX_RE = re.compile(r"^[A-Z0-9]{2,12}$")


def as_str(v) -> str:
    if isinstance(v, list):
        return str(v[0]) if v else ""
    return str(v) if v is not None else ""


def as_list(v) -> list:
    if isinstance(v, list):
        return v
    if v is None or v == "":
        return []
    return [v]


def as_dt(v) -> str | None:
    """
    Accetta stringhe YYYY-MM-DD, YYYY-MM-DDTHH:MM:SS oppure timestamp ms.
    Restituisce stringa ISO oppure None.
    """
    if not v:
        return None
    try:
        ms = int(v)
        if ms > 1_000_000_000_000:  # ms
            return datetime.datetime.utcfromtimestamp(ms / 1000).isoformat()
        elif ms > 1_000_000_000:    # secondi
            return datetime.datetime.utcfromtimestamp(ms).isoformat()
    except (ValueError, TypeError):
        pass
    s = str(v).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%d %b %Y", "%d/%m/%Y"):
        try:
            return datetime.datetime.strptime(s[:19], fmt).isoformat()
        except ValueError:
            continue
    return s


def parse_money(v) -> float | None:
    """
    Estrae un importo da formati eterogenei:
    "EUR 10 000 000", "10,000,000.00", "1.000.000", 2500000, ["5000000"], {"total": …}
    Strategia: prende il numero più grande presente nella stringa (cifre consecutive
    una volta rimossi spazi e separatori), così "EUR 10 000 000" → 10000000.
    """
    if v is None:
        return None
    if isinstance(v, dict):
        for k in ("total", "totalBudget", "value", "amount", "budget"):
            if k in v:
                return parse_money(v[k])
        return None
    if isinstance(v, list):
        vals = [parse_money(x) for x in v]
        vals = [x for x in vals if x]
        return max(vals) if vals else None
    if isinstance(v, (int, float)):
        n = float(v)
        return n if 0 < n < 9.9e12 else None
    s = str(v)
    # rimuove separatori interni alle cifre (spazi, punti, virgole tra gruppi)
    s = re.sub(r"(?<=\d)[\s.,](?=\d{3}\b)", "", s)
    nums = re.findall(r"\d+(?:[.,]\d+)?", s)
    if not nums:
        return None
    vals = []
    for n in nums:
        try:
            vals.append(float(n.replace(",", ".")))
        except ValueError:
            continue
    if not vals:
        return None
    n = max(vals)
    return n if 0 < n < 9.9e12 else None


def normalize_row(raw: dict, extracted_at: str) -> dict | None:
    """
    Mappa i campi del JSON normalizzato prodotto da fetch_eu_calls.py
    verso la struttura della tabella incentivi_eu.
    """
    _raw = raw.get("_raw", {}) or {}

    # ID univoco
    identifier = (
        as_str(raw.get("identifier"))
        or as_str(raw.get("callIdentifier"))
        or as_str(raw.get("id"))
    ).strip()
    if not identifier:
        return None

    # Titolo
    titolo = (
        as_str(raw.get("title"))
        or as_str(raw.get("callTitle"))
        or as_str(raw.get("name"))
    ).strip()

    # Descrizione: prova più campi nel normalizzato e nel _raw
    descrizione = re.sub(
        r"<[^>]+>", " ",
        as_str(
            raw.get("description")
            or raw.get("summary")
            or _raw.get("description")
            or _raw.get("descriptionByte")
            or _raw.get("objective")
            or _raw.get("callDescription")
            or _raw.get("summary")
            or _raw.get("expectedOutcome")
            or ""
        )
    ).strip()
    descrizione = re.sub(r"\s+", " ", descrizione)

    # Programma: campo esplicito, poi _raw, poi prefisso dell'identifier
    programma = (
        as_str(raw.get("programme"))
        or as_str(raw.get("programmeName"))
        or as_str(_raw.get("programmeAbbreviation"))
        or as_str(_raw.get("frameworkProgramme"))
    ).strip()
    if not programma and "-" in identifier:
        prefix = identifier.split("-", 1)[0].strip()
        if PROG_PREFIX_RE.fullmatch(prefix):
            programma = prefix

    # Date
    apertura = as_dt(
        raw.get("open_date")
        or raw.get("openingDate")
        or raw.get("startDate")
        or raw.get("publication_date")
        or _raw.get("plannedOpeningDateLong")
    )
    deadline = as_dt(
        raw.get("deadline")
        or raw.get("deadline_2")
        or raw.get("deadlineDate")
        or raw.get("closingDate")
    )
    if not deadline:
        dl_list = _raw.get("deadlineDatesLong", [])
        if dl_list:
            deadline = as_dt(dl_list[-1])

    # Budget: più chiavi candidate + parser robusto
    budget = parse_money(
        raw.get("budget_topic")
        or raw.get("budgetOverviewTotal")
        or raw.get("budget")
        or _raw.get("budgetTopicActionBudget")
        or _raw.get("budgetOverviewTotal")
        or _raw.get("budgetOverview")
        or _raw.get("totalBudget")
        or _raw.get("callBudget")
    )

    # Link
    link = (
        as_str(raw.get("url"))
        or as_str(raw.get("callDetailsUrl"))
        or as_str(_raw.get("callDetailsUrl"))
    ).strip()
    if not link and identifier:
        link = (
            f"https://ec.europa.eu/info/funding-tenders/opportunities/portal/"
            f"screen/opportunities/topic-details/{identifier.lower()}"
        )

    # Tipo
    tipo = as_str(raw.get("type") or _raw.get("type", {}) or "")

    # Status: i valori vuoti/sconosciuti diventano "forthcoming"
    status_raw = raw.get("status", "")
    if isinstance(status_raw, dict):
        status_str = as_str(status_raw.get("label") or status_raw.get("abbreviation") or "").lower().strip()
    else:
        status_str = as_str(status_raw).lower().strip()
    status = STATUS_MAP.get(status_str, status_str) or "forthcoming"

    # Settori/keyword
    settori = as_list(
        raw.get("tags")
        or raw.get("keywords")
        or _raw.get("tags")
        or _raw.get("keywords")
    )

    return {
        "id": identifier,
        "titolo": titolo,
        "desc_": descrizione[:4000],
        "programma": programma,
        "apertura": apertura,
        "chiusura": deadline,
        "budget": budget,
        "link": link,
        "settori": settori,
        "tipologie": as_list(tipo) if tipo else [],
        "status": status,
        "extracted_at": extracted_at,
        "source": "eu-funding-tenders",
    }


def upload(docs: list[dict], sb: Client):
    extracted_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    rows, seen = [], set()

    for raw in docs:
        row = normalize_row(raw, extracted_at)
        if row and row["id"] not in seen:
            seen.add(row["id"])
            rows.append(row)

    print(f"  Normalizzate {len(rows)} call EU uniche")
    print(f"  Carico su Supabase tabella '{TABLE}' in chunk da {CHUNK_SIZE}...")

    total = 0
    for i in range(0, len(rows), CHUNK_SIZE):
        chunk = rows[i: i + CHUNK_SIZE]
        sb.table(TABLE).upsert(chunk, on_conflict="id").execute()
        total += len(chunk)
        print(f"  [{int(total / len(rows) * 100):3d}%] {total}/{len(rows)}", end="\r")

    print(f"\n  ✓ Upload completato: {total} call EU su Supabase")

    # Riepilogo campi valorizzati (per verificare la qualità del parsing)
    stats = {
        "📅 Con deadline":  sum(1 for r in rows if r.get("chiusura")),
        "💰 Con budget":    sum(1 for r in rows if r.get("budget")),
        "📆 Con apertura":  sum(1 for r in rows if r.get("apertura")),
        "📁 Con programma": sum(1 for r in rows if r.get("programma")),
        "📝 Con descrizione": sum(1 for r in rows if r.get("desc_")),
        "✅ Open":          sum(1 for r in rows if r.get("status") == "open"),
        "🔜 Forthcoming":   sum(1 for r in rows if r.get("status") == "forthcoming"),
        "🔒 Closed":        sum(1 for r in rows if r.get("status") == "closed"),
    }
    for k, v in stats.items():
        print(f"  {k}: {v}/{len(rows)}" if "Con" in k else f"  {k}: {v}")


def main() -> int:
    if not SUPABASE_SERVICE_KEY:
        print("ERRORE: SUPABASE_SERVICE_KEY non impostata.", file=sys.stderr)
        return 1

    if not os.path.exists(INPUT_FILE):
        print(f"ERRORE: file {INPUT_FILE} non trovato. Esegui prima fetch_eu_calls.py",
              file=sys.stderr)
        return 1

    print(f"Leggo {INPUT_FILE}...")
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        docs = json.load(f)

    if not docs:
        print("ATTENZIONE: il file JSON e' vuoto. Nessun dato da caricare.")
        return 0

    print(f"  Documenti letti: {len(docs)}")

    sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

    try:
        upload(docs, sb)
    except Exception as e:
        print(f"ERRORE upload Supabase: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
