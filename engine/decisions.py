"""Registro delle scelte di demo.

L'FDD lascia aperti 18 punti (OP-01..OP-18). Per avere un sistema eseguibile
alcuni di quei punti vanno risolti: ogni scelta è qui, con il punto aperto che
copre e il luogo del codice in cui vive. Nessuna decisione è nascosta nel
codice: questa tabella è quella che la dashboard mostra nella scheda
"Scelte di demo" e quella da portare in review con il cliente.
"""

DEMO_DECISIONS = [
    ("DEMO-01", "OP-12", "Risk Score -> etichetta di rischio: <=20 Basso, <=45 Moderato, "
                         "<=70 Alto, >70 Molto alto", "engine/agents.py: risk_label"),
    ("DEMO-02", "OP-10", "Se un agente non è applicabile all'asset class (es. consensus su "
                         "crypto/commodities) il suo peso è ridistribuito in proporzione sugli "
                         "altri, invece di contare 0", "engine/scoring.py: analyze_asset"),
    ("DEMO-03", "OP-11", "Breakout confermato da volumi >= 1,5x: +6 punti sul Technical Score",
     "engine/agents.py: technical_agent"),
    ("DEMO-04", "OP-12", "Valutazione finale: >=85 Strong Buy, >=75 Buy, >=55 Hold, >=40 Sell, "
                         "altrimenti Strong Sell; un gradino in meno se Risk Score > 70",
     "engine/scoring.py: final_rating"),
    ("DEMO-05", "OP-12", "Piano operativo: ingresso [prezzo-0,6 ATR; prezzo+0,2 ATR], stop a "
                         "prezzo - k x ATR (k 2,0/2,5/3,0/3,5 per livello di rischio, massimo "
                         "-20%), target = il valore stimato dall'AI Valuation Agent",
     "engine/scoring.py: operational_plan"),
    ("DEMO-06", "OP-11", "Finestra della correzione di mercato: 90 giorni",
     "engine/triggers.py: THRESHOLDS"),
    ("DEMO-07", "OP-11", "\"Fondamentali invariati\" = Fundamental Score >= 70",
     "engine/triggers.py: THRESHOLDS"),
    ("DEMO-08", "OP-11", "Insider buying significativo: acquisti netti >= 1 M$ in 90 giorni da "
                         "CEO, CFO, COO o direttore di divisione", "engine/triggers.py: THRESHOLDS"),
    ("DEMO-09", "OP-11", "Volumi elevati: >= 1,5x la media a 20 giorni",
     "engine/triggers.py: THRESHOLDS"),
    ("DEMO-10", "BR-12", "Preferenze apprese: affinità per settore sulle interazioni a 30 giorni "
                         "con decadimento; agisce sulla priorità di presentazione (0,85-1,15x), "
                         "non sull'Opportunity Score", "engine/users.py: learned_preferences"),
    ("DEMO-11", "BR-01", "Tetto di Risk Score per profilo: Conservativo 40, Bilanciato 60, "
                         "Aggressivo 85", "engine/users.py: RISK_CEILING"),
    ("DEMO-12", "OP-10", "I REIT sono trattati sotto la preferenza \"Azioni\"; le Commodities "
                         "restano fuori dalle notifiche finché il dominio del profilo non le "
                         "include - gli scarti sono tracciati con il motivo",
     "engine/users.py, engine/notifications.py"),
    ("DEMO-13", "OP-05", "Soglie degli alert di portafoglio: perdita -15%, utile +25%, drawdown "
                         "-20%, peso posizione 25%, concentrazione settoriale 35%. Il peso della "
                         "singola posizione vale solo per emittenti singoli (azioni, REIT, crypto, "
                         "commodities) e la concentrazione ignora \"Diversificato\" e "
                         "\"Obbligazionario\": un ETF globale al 40% non è una concentrazione",
     "engine/portfolio.py: ALERT_RULES"),
    ("DEMO-14", "OP-05", "Gli alert di portafoglio non consumano il limite di 3 notifiche "
                         "settimanali, che vale per le opportunità",
     "engine/portfolio.py: ALERTS_COUNT_IN_WEEKLY_LIMIT"),
    ("DEMO-15", "BR-09", "Scenari a 12 mesi: Base = stima di valore, Bull = base + 0,6 sigma, "
                         "Bear = prezzo - 0,9 sigma; probabilità funzione dell'Opportunity Score",
     "engine/reports.py: _scenarios"),
    ("DEMO-16", "OP-10", "Il filtro di settore del profilo si applica solo ad azioni e REIT: per "
                         "ETF, obbligazioni e crypto decide la preferenza di asset class",
     "engine/notifications.py: SECTOR_FILTER_CLASSES"),
    ("DEMO-17", "BR-02", "Prescreening dello scanner: trigger attivi, momentum a 3 mesi e upside "
                         "sul target; i primi 24 asset passano all'analisi profonda",
     "engine/pipeline.py: prescreen"),
    ("DEMO-18", "OP-06", "Gestione eccezioni: il fallimento di un provider su un asset lo esclude "
                         "dal ciclo e lo registra nel log, senza fermare la scansione",
     "engine/pipeline.py: run_scan"),
    ("DEMO-19", "OP-12", "Importo di esempio con cui tradurre le percentuali in euro nella vista "
                         "cliente: il 5% del capitale del profilo, arrotondato a 500. È un "
                         "esempio per far capire la posta in gioco, non una raccomandazione di "
                         "quanto investire", "engine/plain.py: EXAMPLE_SHARE_OF_CAPITAL"),
    ("DEMO-20", "OP-02", "Perimetro dell'autonomia dell'agente nella demo: osserva ogni giorno, "
                         "avvisa sui livelli di stop e target, ricorda una volta dopo sette "
                         "giorni; non invia ordini e non modifica il portafoglio",
     "engine/plain.py: commitments"),
    ("DEMO-21", "OP-07", "L'assistente a domande della vista cliente risponde da un insieme di "
                         "risposte generate dal motore, con riconoscimento della domanda su "
                         "parole chiave e nomi degli asset: una pagina statica non può tenere "
                         "la chiave API. Con backend, la domanda va a Gemini con questi stessi "
                         "dati in contesto", "engine/assistant.py"),
    ("DEMO-22", "BR-05", "Soglia del trigger \"stima di valore rialzata\": revisione di almeno "
                         "il 3% in 30 giorni", "engine/triggers.py: THRESHOLDS"),
    ("DEMO-23", "BR-03", "Modello di valutazione delle azioni: utile per azione x multiplo "
                         "giusto, dove il multiplo parte da 9 volte e paga crescita, ritorno "
                         "sul capitale e margini scontando il debito. Per le altre asset class: "
                         "rendimento atteso a 12 mesi dai dati di base",
     "engine/valuation.py"),
    ("DEMO-24", "OP-07", "Divisione del lavoro con Gemini: il modello fa valutazione, lettura "
                         "delle notizie, revisione dei punteggi calcolati (massimo ±10 punti) e "
                         "testi; gli indicatori restano calcolati dal motore perché devono "
                         "essere riproducibili. Ogni uscita del modello passa da una "
                         "validazione prima di entrare nei conti", "engine/llm.py, engine/agents.py"),
    ("DEMO-25", "OP-07", "Modello predefinito gemini-3.8-flash, sovrascrivibile con GEMINI_MODEL; "
                         "le risposte sono messe in cache su disco (.llm_cache) perché una demo "
                         "ripetuta non deve pagare due volte la stessa domanda",
     "engine/llm.py"),
    ("DEMO-26", "BR-03", "Sui dati reali il multiplo giusto è relativo: mediana dei multipli "
                         "del settore corretta per crescita, redditività e debito, con la stima "
                         "limitata a -50%/+60% dal prezzo e confidenza ridotta quando il limite "
                         "scatta", "engine/valuation.py: relative_multiple, peer_stats"),
    ("DEMO-27", "OP-08", "Senza contratto dati mancano insider, bilanci di ETF e obbligazioni e "
                         "metriche on-chain: gli strumenti senza stima di valore vengono "
                         "monitorati ma non proposti, e il motivo è dichiarato",
     "engine/real_universe.py, engine/notifications.py"),
    ("DEMO-28", "BR-07", "Canale di notifica reale: Telegram (token e chat id da variabili "
                         "d'ambiente). Email, WhatsApp e push restano simulati",
     "engine/channels.py"),
    ("DEMO-29", "BR-01", "La profilazione in onboarding è un questionario a risposta chiusa: "
                         "nessun importo da dichiarare e nessuna posizione obbligatoria. Le "
                         "regole risposte→profilo sono dati in engine/onboarding.py, "
                         "interpretati sia dal motore sia dalla pagina",
     "engine/onboarding.py, web/onboarding.js"),
    ("DEMO-30", "BR-01", "Senza capitale dichiarato le percentuali si traducono su una base "
                         "neutra di 1.000 euro (\"ogni 1.000 euro investiti\"); il tetto del "
                         "5% per singola idea resta come regola, non come cifra",
     "engine/plain.py: example_amount"),
    ("DEMO-31", "BR-08", "Il portafoglio è facoltativo: senza posizioni dichiarate l'agente "
                         "lavora solo sul mercato e lo dice, invece di chiedere i dati",
     "engine/plain.py: portfolio_plain, engine/portfolio.py"),
    ("DEMO-32", "BR-01", "L'esperienza dichiarata può solo ridurre il profilo di rischio, non "
                         "ampliarlo: chi dichiara di non avere esperienza non arriva ad "
                         "Aggressivo", "engine/onboarding.py: profile_from_answers"),
    ("DEMO-33", "OP-07", "Il ragionamento interno del modello (thinking) è spento: i suoi token "
                         "escono dallo stesso tetto della risposta, e con i tetti stretti di "
                         "questo ciclo la risposta tornava vuota. Il giudizio è guidato da "
                         "prompt e schema; riaccendibile con GEMINI_THINKING=1 (alzando i "
                         "tetti di token); se un modello non accetta il campo si riprova senza",
     "engine/llm.py: generate_json"),
    ("DEMO-34", "OP-07", "Tetto di chiamate per ciclo (--llm-budget): la quota del piano "
                         "gratuito e' giornaliera, quindi per fare due cicli al giorno "
                         "ognuno deve sapere quanto puo' spendere. Esaurito il tetto le "
                         "analisi restanti passano al calcolo e il ciclo lo dichiara",
     "engine/llm.py: budget, engine/pipeline.py"),
    ("DEMO-35", "BR-10", "Il nome della cache del service worker pubblicato e' l'impronta "
                         "dei file della pagina: cambia solo quando la pagina cambia "
                         "davvero. Senza, chi ha gia' aperto il sito continuerebbe a vedere "
                         "la versione vecchia dopo ogni nuova pubblicazione",
     "build_web.py: _timbra_sw"),
]

FDD_CHANGES = [
    ("BR-03", "L'Analyst Consensus Agent è sostituito dall'AI Valuation Agent: il sistema non "
              "consuma rating e target price di analisti umani, stima il valore da sé con "
              "engine/valuation.py e lo fa giudicare da Gemini. Gli agenti restano otto."),
    ("BR-04", "Il peso del 25% resta invariato ma cambia titolare: \"Analyst 25%\" diventa "
              "\"Valutazione AI 25%\". Le fasce di classificazione non cambiano."),
    ("BR-01", "La profilazione non raccoglie capitale disponibile né posizioni: il committente "
              "non vuole che l'utente dichiari i propri dati patrimoniali. Al loro posto un "
              "questionario a risposta chiusa che determina gli stessi campi usati dal motore; "
              "il portafoglio resta facoltativo e la traduzione in euro usa una base neutra."),
    ("BR-05", "Il trigger \"upgrade degli analisti\" diventa \"stima di valore rialzata\": "
              "scatta quando la revisione della guidance dell'emittente alza la stima del "
              "sistema di almeno il 3% in 30 giorni."),
    ("3.2", "Con --real i dati vengono da Yahoo Finance senza chiave: prezzi, bilanci "
            "annuali e trimestrali, notizie e cambi. Insider trading e fondamentali di ETF e "
            "obbligazioni richiedono un contratto dati: finché manca, quegli strumenti sono "
            "monitorati ma non proposti."),
    ("3.2", "Dai data provider non arrivano più rating, target price e upgrade/downgrade: solo "
            "fatti (prezzi, bilanci, guidance, insider, news, earnings). Il provider LLM è "
            "Gemini API (chiude OP-07)."),
    ("3.4", "Il modello dati perde rating e target price degli analisti e acquisisce la stima "
            "di valore: valore, metodo, confidenza, revisione a 30 giorni e sorgente "
            "(Gemini o modello quantitativo)."),
    ("BR-01", "Il dominio dei settori guadagna \"Immobiliare\": i sette settori documentati "
              "non lo comprendono, ma le società immobiliari del listino sono mappate sotto "
              "\"Azioni\" con settore \"Immobiliare\", quindi nessun profilo poteva "
              "riceverle. Chiude un pezzo di OP-10."),
    ("OP-10", "Si chiude da sé per la parte di scoring: con la valutazione fatta in casa anche "
              "crypto e commodities hanno tutti e cinque i componenti, mentre col consensus "
              "restavano senza copertura. Resta aperto per il dominio \"Asset preferiti\" "
              "del profilo."),
]

OPEN_POINTS_LEFT = [
    ("OP-01", "Revisori del documento: fuori dal perimetro della demo."),
    ("OP-02", "Significato operativo di \"agente completamente autonomo\": la demo si ferma alla "
              "notifica con piano operativo, non esegue ordini."),
    ("OP-03", "Referenti di progetto: fuori dal perimetro della demo."),
    ("OP-04", "Situazione as-is dei clienti retail: non modellata."),
    ("OP-08", "Licenze d'uso dei dati e ripartizione reale tra provider: la demo usa dati "
              "sintetici, la mappa dei campi per provider è in engine/universe.py."),
    ("OP-09", "Ruoli amministrativi: la demo implementa solo il ruolo Cliente retail."),
    ("OP-13", "Formato, naming e conservazione dei report: la demo li tiene in archivio come "
              "oggetti applicativi, senza PDF né versioning."),
    ("OP-14", "KPI di business e frequenza di refresh: la demo mostra solo KPI operativi di ciclo."),
    ("OP-15", "GDPR: nessun dato personale reale, nessuna base giuridica modellata."),
    ("OP-16", "Sicurezza: nessuna autenticazione, cifratura o gestione segreti nella demo."),
    ("OP-17", "Estremi della valutazione di compliance: non disponibili."),
    ("OP-18", "Misure quantitative di disponibilità e tempi di risposta: non misurate."),
]
