#!/usr/bin/env python3
"""
Refresh open data incentivi.gov.it -> incentivi-data.js
Per hosting intranet dell'app Radar Incentivi: schedulare (es. cron/Task Scheduler
notturno) nella stessa cartella di index.html. L'app carica
incentivi-data.js automaticamente all'apertura.

Fonte: Open data incentivi.gov.it (licenza IODL v2.0)
Uso: pip install requests && python refresh_dati.py
"""
import json
import sys
import datetime
from pathlib import Path

import requests

ENDPOINT = "https://www.incentivi.gov.it/solr/coredrupal/select"
FL = (
    "ID_Incentivo:zs_nid,Titolo:zs_title,Descrizione:zs_body,"
    "Obiettivo_Finalita:zm_field_scopes_value,Data_apertura:zs_field_open_date,"
    "Data_chiusura:zs_field_close_date,Note_di_apertura_chiusura:zs_field_close_date_descriptor,"
    "Dimensioni:zm_field_dimensions_value,Tipologia_Soggetto:zm_field_subject_type_value,"
    "Forma_agevolazione:zm_field_support_form_value,Costi_Ammessi:zm_field_granted_costs_value,"
    "Spesa_Ammessa_min:zs_field_cost_min,Spesa_Ammessa_max:zs_field_cost_max,"
    "Agevolazione_Concedibile_min:zs_field_support_grant_type_min,"
    "Agevolazione_Concedibile_max:zs_field_support_grant_type_max,"
    "Settore_Attivita:zm_field_activity_sector_value,Codici_ATECO:zs_field_ateco,"
    "Regioni:zm_field_regions_value,Comuni:zs_field_comuni,"
    "Ambito_territoriale:zm_field_special_territory_value,Soggetto_Concedente:zs_field_subject_grant,"
    "Base_normativa_primaria:zs_field_primary_ruleset,Base_normativa_secondaria:zs_field_secondary_ruleset,"
    "Provvedimento_attuativo:zs_field_implementation_ruleset,Gazzetta_ufficiale:zs_field_official_references,"
    "Stanziamento_incentivo:zs_field_budget_allocation,Link_istituzionale:zs_field_link,"
    "Altre_caratteristiche:zs_field_other_characteristic,Data_ultimo_aggiornamento:ds_last_update"
)

PARAMS = {"q.op": "OR", "wt": "json", "rows": "8000", "fl": FL, "q": "index_id:incentivi"}
OUT = Path(__file__).resolve().parent / "incentivi-data.js"


def main() -> int:
    try:
        r = requests.get(
            ENDPOINT,
            params=PARAMS,
            timeout=120,
            headers={"User-Agent": "Mozilla/5.0 (RadarIncentivi-refresh; uso interno)"},
        )
        r.raise_for_status()
        data = r.json()
        docs = data["response"]["docs"]
    except Exception as e:
        print(f"ERRORE durante il download: {e}", file=sys.stderr)
        return 1

    if not docs:
        print("ERRORE: nessun documento ricevuto, file non aggiornato.", file=sys.stderr)
        return 1

    payload = {
        "extractedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "docs": docs,
    }
    js = "window.INCENTIVI_DATA = " + json.dumps(payload, ensure_ascii=False) + ";\n"
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(js, encoding="utf-8")
    tmp.replace(OUT)
    print(f"OK: {len(docs)} incentivi -> {OUT.name} ({OUT.stat().st_size/1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
