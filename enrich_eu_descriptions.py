#!/usr/bin/env python3
"""
enrich_eu_descriptions.py — Radar Incentivi EU

Arricchisce la tabella `incentivi_eu` su Supabase con le descrizioni
dettagliate di ogni call, recuperate dall'endpoint topicDetails del
portale EU Funding & Tenders.

Endpoint per ogni call:
  https://ec.europa.eu/info/funding-tenders/opportunities/data/topicDetails/{id_lower}.json

Variabili d'ambiente richieste:
    SUPABASE_URL          URL del progetto Supabase
    SUPABASE_SERVICE_KEY  Service Role Key

Opzionali:
    ENRICH_BATCH   quante call processare in parallelo (default: 8)
    ENRICH_LIMIT   max call da processare in questa esecuzione (default: 0 = tutte)
    FORCE          se "1", riscrive anche le descrizioni già presenti

Richiede:
    pip install requests supabase
"""

import json
import os
import re
import sys
import time
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from supabase import create_client, Client

# ── CONFIGURAZIONE ────────────────────────────────────────────────────────────
SUPABASE_URL     = os.environ.get("SUPABASE_URL", "https://ncfpbqoforedqwzgsqql.supabase.co")
SERVICE_KEY      = os.environ.get("SUPABASE_SERVICE_KEY", "")
BATCH_SIZE       = int(os.environ.get("ENRICH_BATCH", "8"))
LIMIT            = int(os.environ.get("ENRICH_LIMIT", "0"))   # 0 = tutte
FORCE            = os.environ.get("FORCE", "0") == "1"

TABLE            = "incentivi_eu"
TOPIC_URL        = "https://ec.europa.eu/info/funding-tenders/opportunities/data/topicDetails/{}.json"
FALLBACK_DESC    = "Descrizione non disponibile sul portale EU Funding & Tenders."
MAX_DESC_LEN     = 4000
# ─────────────────────────────────────────────────────────────────────────────


def build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def clean_html(html: str) -> str:
    """Rimuove tag HTML e normalizza gli spazi bianchi."""
    text = re.sub(r"<style[^>]*>[\s\S]*?</style>", " ", html, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = text.replace("&lt;", "<").replace("&gt;", ">")
    text = re.sub(r"&#\d+;", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def pick_description(td: dict) -> str:
    """
    Estrae la migliore descrizione disponibile dal JSON TopicDetails.
    Prova più campi in ordine di preferenza.
    """
    for field in ("description", "objective", "callDescription", "expectedOutcome", "summary"):
        v = td.get(field, "")
        if v and isinstance(v, str):
            text = clean_html(v).strip()
            if len(text) > 80:   # scarta frammenti insignificanti
                return text[:MAX_DESC_LEN]
    return ""


def pick_budget(td: dict) -> float | None:
    """
    Estrae il budget totale dalla struttura budgetOverviewJSONItem.
    """
    try:
        budget_map = td.get("budgetOverviewJSONItem", {}).get("budgetTopicActionMap", {})
        total = 0.0
        for action_list in budget_map.values():
            for action in (action_list if isinstance(action_list, list) else [action_list]):
                for v in (action.get("budgetYearMap") or {}).values():
                    n = float(re.sub(r"[^\d.]", "", str(v)) or 0)
                    if 0 < n < 9.9e12:
                        total += n
        return total if total > 0 else None
    except Exception:
        return None


def fetch_topic_details(session: requests.Session, call_id: str) -> dict:
    """
    Chiama l'API topicDetails per un singolo bando.
    Restituisce un dict con 'desc_' e opzionalmente 'budget'.
    """
    url = TOPIC_URL.format(call_id.lower())
    result = {"desc_": FALLBACK_DESC, "budget": None, "ok": False}
    try:
        r = session.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (RadarIncentivi/2.0)",
                "Accept": "application/json",
            },
            timeout=20,
        )
        if r.status_code == 404:
            result["desc_"] = "Call non trovata nel portale EU Funding & Tenders."
            return result
        r.raise_for_status()
        data = r.json()
        td = data.get("TopicDetails", data)   # alcune risposte wrappano, altre no
        desc = pick_description(td)
        if desc:
            result["desc_"] = desc
            result["ok"] = True
        budget = pick_budget(td)
        if budget:
            result["budget"] = budget
    except requests.exceptions.Timeout:
        result["desc_"] = "Timeout durante il recupero della descrizione dal portale EU."
    except requests.exceptions.RequestException as e:
        result["desc_"] = f"Errore di rete: {str(e)[:200]}"
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        result["desc_"] = f"Errore nel parsing della risposta EU: {str(e)[:200]}"
    return result


def get_calls_to_enrich(sb: Client) -> list[dict]:
    """
    Recupera le call da Supabase che non hanno ancora una descrizione.
    Ordine: open prima, poi forthcoming, poi closed.
    """
    query = sb.table(TABLE).select("id, budget, status")
    if not FORCE:
        query = query.is_("desc_", "null")
    query = query.order("status", desc=True)   # open > forthcoming > closed
    if LIMIT > 0:
        query = query.limit(LIMIT)
    response = query.execute()
    return response.data or []


def update_call(sb: Client, call_id: str, patch: dict) -> bool:
    """Aggiorna una singola call su Supabase."""
    try:
        sb.table(TABLE).update(patch).eq("id", call_id).execute()
        return True
    except Exception as e:
        print(f"  ✗ Errore PATCH {call_id}: {e}", file=sys.stderr)
        return False


def main() -> int:
    if not SERVICE_KEY:
        print("ERRORE: SUPABASE_SERVICE_KEY non impostata.", file=sys.stderr)
        return 1

    print(f"{'='*60}")
    print(f"  Radar Incentivi — Enrichment Descrizioni EU")
    print(f"  {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"  Batch: {BATCH_SIZE} | Limit: {LIMIT or 'tutte'} | Force: {FORCE}")
    print(f"{'='*60}")

    sb = create_client(SUPABASE_URL, SERVICE_KEY)
    session = build_session()

    # Recupera le call da arricchire
    print("\nRecupero call da arricchire da Supabase...")
    calls = get_calls_to_enrich(sb)
    print(f"  → {len(calls)} call da processare")

    if not calls:
        print("\n✓ Nessuna call da arricchire. Tutto aggiornato!")
        return 0

    # Statistiche
    stats = {
        "processed": 0,
        "with_real_desc": 0,
        "fallback": 0,
        "budget_updated": 0,
        "errors": 0,
    }

    start = time.time()

    def process_one(row: dict) -> tuple[str, dict, dict]:
        call_id = row["id"]
        details = fetch_topic_details(session, call_id)

        patch: dict = {"desc_": details["desc_"]}

        # Aggiorna il budget solo se non era già presente
        if details["budget"] and not row.get("budget"):
            patch["budget"] = details["budget"]

        return call_id, details, patch

    # Processamento in parallelo con ThreadPoolExecutor
    print(f"\nProcesso {len(calls)} call in batch da {BATCH_SIZE}...\n")

    with ThreadPoolExecutor(max_workers=BATCH_SIZE) as executor:
        futures = {executor.submit(process_one, row): row for row in calls}

        for i, future in enumerate(as_completed(futures), 1):
            try:
                call_id, details, patch = future.result()
                ok = update_call(sb, call_id, patch)

                stats["processed"] += 1
                if details["ok"]:
                    stats["with_real_desc"] += 1
                else:
                    stats["fallback"] += 1
                if patch.get("budget"):
                    stats["budget_updated"] += 1
                if not ok:
                    stats["errors"] += 1

                # Progress ogni 10 call o alla fine
                if i % 10 == 0 or i == len(calls):
                    elapsed = time.time() - start
                    pct = i / len(calls) * 100
                    rate = i / elapsed if elapsed > 0 else 0
                    eta = (len(calls) - i) / rate if rate > 0 else 0
                    desc_preview = details["desc_"][:60].replace("\n", " ")
                    print(
                        f"  [{pct:5.1f}%] {i:4d}/{len(calls)} | "
                        f"{'✓' if details['ok'] else '·'} {call_id[:40]:40s} | "
                        f"ETA: {eta:.0f}s"
                    )

            except Exception as e:
                stats["errors"] += 1
                print(f"  ✗ Errore imprevisto: {e}", file=sys.stderr)

    elapsed = time.time() - start

    # Riepilogo finale
    print(f"\n{'='*60}")
    print(f"  Enrichment completato in {elapsed:.1f}s")
    print(f"{'='*60}")
    print(f"  📝 Processate:              {stats['processed']}/{len(calls)}")
    print(f"  ✅ Con descrizione reale:   {stats['with_real_desc']}")
    print(f"  ⚠️  Fallback (non trovata): {stats['fallback']}")
    print(f"  💰 Budget aggiornato:       {stats['budget_updated']}")
    print(f"  ✗  Errori PATCH:            {stats['errors']}")

    # Verifica finale su Supabase
    try:
        total_resp = sb.table(TABLE).select("id", count="exact").execute()
        desc_resp  = sb.table(TABLE).select("id", count="exact").not_.is_("desc_", "null").execute()
        total = total_resp.count or 0
        with_desc = desc_resp.count or 0
        print(f"\n  DB finale: {with_desc}/{total} call con descrizione ({with_desc/total*100:.0f}%)")
    except Exception:
        pass

    return 0 if stats["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
