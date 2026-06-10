#!/usr/bin/env python3
"""
upload_to_supabase.py — Radar Incentivi

Carica su Supabase i bandi da incentivi.gov.it.
- Legge il file `incentivi_raw.json` (array diretto o wrapper Solr)
- In assenza del file scarica direttamente dall'API

Richiede:
    pip install requests supabase

Variabili d'ambiente:
    SUPABASE_URL          URL del progetto Supabase
    SUPABASE_SERVICE_KEY  Service Role Key
    INPUT_FILE            (opzionale) percorso file JSON già scaricato
"""
import json
import os
import sys
import time
import datetime
import re

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from supabase import create_client, Client

# ── CONFIGURAZIONE ──────────────────────────────────────────────────
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://ncfpbqoforedqwzgsqql.supabase.co")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
INPUT_FILE = os.environ.get("INPUT_FILE", "incentivi_raw.json")

ENDPOINT = "https://www.incentivi.gov.it/solr/coredrupal/select"
FL = (
    "ID_Incentivo:zs_nid,Titolo:zs_title,Descrizione:zs_body,"
    "Obiettivo_Finalita:zm_field_scopes_value,Data_apertura:zs_field_open_date,"
    "Data_chiusura:zs_field_close_date,Note_di_apertura_chiusura:zs_field_close_date_descriptor,"
    "Dimensioni:zm_field_dimensions_value,Tipologia_Soggetto:zm_field_subject_type_value,"
    "Forma_agevolazione:zm_field_support_form_value,"
    "Spesa_Ammessa_max:zs_field_cost_max,Agevolazione_Concedibile_max:zs_field_support_grant_type_max,"
    "Settore_Attivita:zm_field_activity_sector_value,Regioni:zm_field_regions_value,"
    "Soggetto_Concedente:zs_field_subject_grant,Base_normativa_primaria:zs_field_primary_ruleset,"
    "Base_normativa_secondaria:zs_field_secondary_ruleset,"
    "Provvedimento_attuativo:zs_field_implementation_ruleset,"
    "Gazzetta_ufficiale:zs_field_official_references,"
    "Stanziamento_incentivo:zs_field_budget_allocation,Link_istituzionale:zs_field_link,"
    "Data_ultimo_aggiornamento:ds_last_update"
)
PARAMS = {"q.op": "OR", "wt": "json", "rows": "8000", "fl": FL, "q": "index_id:incentivi"}
CHUNK_SIZE = 200
SENTINEL = 9.9e10
TABLE = "incentivi"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "it-IT,it;q=0.9",
    "Referer": "https://www.incentivi.gov.it/",
}
# ────────────────────────────────────────────────────


def build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET"])
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def as_list(v):
    if isinstance(v, list): return v
    if v is None or v == "": return []
    return [v]

def as_str(v):
    if isinstance(v, list): return str(v[0]) if v else ""
    return str(v) if v is not None else ""

def as_num(v):
    try:
        n = float(as_str(v))
        return None if (n <= 0 or n >= SENTINEL) else n
    except (ValueError, TypeError):
        return None

def as_dt(v):
    s = as_str(v)
    if not s: return None
    try:
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return None


def normalize_row(raw: dict, extracted_at: str) -> dict | None:
    id_ = as_str(raw.get("ID_Incentivo") or raw.get("id"))
    if not id_: return None

    titolo = as_str(raw.get("Titolo") or raw.get("t")).strip()
    desc = re.sub(r"\s+", " ", as_str(raw.get("Descrizione") or raw.get("d"))).strip()
    regioni = as_list(raw.get("Regioni") or raw.get("re"))
    nazionale = len(regioni) == 0 or len(regioni) >= 19

    normativa = " ".join([
        as_str(raw.get("Base_normativa_primaria") or raw.get("bn")),
        as_str(raw.get("Base_normativa_secondaria", "")),
        as_str(raw.get("Provvedimento_attuativo") or raw.get("pa")),
        as_str(raw.get("Gazzetta_ufficiale") or raw.get("gu")),
    ])
    pnrr = bool(re.search(r"PNRR|piano nazionale di ripresa", normativa + titolo, re.I))
    ue = pnrr or bool(re.search(
        r"FESR|FSE\+?|FEASR|JTF|Horizon|Next ?Generation|commissione europea|"
        r"regolamento \(UE\)|decisione C ?\(|POR |PON |PR FESR|programma regionale",
        normativa + titolo, re.I
    ))

    return {
        "id": id_, "titolo": titolo, "desc_": desc,
        "obiettivi": as_list(raw.get("Obiettivo_Finalita") or raw.get("ob")),
        "apertura": as_dt(raw.get("Data_apertura") or raw.get("da")),
        "chiusura": as_dt(raw.get("Data_chiusura") or raw.get("dc")),
        "note": as_str(raw.get("Note_di_apertura_chiusura") or raw.get("no")).strip(),
        "dimensioni": as_list(raw.get("Dimensioni") or raw.get("di")),
        "tipologie": as_list(raw.get("Tipologia_Soggetto") or raw.get("ts")),
        "forme": as_list(raw.get("Forma_agevolazione") or raw.get("fa")),
        "spesa_max": as_num(raw.get("Spesa_Ammessa_max") or raw.get("sx")),
        "agev_max": as_num(raw.get("Agevolazione_Concedibile_max") or raw.get("ax")),
        "settori": as_list(raw.get("Settore_Attivita") or raw.get("se")),
        "regioni": regioni,
        "concedente": as_str(raw.get("Soggetto_Concedente") or raw.get("sc")).strip(),
        "normativa": normativa.strip(),
        "budget": as_num(raw.get("Stanziamento_incentivo") or raw.get("bu")),
        "link": as_str(raw.get("Link_istituzionale") or raw.get("li")).strip(),
        "aggiornato": as_dt(raw.get("Data_ultimo_aggiornamento") or raw.get("up")),
        "nazionale": nazionale, "pnrr": pnrr, "ue": ue,
        "extracted_at": extracted_at, "source": "incentivi.gov.it",
    }


def load_docs() -> list[dict]:
    """Legge i dati: da file locale oppure scaricando dall'API."""
    if INPUT_FILE and os.path.exists(INPUT_FILE):
        print(f"Leggo dati da file locale: {INPUT_FILE}")
        with open(INPUT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Supporta sia array diretto [{...}, ...]
        # che wrapper Solr {"response": {"docs": [...]}}
        if isinstance(data, list):
            print("  Formato: array diretto")
            docs = data
        elif isinstance(data, dict) and "response" in data:
            print("  Formato: wrapper Solr")
            docs = data["response"]["docs"]
        else:
            print("ERRORE: struttura JSON non riconosciuta.", file=sys.stderr)
            sys.exit(1)
    else:
        print("Scarico dati da incentivi.gov.it…")
        time.sleep(2)
        session = build_session()
        r = session.get(ENDPOINT, params=PARAMS, timeout=120, headers=HEADERS)
        print(f"  HTTP {r.status_code}")
        r.raise_for_status()
        data = r.json()
        docs = data["response"]["docs"]

    print(f"  Documenti ricevuti: {len(docs)}")
    return docs


def upload(docs: list[dict], sb: Client):
    extracted_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    rows, seen = [], set()
    for raw in docs:
        row = normalize_row(raw, extracted_at)
        if row and row["id"] not in seen:
            seen.add(row["id"])
            rows.append(row)

    print(f"  Normalizzati {len(rows)} incentivi unici")
    print(f"  Carico su Supabase in chunk da {CHUNK_SIZE}…")

    total = 0
    for i in range(0, len(rows), CHUNK_SIZE):
        chunk = rows[i: i + CHUNK_SIZE]
        sb.table(TABLE).upsert(chunk, on_conflict="id").execute()
        total += len(chunk)
        print(f"  [{int(total/len(rows)*100):3d}%] {total}/{len(rows)}", end="\r")

    print(f"\n  ✓ Upload completato: {total} incentivi su Supabase")


def main() -> int:
    if not SUPABASE_SERVICE_KEY:
        print("ERRORE: SUPABASE_SERVICE_KEY non impostata.", file=sys.stderr)
        return 1

    sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

    try:
        docs = load_docs()
    except Exception as e:
        print(f"ERRORE download: {e}", file=sys.stderr)
        return 1

    if not docs:
        print("ERRORE: nessun documento ricevuto.", file=sys.stderr)
        return 1

    try:
        upload(docs, sb)
    except Exception as e:
        print(f"ERRORE upload Supabase: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
