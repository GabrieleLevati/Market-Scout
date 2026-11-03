# Come funziona, e come farlo usare ad altri

Due domande separate: *che cosa succede quando lo uso io* e *che cosa serve perché lo usi
qualcun altro*. La seconda ha tre risposte diverse, con costi e lavoro molto diversi.

---

## Parte 1 — Come funziona oggi

Il sistema è fatto di **due pezzi che non si parlano mai in diretta**.

```
   IL MOTORE (Python, sul tuo computer)                 LA PAGINA (browser)
   ────────────────────────────────────                 ──────────────────────
   1. scarica prezzi, bilanci, notizie  ──┐
      (Yahoo Finance, cache in              │
       .data_cache\: prezzi 60 minuti,      │
       notizie 3 ore, bilanci un giorno)    │
   2. calcola gli indicatori                │
      (RSI, MACD, medie, ADX, rischio)      │
   3. cinque agenti danno un voto           │
      (conti · prezzo · valore · notizie    │
       · rischio) → voto 0-100              │
   4. rileva i trigger e decide             │
      chi avvisare, per ogni profilo        │
   5. scrive TUTTO in un file solo  ────────┴──→  web\data.js  ──→  6. la pagina legge il file
      (48 strumenti analizzati,                    (circa 1 MB)        7. fa il questionario
       spiegazioni in italiano,                                        8. filtra con il TUO profilo
       report, log del ciclo)                                          9. mostra la tua pagina
                                                                      10. risponde alle domande
```

**Il motore fa i conti, la pagina non ne fa nessuno.** Tutta la parte finanziaria — indicatori,
valutazione, voti, trigger — avviene in Python e finisce dentro `web\data.js`. La pagina legge
quel file, ti fa il questionario e **filtra**: dei 48 strumenti già analizzati tiene quelli
che hanno passato gli **85 punti su 100** (la soglia sotto la quale nessuno viene disturbato,
uguale per tutti) e che rientrano nel tuo profilo (mercati, settori, tipo di strumento, tetto
di rischio), ordina per voto e ne mostra al massimo quanti hai chiesto. Nient'altro.

È per questo che la pagina funziona anche aperta da un file, senza internet e senza server: il
lavoro è già stato fatto.

### Dove sta ogni cosa

| Cosa | Dove | Chi lo vede |
|---|---|---|
| Risultato del ciclo (analisi, spiegazioni, report) | `web\data.js` | chiunque apra la pagina |
| Il tuo profilo e il tuo portafoglio, se hai un `profilo.json` | nel file **e** copiati dentro `web\data.js` — **esclusi con `build_web.py --pubblico`** | chiunque apra quel file |
| Il profilo fatto col questionario | `localStorage` del browser (e `profilo.json` se lo scarichi) | solo chi usa quel browser |
| Prezzi, bilanci e notizie scaricati | `.data_cache\` (**tre** file per strumento al giorno: `chart_`, `statements_`, `news_`) | solo il tuo computer |
| Risposte di Gemini | `.llm_cache\` | solo il tuo computer |
| Registro delle esecuzioni automatiche | `giornaliero.log`, in questa cartella: contiene il log del ciclo, quindi anche il nome del profilo | solo il tuo computer |
| La tua chiave Gemini, token Telegram e chat id | variabili d'ambiente; con `setx` restano **permanenti** nel tuo profilo Windows finché non le togli (`setx GEMINI_API_KEY ""`) | solo il tuo computer |

Non c'è un database, non c'è un server, non c'è login. Il prezzo di questa semplicità è che
**oggi è un sistema per una persona**: quella che lancia il ciclo.

### Quando gira

A mano (`python cli.py scan --real --live`) oppure da solo ogni mattina alle 7:30 con
`giornaliero.cmd` registrato in Utilità di pianificazione (passo 6 di [ISTRUZIONI.md](ISTRUZIONI.md)).

Sono due comandi distinti, e `giornaliero.cmd` li esegue entrambi: `cli.py scan` fa le analisi
e, se hai acceso Telegram, manda il messaggio; `build_web.py` riscrive `data.js`, cioè quello
che vedi aprendo la pagina. Se lanci solo il primo, la pagina resta al ciclo precedente.

### Perché è fatto così

Nessuna libreria da installare, nessun servizio da pagare, nessun dato personale in giro:
si apre e funziona. Se fosse nato come applicazione web multiutente non avresti potuto provarlo
senza prima mettere in piedi un server, un database e un'autenticazione.

### Un'analisi sola, decisioni diverse

Il motore analizza gli strumenti **una volta per tutti**: gli stessi 48 voti, gli stessi
trigger, e la stessa soglia comune: sotto 85 punti su 100 non si parla a nessuno. Quello che
cambia da persona a persona è il **filtro** applicato dopo: tetto di rischio (40 su 100 per un
profilo prudente, 60 per uno equilibrato, 85 per uno spavaldo — è un punteggio di rischio, non
ha niente a che vedere con la soglia dei voti), mercati, settori, tipi di strumento e quante
volte a settimana si può essere disturbati.

Si vede eseguendo:

```powershell
python tools\confronto_profili.py --threshold 70
```

Lo stesso ciclo, tre persone che hanno risposto in modo diverso al questionario: il prudente
non riceve niente (tutto quello che è sopra soglia sta su un mercato che ha escluso),
l'equilibrato ne riceve 2 su 7 idonei (limite di due a settimana), lo spavaldo 3 su 10. Nessuno
riceve un'analisi diversa: ricevono una selezione diversa della stessa analisi.

---

## Parte 2 — Farlo usare ad altri: tre livelli

### Livello 1 — Gli mandi la cartella (due minuti, zero infrastruttura)

Prepari la cartella **senza i tuoi dati** e mandi quella:

```powershell
python build_web.py --real --live --llm-limit 2 --llm-pace 5 --pubblico --cartella da-caricare
python tools\selftest_pubblico.py
```

Poi copi `da-caricare\` (circa 1 MB) su Google Drive, WhatsApp o una chiavetta.
L'amico la apre con doppio clic su `index.html`.

**Non mandare `web\`**: quello è il tuo, e se hai un `profilo.json` contiene il tuo profilo,
le tue posizioni e il log del ciclo. La differenza la fa `--pubblico`, e il secondo comando
serve a verificarla: deve dire «Nessuna fuga di dati personali».

**Cosa funziona:** tutto il prodotto. Fa il suo questionario, ottiene il suo profilo, vede la
sua pagina con le sue segnalazioni, può chiedere spiegazioni. Il suo profilo resta nel suo
browser: tu non lo vedi e non lo raccogli.

**Cosa non funziona:** i dati sono la fotografia del giorno in cui hai generato il file. Domani
sono vecchi, e per aggiornarli devi rimandare la cartella. Nessuna notifica: la pagina non sa
scrivere a nessuno.

Da fare: niente. Da sapere: mandagli anche il link `index.html?esempio=1`, che apre un profilo
di esempio senza compilare nulla — utile per fargli capire in dieci secondi di che si tratta.

### Livello 2 — Una pagina online che si aggiorna ogni giorno (gratis, mezza giornata di lavoro)

È il punto di equilibrio migliore, e funziona proprio per com'è fatto il sistema.

1. Scegli un hosting di file statici gratuito: **Cloudflare Pages** (consigliato, e c'è la
   guida passo a passo in [ISTRUZIONI.md](ISTRUZIONI.md)), GitHub Pages o Netlify. Ottieni un
   indirizzo in HTTPS tipo `https://market-scout.pages.dev` — l'HTTPS serve, perché senza di
   esso il telefono non propone l'installazione come app.
2. Il tuo computer continua a fare il lavoro e prepara una **cartella da pubblicare**, separata
   da quella privata:

   ```powershell
   python build_web.py --real --live                                    # la tua dashboard, privata
   python build_web.py --real --live --pubblico --cartella da-caricare  # quella da mettere online
   ```

   > **Perché `da-caricare` e non `sito`.** `sito\` esiste nel repository ed è la cartella che
   > il ciclo nel cloud rigenera e pubblica da sé (livello 3). Un file generato con due autori
   > finisce con i marcatori di conflitto di git scritti dentro i dati: è successo, e la pagina
   > è diventata bianca. Quando generi dal PC, scrivi altrove.

   La seconda riga crea `da-caricare\` con i file della pagina e un `data.js` da cui sono
   **esclusi il tuo profilo, le tue posizioni, i prezzi di carico, i report che hai chiesto tu e
   le righe del log che ti nominano**: restano solo le analisi, che sono uguali per tutti. La
   cartella `web\` resta quella privata, così pubblicare non ti cancella il profilo dalla
   dashboard di casa.

   Prima di pubblicare, una verifica che dura dieci secondi:

   ```powershell
   python tools\selftest_pubblico.py
   ```

   Costruisce un profilo con dati riconoscibili, genera il file pubblico e li cerca dentro:
   deve rispondere «Nessuna fuga di dati personali». Il controllo esiste perché la prima
   versione di `--pubblico` toglieva il profilo dall'elenco degli utenti ma lo lasciava nel log
   del ciclo, dove nome, capitale e valore del portafoglio restavano in chiaro.
3. Pubblichi la cartella: `git add sito && git commit -m "ciclo" && git push`, oppure il
   comando di deploy del servizio che hai scelto (su Netlify basta trascinarla).
4. Mandi **un solo link** agli amici. Ognuno fa il suo questionario sul suo telefono, e vede la
   propria pagina sulle analisi di stamattina.

**Cosa funziona:** pagina personalizzata per ciascuno, dati freschi ogni giorno, nessun costo,
nessun server da gestire. Funziona perché le analisi di tutti i 48 strumenti sono già nel file e
il filtro per profilo gira nel browser di chi guarda.

**Cosa non funziona:** nessuno riceve messaggi (né Telegram né email): per sapere *a chi*
scrivere servirebbe un server che conosca gli utenti. E se il tuo computer è spento, il file
resta quello del giorno prima — la pagina mostra la data del ciclo, quindi si vede.

**Da sapere:** il link è pubblico, e chi ce l'ha vede le analisi. Generato con `--pubblico` il
file non contiene dati di nessuno — solo strumenti, numeri e spiegazioni — e i profili dei tuoi
amici restano nei loro browser. Resta però il problema della natura dell'attività: vedi la
Parte 3.

### Livello 3 — Prodotto multiutente vero (è l'architettura dell'FDD)

Serve quando vuoi che **ognuno riceva le proprie notifiche** senza che tu faccia niente.

Cosa va aggiunto, in ordine di necessità:

1. **Un backend** (FastAPI, come prevede il documento) che esegue il ciclo sul server e serve le
   pagine. Qui vive la chiave Gemini: oggi non può stare nel browser, ed è anche il motivo per
   cui la chat della vista cliente non chiama il modello.
2. **Un database** (PostgreSQL) per profili, storico delle segnalazioni, limite settimanale per
   utente, preferenze apprese.
3. **Autenticazione**: ognuno entra e vede solo la sua pagina (oggi non esiste: è OP-16).
4. **Canali per utente**: il chat id di Telegram di ciascuno, o un server di posta per le email,
   o un'app installata per le notifiche push.
5. **Uno scheduler sul server** (Celery + cron, come da FDD) invece dell'Utilità di
   pianificazione del tuo PC.
6. **Informativa privacy, consenso per canale, conservazione dei dati** (OP-15).

Costo indicativo: un server piccolo basta (5-10 euro al mese) più il consumo di Gemini, che
cresce col numero di strumenti analizzati, non col numero di utenti — l'analisi è una sola per
tutti, è la decisione che è personale. Il lavoro è la parte seria: è circa l'80% di quello che
resta da fare del progetto, ed è esattamente il perimetro dell'FDD.

---

## Parte 3 — Tre cose da sapere prima di darlo ad amici

**1. Darlo ad altri cambia la natura della cosa.** Guardare analisi che un programma produce
per te è una cosa; mandare a persone che si fidano di te dei segnali su cosa comprare è un'altra.
In Italia la consulenza in materia di investimenti è un'attività riservata a soggetti
autorizzati, e la diffusione di raccomandazioni di investimento ha obblighi suoi di trasparenza.
Una pagina che ciascuno consulta con i propri criteri, e che dichiara in ogni schermata di non
essere un consiglio personalizzato, sta nell'informazione; tu che giri una segnalazione dicendo
"guarda qui" no. **Non è un parere legale:** prima di distribuirlo oltre la cerchia personale
fallo valutare da chi di dovere — è letteralmente il punto aperto OP-17 e il requisito NFR-05
del documento.

**2. Finché non raccogli nulla, non hai obblighi sui dati degli altri.** Ai livelli 1 e 2 il
profilo dei tuoi amici resta nel loro browser: tu non lo vedi, non lo salvi, non lo trasmetti.
Appena introduci login e notifiche (livello 3) tratti dati personali di terzi e servono
informativa, base giuridica e tempi di conservazione: è OP-15, e va scritto prima, non dopo.

**3. Di' a voce quello che la pagina scrive già.** I dati sono gratuiti e non garantiti; Gemini
può sbagliare e la pagina dichiara quando una stima è poco affidabile; il sistema non compra e
non vende niente. Un amico che riceve un messaggio da te non legge le note in piccolo: gliela
dici tu, questa frase, la prima volta.
