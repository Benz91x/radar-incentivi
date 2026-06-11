# Radar Incentivi — Innovation & Ventures

Web app single-file per il monitoraggio dei bandi e incentivi italiani
([incentivi.gov.it](https://www.incentivi.gov.it)) ed europei
([EU Funding & Tenders Portal](https://ec.europa.eu/info/funding-tenders/opportunities/portal/)),
pensata per la service line **Deloitte Advisory — Innovation & Ventures**.

**Fonte dati:** [Open data incentivi.gov.it](https://www.incentivi.gov.it/it/open-data)
(licenza [IODL v2.0](https://www.dati.gov.it/iodl/2.0/), attribuzione nel footer dell'app)
e JSON pubblico grantsTenders della Commissione Europea.

---

## 🔗 Link diretto app

> **[Apri Radar Incentivi →](https://benz91x.github.io/radar-incentivi/)**

Nessuna installazione: i dati si caricano automaticamente da Supabase all'apertura.

---

## Architettura

```
incentivi.gov.it ──(refresh.yml, 03:00 UTC)──▶ upload_to_supabase.py ──▶ Supabase «incentivi»
EU F&T Portal ────(refresh_eu.yml, 03:30 UTC)─▶ fetch_eu_calls.py
                                               └▶ upload_eu_to_supabase.py ─▶ Supabase «incentivi_eu»
radar-incentivi.html (GitHub Pages) ◀──── REST (anon key, sola lettura catalogo)
                                    ◀───▶ «team_state» (shortlist/esclusi/note condivisi)
                                    ◀───▶ «app_config» (pesi e soglie scoring condivisi)
```

## Cosa fa

- **Dashboard / briefing mattutino** — saluto personalizzato e sintesi del giorno; KPI cliccabili:
  aperti ora, in scadenza ≤ 60 gg, in target I&V, dotazione complessiva degli attivi in target,
  call EU aperte, shortlist. Pannelli: top opportunità per score, prossime scadenze,
  attività recente del team, distribuzione score, stati MIMIT/EU, top regioni e settori.
- **Bandi** — ricerca, filtri (stato, regione, tipo/programma), ordinamento per score, scadenza,
  budget o agevolazione; chip "⏳ N gg" con colore d'urgenza; badge score con punteggio numerico
  e spiegazione al passaggio del mouse.
- **Score I&V configurabile** — pulsante **⚙ Scoring** nell'header: pesi per criterio (MIMIT ed EU),
  soglie In target / Da valutare, keyword Innovation & Ventures con bonus. La configurazione è
  salvata su Supabase e vale per tutto il team. Nel dettaglio bando: breakdown "perché questo score".
- **Collaborazione team** — al primo accesso l'app chiede il nome (salvato nel browser): shortlist,
  esclusioni e note mostrano chi ha fatto cosa e quando; il feed "Attività recente" è in dashboard.
- **Export/Import** — dalla pagina Shortlist: CSV (per Excel), JSON completo dello stato team,
  import del JSON di un collega (merge non distruttivo).

## Aggiornamento dati

Due GitHub Actions notturne (eseguibili anche a mano da **Actions → Run workflow**):

| Workflow | Orario UTC | Cosa fa |
|---|---|---|
| `refresh.yml` | 03:00 | scarica i dati **freschi** da incentivi.gov.it e li carica su `incentivi` |
| `refresh_eu.yml` | 03:30 | scarica le call dal portale EU e le carica su `incentivi_eu` |

Richiedono il secret di repository **`SUPABASE_SERVICE_KEY`** (Service Role Key).

Nota: `incentivi_raw.json` è solo uno snapshot di sviluppo; i workflow non lo usano
(`INPUT_FILE` vuoto forza il download dall'API). Può essere rimosso dal repo.

Aggiornamento manuale da locale:

```bash
pip install requests supabase
export SUPABASE_SERVICE_KEY=…   # mai committare la service key
INPUT_FILE= python upload_to_supabase.py
python fetch_eu_calls.py && python upload_eu_to_supabase.py
```

## Sicurezza

- La **anon key** nel file HTML è pubblica by design: le policy RLS permettono al ruolo anon
  la sola lettura del catalogo (`incentivi`, `incentivi_eu`) e lettura/scrittura (senza delete)
  di `team_state` e `app_config`.
- La **Service Role Key** vive solo nei secrets GitHub / variabili d'ambiente locali.

## Note e limiti

- Perimetro dati IT = catalogo incentivi.gov.it (misure nazionali e regionali, incluse quelle
  cofinanziate UE/PNRR). Le call EU "dirette" arrivano dal Funding & Tenders Portal (JSON statico
  grantsTenders): per alcune call budget e descrizione estesa non sono presenti nel feed.
- Gli importi sono quelli dichiarati nelle fonti; i valori non disponibili sono mostrati come "n.d./—".
- `refresh_dati.py` (generazione `incentivi-data.js` per hosting intranet senza Supabase) è
  mantenuto come alternativa standalone ma non è usato dall'app pubblicata.
