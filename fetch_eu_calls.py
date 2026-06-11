#!/usr/bin/env python3
"""
fetch_eu_calls.py — Radar Incentivi EU

Scarica le call aperte dal portale EU Funding & Tenders.

Endpoint CORRETTO (file JSON statico pubblico, nessuna auth richiesta):
  https://ec.europa.eu/info/funding-tenders/opportunities/data/referenceData/grantsTenders.json

NOTA: l'endpoint api.tech.ec.europa.eu/search-api non è pubblico
      e risponde 405/400. Usare solo il JSON statico sopra.

Richiede:
    pip install requests
"""

import json
import sys
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

OUTPUT_FILE = "eu_calls_raw.json"

# URL del JSON statico aggiornato quotidianamente dalla Commissione Europea
GRANTS_JSON_URL = (
    "https://ec.europa.eu/info/funding-tenders/opportunities/data/"
    "referenceData/grantsTenders.json"
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, */*",
    "Accept-Language": "en",
}

# Programmi da includere (None = tutti)
FILTER_PROGRAMMES = None  # es. ["HORIZON", "DIGITAL", "LIFE", "CEF"]

# Status da includere (None = tutti)
FILTER_STATUS = ["31094502", "31094501"]  # 31094502=open, 31094501=forthcoming
# Per solo open: ["31094502"]


def build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=5,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def download_grants_json(session: requests.Session) -> dict:
    """Scarica il JSON statico grantsTenders.json con progress a blocchi."""
    print(f"Scarico {GRANTS_JSON_URL} ...")
    r = session.get(GRANTS_JSON_URL, headers=HEADERS, stream=True, timeout=120)
    r.raise_for_status()

    total_size = int(r.headers.get("content-length", 0))
    downloaded = 0
    chunks = []

    for chunk in r.iter_content(chunk_size=65536):
        if chunk:
            chunks.append(chunk)
            downloaded += len(chunk)
            if total_size:
                pct = downloaded / total_size * 100
                print(f"  Download: {downloaded/1024/1024:.1f} MB / {total_size/1024/1024:.1f} MB ({pct:.0f}%)  ", end="\r")
            else:
                print(f"  Download: {downloaded/1024/1024:.1f} MB  ", end="\r")

    print()
    raw = b"".join(chunks)
    print(f"  File scaricato: {len(raw)/1024/1024:.1f} MB")
    return json.loads(raw.decode("utf-8"))


def extract_calls(data: dict) -> list[dict]:
    """
    Estrae le call/topic dal JSON grantsTenders.
    La struttura è: data["fundingData"]["GrantTenderObj"] è la lista.
    Ogni elemento ha campi come: identifier, title, status, programmeAbbreviation, ecc.
    """
    try:
        items = data["fundingData"]["GrantTenderObj"]
    except (KeyError, TypeError):
        # Struttura alternativa: lista diretta
        if isinstance(data, list):
            items = data
        else:
            print("ERRORE: struttura JSON non riconosciuta.")
            print(f"  Chiavi trovate: {list(data.keys()) if isinstance(data, dict) else type(data)}")
            return []

    print(f"  Elementi totali nel JSON: {len(items)}")

    calls = []
    seen = set()

    for item in items:
        # Filtra per status se richiesto
        if FILTER_STATUS:
            item_status = item.get("status", {}) if isinstance(item.get("status"), dict) else {}
            status_id = str(item_status.get("id", ""))
            # Alcuni record hanno status come stringa diretta
            if isinstance(item.get("status"), str):
                status_id = item["status"]
            if status_id not in FILTER_STATUS and status_id not in [""]:
                continue

        # Filtra per programma se richiesto
        if FILTER_PROGRAMMES:
            prog = item.get("programmeAbbreviation", "") or ""
            if not any(p.upper() in prog.upper() for p in FILTER_PROGRAMMES):
                continue

        # Dedup per identifier
        rid = (
            item.get("identifier") or
            item.get("id") or
            item.get("callIdentifier") or
            ""
        )
        if rid and rid in seen:
            continue
        if rid:
            seen.add(rid)

        calls.append(item)

    return calls


def normalize_call(item: dict) -> dict:
    """
    Normalizza i campi di una call in un formato piatto e leggibile.
    Compatibile con il formato atteso dal resto di radar-incentivi.
    """
    def ms_to_date(ms) -> str:
        """Converte timestamp in millisecondi in stringa YYYY-MM-DD."""
        if not ms:
            return ""
        try:
            import datetime
            return datetime.datetime.utcfromtimestamp(int(ms) / 1000).strftime("%Y-%m-%d")
        except Exception:
            return str(ms)

    status_raw = item.get("status", {})
    if isinstance(status_raw, dict):
        status_label = status_raw.get("label", status_raw.get("abbreviation", ""))
    else:
        status_label = str(status_raw)

    # Deadline: può essere lista di timestamp
    deadlines = item.get("deadlineDatesLong", []) or []
    deadline_1 = ms_to_date(deadlines[0]) if len(deadlines) > 0 else ""
    deadline_2 = ms_to_date(deadlines[1]) if len(deadlines) > 1 else ""

    identifier = (
        item.get("identifier") or
        item.get("callIdentifier") or
        item.get("id") or
        ""
    )

    title = item.get("title") or item.get("callTitle") or ""

    return {
        "identifier": identifier,
        "title": title,
        "status": status_label,
        "programme": item.get("programmeAbbreviation", ""),
        "type": item.get("type", {}).get("label", "") if isinstance(item.get("type"), dict) else str(item.get("type", "")),
        "open_date": ms_to_date(item.get("plannedOpeningDateLong") or item.get("startDate")),
        "deadline": deadline_1,
        "deadline_2": deadline_2,
        "publication_date": ms_to_date(item.get("publicationDateLong")),
        "budget_topic": item.get("budgetTopicActionBudget") or item.get("budget") or "",
        "url": (
            f"https://ec.europa.eu/info/funding-tenders/opportunities/portal/"
            f"screen/opportunities/topic-details/{identifier.lower()}"
            if identifier else ""
        ),
        "_raw": item,  # mantieni il raw per uso futuro
    }


def main() -> int:
    session = build_session()

    # 1. Scarica il JSON statico
    try:
        data = download_grants_json(session)
    except Exception as e:
        print(f"ERRORE download JSON: {e}")
        return 1

    # 2. Estrai le call
    raw_calls = extract_calls(data)
    print(f"  Call/Topic trovati dopo filtro status: {len(raw_calls)}")

    if not raw_calls:
        print("\nATTENZIONE: nessuna call estratta. Controlla i filtri FILTER_STATUS.")
        # Salva comunque una lista vuota
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)
        return 0

    # 3. Normalizza
    calls = [normalize_call(c) for c in raw_calls]

    # 4. Salva
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(calls, f, ensure_ascii=False, indent=2)

    print(f"\n✓ Salvate {len(calls)} call EU in {OUTPUT_FILE}")

    # Stampa un campione per verifica
    if calls:
        sample = calls[0]
        print("\n  Esempio prima call:")
        for k, v in sample.items():
            if k != "_raw":
                print(f"    {k}: {v}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
