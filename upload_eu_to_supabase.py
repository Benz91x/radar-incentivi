#!/usr/bin/env python3
"""
upload_eu_to_supabase.py — Radar Incentivi EU

Legge eu_calls_raw.json e carica/aggiorna le call EU
nella tabella Supabase `incentivi_eu`.

Richiede:
    pip install requests supabase

Variabili d'ambiente:
    SUPABASE_URL          URL del progetto Supabase (stessa del progetto principale)
    SUPABASE_SERVICE_KEY  Service Role Key (stesso secret GitHub)
    INPUT_FILE            (opzionale) default: eu_calls_raw.json
"""

import json
import os
import sys
import re
import datetime

from supabase import create_client, Client

# ── CONFIGURAZIONE ──────────────────────────────────────────────────────────────────────────
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://ncfpbqoforedqwzgsqql.supabase.co")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
INPUT_FILE = os.environ.get("INPUT_FILE", "eu_calls_raw.json")
TABLE = "incentivi_eu"
CHUNK_SIZE = 100
# ────────────────────────────────────────────────────────────────────────────────


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
    s = as_str(v)
    if not s:
        return None
    # Formati comuni EU: 2024-12-31T00:00:00, 2024-12-31, 31 Dec 2024
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%d %b %Y", "%d/%m/%Y"):
        try:
            return datetime.datetime.strptime(s[:len(fmt)+2].strip(), fmt).isoformat()
        except ValueError:
            continue
    return s  # restituisce la stringa originale se non parsabile


def normalize_row(raw: dict, extracted_at: str) -> dict | None:
    """
    Mappa i campi dell'API EU Funding & Tenders verso la struttura
    della tabella incentivi_eu.
    """
    # ID univoco: callIdentifier o identifier o id
    identifier = (
        as_str(raw.get("callIdentifier"))
        or as_str(raw.get("identifier"))
        or as_str(raw.get("id"))
    ).strip()

    if not identifier:
        return None

    titolo = as_str(raw.get("callTitle") or raw.get("title") or raw.get("name")).strip()
    descrizione = re.sub(
        r"<[^>]+>", " ",
        as_str(raw.get("description") or raw.get("objective") or raw.get("callDescription"))
    ).strip()
    descrizione = re.sub(r"\s+", " ", descrizione)

    programma = as_str(
        raw.get("programmeName")
        or raw.get("programme")
        or raw.get("_programme_filter")
    ).strip()

    deadline_raw = (
        raw.get("deadlineDates")
        or raw.get("deadlineDate")
        or raw.get("deadline")
        or raw.get("closingDate")
    )
    if isinstance(deadline_raw, list) and deadline_raw:
        deadline = as_dt(deadline_raw[-1])  # ultima deadline se multipla
    else:
        deadline = as_dt(deadline_raw)

    apertura = as_dt(
        raw.get("openingDate")
        or raw.get("startDate")
        or raw.get("publicationDate")
    )

    budget_raw = raw.get("budgetOverviewTotal") or raw.get("budget") or raw.get("budgetTotal")
    try:
        budget = float(str(budget_raw).replace(",", ".")
                       .replace(" ", "")) if budget_raw else None
        if budget and (budget <= 0 or budget > 9.9e12):
            budget = None
    except (ValueError, TypeError):
        budget = None

    link = as_str(
        raw.get("callDetailsUrl")
        or raw.get("url")
        or raw.get("link")
    ).strip()
    # Componi link standard se manca
    if not link and identifier:
        link = f"https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/{identifier.lower()}"

    return {
        "id": identifier,
        "titolo": titolo,
        "desc_": descrizione[:4000],  # limita per evitare payload enormi
        "programma": programma,
        "apertura": apertura,
        "chiusura": deadline,
        "budget": budget,
        "link": link,
        "settori": as_list(raw.get("tags") or raw.get("keywords") or raw.get("sectors")),
        "tipologie": as_list(raw.get("actionType") or raw.get("type")),
        "status": as_str(raw.get("status", "open")).lower(),
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
