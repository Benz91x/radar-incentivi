#!/usr/bin/env python3
"""
upload_eu_to_supabase.py — Radar Incentivi EU

Legge eu_calls_raw.json (prodotto da fetch_eu_calls.py, formato normalizzato)
e carica/aggiorna le call EU nella tabella Supabase `incentivi_eu`.

Richiede:
    pip install requests supabase

Variabili d'ambiente:
    SUPABASE_URL          URL del progetto Supabase
    SUPABASE_SERVICE_KEY  Service Role Key
    INPUT_FILE            (opzionale) default: eu_calls_raw.json
"""

import json
import os
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
# FIX: rimosso il fallback `or "open"` che forzava i bandi scaduti/sconosciuti
# ad apparire come aperti. Ora i valori non riconosciuti diventano "forthcoming"
# (più sicuro che assumerli aperti).
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
    # Timestamp in millisecondi (intero o stringa numerica)
    try:
        ms = int(v)
        if ms > 1_000_000_000_000:  # ms
            return datetime.datetime.utcfromtimestamp(ms / 1000).isoformat()
        elif ms > 1_000_000_000:    # secondi
            return datetime.datetime.utcfromtimestamp(ms).isoformat()
    except (ValueError, TypeError):
        pass
    # Stringa data
    s = str(v).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%d %b %Y", "%d/%m/%Y"):
        try:
            return datetime.datetime.strptime(s[:19], fmt).isoformat()
        except ValueError:
            continue
    return s  # restituisce la stringa originale se non parsabile


def normalize_row(raw: dict, extracted_at: str) -> dict | None:
    """
    Mappa i campi del JSON normalizzato prodotto da fetch_eu_calls.py
    verso la struttura della tabella incentivi_eu.

    fetch_eu_calls.py produce:
        identifier, title, status, programme, type,
        open_date, deadline, deadline_2,
        publication_date, budget_topic, url, _raw
    """
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

    # Descrizione: nel formato normalizzato non c'è un campo desc dedicato,
    # si prova a leggerlo dal _raw se presente
    _raw = raw.get("_raw", {}) or {}
    import re
    descrizione = re.sub(
        r"<[^>]+>", " ",
        as_str(
            raw.get("description")
            or _raw.get("description")
            or _raw.get("objective")
            or _raw.get("callDescription")
            or ""
        )
    ).strip()
    descrizione = re.sub(r"\s+", " ", descrizione)

    # Programma
    programma = (
        as_str(raw.get("programme"))
        or as_str(raw.get("programmeName"))
        or as_str(_raw.get("programmeAbbreviation"))
    ).strip()

    # Date — formato normalizzato usa "open_date" e "deadline"
    apertura = as_dt(
        raw.get("open_date")
        or raw.get("openingDate")
        or raw.get("startDate")
        or raw.get("publication_date")
        or _raw.get("plannedOpeningDateLong")
    )

    # Deadline: prende la prima disponibile tra deadline e deadline_2
    deadline = as_dt(
        raw.get("deadline")
        or raw.get("deadline_2")
        or raw.get("deadlineDate")
        or raw.get("closingDate")
    )
    if not deadline:
        # Prova dal _raw (lista di timestamp ms)
        dl_list = _raw.get("deadlineDatesLong", [])
        if dl_list:
            deadline = as_dt(dl_list[-1])

    # Budget
    budget_raw = (
        raw.get("budget_topic")
        or raw.get("budgetOverviewTotal")
        or raw.get("budget")
        or _raw.get("budgetTopicActionBudget")
        or _raw.get("budgetOverviewTotal")
    )
    try:
        budget = float(str(budget_raw).replace(",", ".").replace(" ", "")) if budget_raw else None
        if budget and (budget <= 0 or budget > 9.9e12):
            budget = None
    except (ValueError, TypeError):
        budget = None

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

    # Status — FIX: rimosso il fallback `or "open"` che causava il bug principale.
    # I bandi con status vuoto o non riconosciuto vengono ora impostati a
    # "forthcoming" (valore sicuro) invece di "open" (valore fuorviante).
    status_raw = raw.get("status", "")
    if isinstance(status_raw, dict):
        status_str = as_str(status_raw.get("label") or status_raw.get("abbreviation") or "").lower().strip()
    else:
        status_str = as_str(status_raw).lower().strip()

    status = STATUS_MAP.get(status_str, status_str) or "forthcoming"

    # Settori/keyword dal _raw
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

    # Riepilogo campi valorizzati
    with_deadline = sum(1 for r in rows if r.get("chiusura"))
    with_budget = sum(1 for r in rows if r.get("budget"))
    with_apertura = sum(1 for r in rows if r.get("apertura"))
    open_count = sum(1 for r in rows if r.get("status") == "open")
    forthcoming_count = sum(1 for r in rows if r.get("status") == "forthcoming")
    closed_count = sum(1 for r in rows if r.get("status") == "closed")
    print(f"  📅 Con deadline: {with_deadline}/{len(rows)}")
    print(f"  💰 Con budget:   {with_budget}/{len(rows)}")
    print(f"  📆 Con apertura: {with_apertura}/{len(rows)}")
    print(f"  ✅ Open:         {open_count}")
    print(f"  🔜 Forthcoming:  {forthcoming_count}")
    print(f"  🔒 Closed:       {closed_count}")


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
