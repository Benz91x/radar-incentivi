# Radar Incentivi — Innovation & Ventures

Web app single-file per il monitoraggio dei bandi e incentivi pubblicati su [incentivi.gov.it](https://www.incentivi.gov.it), pensata per la service line **Deloitte Advisory — Innovation & Ventures**.

**Fonte dati:** [Open data incentivi.gov.it](https://www.incentivi.gov.it/it/open-data) · licenza [IODL v2.0](https://www.dati.gov.it/iodl/2.0/) (riuso libero con attribuzione, già riportata nel footer dell'app).

---

## 🔗 Link diretto app

> **[Apri Radar Incentivi →](https://benz91x.github.io/radar-incentivi/)**

---

## Avvio rapido (nessuna installazione)

1. Apri il link sopra nel browser.
2. Apri [incentivi.gov.it/it/open-data](https://www.incentivi.gov.it/it/open-data) e clicca **«Scarica JSON»** → ottieni `opendata-export.json`.
3. Trascina il file nell'app. Fine: ~5.500 incentivi caricati e classificati.

I dati restano salvati nel browser (IndexedDB): alla riapertura l'app riparte dall'ultimo import. Per aggiornare, ripeti i passi 2–3.

## Cosa fa

- **Dashboard** — KPI: attivi, in attivazione, in scadenza ≤ 60 gg, chiusi, in target I&V, dotazione complessiva degli attivi in target; distribuzioni per obiettivo, territorio e forma di agevolazione; top opportunità per score.
- **Schede bando** — KPI da primo colloquio con Manager/Partner: titolo (link alla scheda ufficiale), descrizione, **dotazione**, **agevolazione max**, **spesa ammessa max**, obiettivi, forma, beneficiari, territorio, ente concedente, date/sportello, badge PNRR/UE/Nazionale.
- **Score I&V** — punteggio automatico per rilevanza Innovation & Ventures. Soglie: **In target ≥ 4** · **Da valutare ≥ 2** · altrimenti **Fuori target**. Personalizzabile dal pulsante **⚙ Scoring**.
- **Condivisione team** — **👥 Stato team → Esporta**: genera un .json con esclusioni/shortlist/note da far importare ai colleghi.

## Aggiornamento automatico dati

Un **GitHub Action** esegue `refresh_dati.py` ogni notte alle 03:00 UTC e fa commit di `incentivi-data.js` nel repo. L'app lo carica automaticamente all'apertura — nessun import manuale necessario.

Puoi triggerare manualmente l'aggiornamento da: **Actions → Refresh Incentivi Data → Run workflow**.

## Aggiornamento manuale (opzionale)

```bash
pip install requests
python refresh_dati.py   # genera/aggiorna incentivi-data.js
```

## Note e limiti

- Perimetro dati = catalogo incentivi.gov.it (misure nazionali e regionali, incluse quelle cofinanziate UE/PNRR). I bandi UE "diretti" (es. Horizon Europe) non transitano dal portale.
- Gli importi sono quelli dichiarati negli open data (in euro); i valori non disponibili sono mostrati come "n.d.".
- Schema dati supportato: export ufficiale «Scarica JSON» (array di schede), oppure risposta Solr `{response:{docs:[…]}}`.
