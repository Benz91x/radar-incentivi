#!/usr/bin/env python3
"""
fetch_eu_calls.py — Radar Incentivi EU

Scarica le call aperte dal portale EU Funding & Tenders (SEDIA API)
e salva il risultato in eu_calls_raw.json.

Endpoint ufficiale:
  GET https://api.tech.ec.europa.eu/search-api/prod/rest/search
  Parametri: apiKey=SEDIA, text=*, type=CallForProposal, status=open

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
PAGE_SIZE = 50

# Endpoint GET ufficiale SEDIA — nessuna autenticazione richiesta
BASE_URL = "https://api.tech.ec.europa.eu/search-api/prod/rest/search"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Accept-Language": "en",
}


def build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=4,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def fetch_page(session: requests.Session, page: int) -> dict:
    """Scarica una pagina di call aperte via GET."""
    params = {
        "apiKey": "SEDIA",
        "text": "*",
        "pageSize": PAGE_SIZE,
        "pageNumber": page,
        "type": "CallForProposal",
        "status": "open",
        "sortBy": "startDate",
        "sortOrder": "DESC",
    }
    r = session.get(BASE_URL, params=params, headers=HEADERS, timeout=60)
    r.raise_for_status()
    return r.json()


def fetch_all_calls() -> list[dict]:
    session = build_session()
    all_results = []
    seen_ids = set()
    page = 1

    print("Scarico call aperte dal portale EU Funding & Tenders (SEDIA API)...")

    # Prima chiamata per capire quante pagine ci sono
    try:
        data = fetch_page(session, page)
    except Exception as e:
        print(f"  ERRORE prima chiamata: {e}")
        # Prova endpoint alternativo topics
        return fetch_topics_fallback(session)

    total = data.get("totalCount", data.get("total", 0))
    hits = data.get("results", data.get("hits", []))
    print(f"  Totale call disponibili: {total}")

    for item in hits:
        doc = item.get("metadata", item)
        rid = (
            doc.get("identifier", [""])[0] if isinstance(doc.get("identifier"), list)
            else doc.get("identifier") or doc.get("id") or ""
        )
        if rid and rid not in seen_ids:
            seen_ids.add(rid)
            all_results.append(doc)

    print(f"  Pagina {page}: {len(hits)} risultati → totale univoci: {len(all_results)}")

    import math
    total_pages = math.ceil(total / PAGE_SIZE) if total else 1

    for page in range(2, min(total_pages + 1, 201)):  # max 200 pagine = 10.000 call
        time.sleep(0.5)
        try:
            data = fetch_page(session, page)
            hits = data.get("results", data.get("hits", []))
            if not hits:
                break
            for item in hits:
                doc = item.get("metadata", item)
                rid = (
                    doc.get("identifier", [""])[0] if isinstance(doc.get("identifier"), list)
                    else doc.get("identifier") or doc.get("id") or ""
                )
                if rid and rid not in seen_ids:
                    seen_ids.add(rid)
                    all_results.append(doc)
            print(f"  Pagina {page}/{total_pages}: {len(hits)} risultati → totale univoci: {len(all_results)}", end="\r")
        except Exception as e:
            print(f"\n  Errore pagina {page}: {e} — interrompo")
            break

    print(f"\n  Download completato: {len(all_results)} call uniche scaricate")
    return all_results


def fetch_topics_fallback(session: requests.Session) -> list[dict]:
    """
    Fallback: usa l'endpoint /topics che restituisce i topic aperti
    di Horizon Europe e altri programmi.
    """
    print("\nFallback: provo endpoint /topics...")
    url = "https://api.tech.ec.europa.eu/search-api/prod/rest/search"
    params = {
        "apiKey": "SEDIA",
        "text": "*",
        "pageSize": PAGE_SIZE,
        "pageNumber": 1,
        "type": "Topic",
        "status": "open",
    }
    results = []
    seen_ids = set()
    page = 1

    while True:
        params["pageNumber"] = page
        try:
            r = session.get(url, params=params, headers=HEADERS, timeout=60)
            print(f"  [topics] pagina {page} → HTTP {r.status_code}")
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f"  [topics] errore: {e}")
            break

        hits = data.get("results", data.get("hits", []))
        if not hits:
            break

        for item in hits:
            doc = item.get("metadata", item)
            rid = (
                doc.get("identifier", [""])[0] if isinstance(doc.get("identifier"), list)
                else doc.get("identifier") or doc.get("id") or ""
            )
            if rid and rid not in seen_ids:
                seen_ids.add(rid)
                results.append(doc)

        total = data.get("totalCount", data.get("total", 0))
        import math
        total_pages = math.ceil(total / PAGE_SIZE) if total else 1
        print(f"  Pagina {page}/{total_pages}: {len(hits)} risultati → totale: {len(results)}")

        if page >= total_pages or len(hits) < PAGE_SIZE:
            break
        page += 1
        time.sleep(0.5)

    return results


def main() -> int:
    calls = fetch_all_calls()

    if not calls:
        print("\nATTENZIONE: nessuna call scaricata.")
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)
        return 0

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(calls, f, ensure_ascii=False, indent=2)

    print(f"\n✓ Salvate {len(calls)} call EU in {OUTPUT_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
