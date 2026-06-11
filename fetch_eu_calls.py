#!/usr/bin/env python3
"""
fetch_eu_calls.py — Radar Incentivi EU

Scarica le call aperte dal portale EU Funding & Tenders
e salva il risultato in eu_calls_raw.json.

Programmi inclusi: Horizon Europe, Digital Europe, LIFE, CEF, COSME, EIC
Nessuna autenticazione richiesta (API pubblica).

Richiede:
    pip install requests

Uso:
    python fetch_eu_calls.py
"""

import json
import sys
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

OUTPUT_FILE = "eu_calls_raw.json"

# API pubblica EU Funding & Tenders Portal
SEARCH_URL = "https://api.tech.ec.europa.eu/search-api/prod/rest/search"

# Programmi EU di interesse
PROGRAMMES = [
    "HORIZON",        # Horizon Europe
    "DIGITAL",        # Digital Europe Programme
    "LIFE",           # LIFE Programme
    "CEF",            # Connecting Europe Facility
    "SMP",            # Single Market Programme
    "EIC",            # European Innovation Council
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; RadarIncentivi/1.0)",
    "Accept": "application/json",
    "Content-Type": "application/json",
}

PAGE_SIZE = 100


def build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def fetch_programme(session: requests.Session, programme: str) -> list[dict]:
    """Scarica tutte le call aperte per un programma specifico."""
    results = []
    page = 1

    while True:
        payload = {
            "apiKey": "SEDIA",
            "text": "*",
            "pageSize": PAGE_SIZE,
            "pageNumber": page,
            "query": {
                "bool": {
                    "must": [
                        {"term": {"programmeName": programme}},
                        {"term": {"status": "open"}},
                    ]
                }
            },
            "languages": ["en"],
        }

        try:
            r = session.post(SEARCH_URL, json=payload, headers=HEADERS, timeout=60)
            print(f"  [{programme}] pagina {page} → HTTP {r.status_code}")

            if r.status_code == 400:
                # Alcuni programmi usano endpoint diverso, proviamo GET semplice
                break
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f"  [{programme}] errore: {e}")
            break

        hits = data.get("results", data.get("hits", []))
        if not hits:
            break

        for hit in hits:
            src = hit.get("_source", hit)
            src["_programme_filter"] = programme
            results.append(src)

        total = data.get("total", data.get("totalCount", 0))
        fetched = page * PAGE_SIZE
        if fetched >= total or len(hits) < PAGE_SIZE:
            break

        page += 1
        time.sleep(0.5)

    return results


def fetch_all_calls() -> list[dict]:
    """Scarica call da tutti i programmi usando anche l'endpoint GET pubblico."""
    session = build_session()
    all_results = []
    seen_ids = set()

    # Endpoint alternativo GET — restituisce call aperte senza autenticazione
    get_url = (
        "https://api.tech.ec.europa.eu/search-api/prod/rest/search"
        "?apiKey=SEDIA&text=*&pageSize=100&pageNumber=1"
        "&query=%7B%22bool%22%3A%7B%22must%22%3A%5B%7B%22term%22%3A%7B%22status%22%3A%22open%22%7D%7D%5D%7D%7D"
    )

    print("Scarico call aperte dal portale EU Funding & Tenders...")

    # Metodo principale: POST per ogni programma
    for prog in PROGRAMMES:
        print(f"\n  Programma: {prog}")
        rows = fetch_programme(session, prog)
        for row in rows:
            rid = row.get("identifier") or row.get("id") or row.get("callIdentifier", "")
            if rid and rid not in seen_ids:
                seen_ids.add(rid)
                all_results.append(row)
        print(f"  → {len(rows)} call trovate (totale univoche: {len(all_results)})")
        time.sleep(1)

    # Fallback: endpoint GET generico se POST non ha restituito nulla
    if not all_results:
        print("\nFallback: provo endpoint GET generico...")
        try:
            r = session.get(get_url, headers=HEADERS, timeout=60)
            r.raise_for_status()
            data = r.json()
            hits = data.get("results", data.get("hits", []))
            for hit in hits:
                src = hit.get("_source", hit)
                rid = src.get("identifier") or src.get("id") or ""
                if rid and rid not in seen_ids:
                    seen_ids.add(rid)
                    all_results.append(src)
            print(f"  → {len(all_results)} call trovate via GET")
        except Exception as e:
            print(f"  Fallback fallito: {e}")

    return all_results


def main() -> int:
    calls = fetch_all_calls()

    if not calls:
        print("\nATTENZIONE: nessuna call scaricata. Verifica connessione o API.")
        # Salva file vuoto per non bloccare il workflow
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)
        return 0

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(calls, f, ensure_ascii=False, indent=2)

    print(f"\n✓ Salvate {len(calls)} call EU in {OUTPUT_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
