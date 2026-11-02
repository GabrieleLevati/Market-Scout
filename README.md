# AI Market Scout & Investment Copilot — demo eseguibile

Demo funzionante dell'FDD **AI-MARKET-SCOUT v1.0 (30/10/2026)**: un ciclo completo di
scansione del mercato, scoring multi-agente, notifiche selettive, monitoraggio di
portafoglio e report on demand, con due interfacce sugli stessi dati.

Serve a **far vedere e discutere il comportamento del sistema descritto nell'FDD** prima di
costruirlo: ogni regola del documento è implementata e ispezionabile, e ogni punto lasciato
aperto dall'FDD è stato risolto con una scelta dichiarata, isolata e modificabile da un
singolo punto del codice.

**Le analisi le fa l'intelligenza artificiale, non il consensus degli analisti.** Nel sistema
non entrano rating né target price di analisti umani: il valore di ogni investimento lo stima
il motore dai fatti pubblicati (bilanci, guidance, dati di rete, scorte) e il giudizio lo dà
**Gemini** via API. È uno scostamento dall'FDD, tracciato nella tabella *Scostamenti
dall'FDD* qui sotto.

**Due viste, un solo motore.**

- **Vista cliente** (quella che si apre): l'agente parla in italiano corrente a un cliente
  retail che non ha mai letto un bilancio. Niente punteggi, niente gergo: che cos'è quella
  società, perché proprio adesso, quanti euro può guadagnare o perdere, che cosa fare, di
  che cosa si occupa l'agente da qui in avanti. In fondo una casella per chiedergli
  qualunque cosa.
- **Vista analista** (pulsante in alto a destra): la dashboard tecnica con tutti i
  punteggi, i driver di ogni agente, i trigger, il log del ciclo e le scelte di demo.
  È quella che serve in review per far vedere *come* il motore è arrivato lì.

```
ai-market-scout-demo/
├─ engine/          motore Python (sola libreria standard)
├─ web/             dashboard statica (nessuna libreria, nessun bundler)
├─ cli.py           interfaccia a riga di comando
└─ build_web.py     genera web/data.js dal risultato del ciclo
```

> **Istruzioni passo a passo per avere il prodotto funzionante: [ISTRUZIONI.md](ISTRUZIONI.md)** —
> sei passi con un controllo per ognuno, dal primo avvio al ciclo giornaliero che scrive su
> Telegram.
>
> **Come funziona e come farlo usare ad altri: [COME-FUNZIONA.md](COME-FUNZIONA.md)** — che cosa
> fa il motore e che cosa fa la pagina, dove sta ogni dato, e i tre livelli per passarlo a
> qualcun altro (cartella copiata · pagina online aggiornata ogni giorno · prodotto multiutente),
> con quello che va saputo prima di distribuirlo.

## Avvio rapido

Servono solo Python 3.11+ e un browser. **Nessun `pip install`, nessun `npm install`.**
Il ciclo di default lavora sui dati sintetici e non esce in rete: la rete serve solo con
`--real` (prezzi veri) o `--live` (Gemini).

```bash
# 1. ciclo completo: i 10 step del workflow FDD 3.1, con tempi reali
python cli.py scan

# 2. rigenera i dati della dashboard e aprila
python build_web.py
start web/index.html        # Windows (oppure apri il file col browser)
```

Si apre la **vista cliente**; il pulsante *Vista analista* in alto a destra porta alla
dashboard tecnica (la scelta resta memorizzata nel browser). Tutto gira da `file://`: non
serve un web server.

### Il questionario iniziale

Alla prima apertura la vista cliente non chiede dati patrimoniali: fa **otto domande a
risposta chiusa** (orizzonte, reazione a una perdita del 20%, esperienza, tipi di strumento,
mercati, settori, con che frequenza e su quale canale) e da quelle ricava il profilo —
rischio, mercati, settori, tipi di strumento, limite settimanale. Nessun importo da digitare,
nessuna posizione da elencare: dove servono gli euro, le percentuali vengono tradotte su una
base neutra di 1.000 euro ("ogni 1.000 euro investiti…").

Il profilo resta nel browser (`localStorage`); il pulsante *Scarico il profilo per il computer*
produce il `profilo.json` che serve alla riga di comando e alle notifiche su Telegram. Le
domande e le regole di calcolo vivono in un posto solo, `engine/onboarding.py`, e vengono
interpretate sia dal motore sia dalla pagina.

Tre regole che valgono la pena di essere citate, perché sono il risultato di un confronto tra
quattro impostazioni diverse del questionario (conformità, comprensibilità, utilità per il
motore, prodotto):

- **un tetto non si compensa**: chi risponde "vendo tutto" a una perdita del 20%, o dichiara di
  cominciare adesso, resta nel profilo prudente qualunque cosa risponda altrove;
- **l'esperienza può solo ridurre il rischio**, mai ampliarlo: senza esperienza dichiarata non
  si arriva al profilo aggressivo;
- **scegliere un mestiere è scegliere le aziende singole**: le opzioni dei settori aggiungono da
  sé le azioni, così non serve una domanda in più e non si ottengono filtri inerti.

Lo stesso questionario in terminale: `python cli.py onboarding`. Verifica automatica delle
regole e della parità tra motore e pagina: `python tools/selftest_onboarding.py`.

### Provarla dal telefono

La vista cliente è pensata per uno schermo di telefono e la pagina è statica, quindi basta
raggiungerla. Senza installare niente, dal PC:

```powershell
python -m http.server 8000 --directory web
```

Poi dal telefono, sulla stessa rete Wi-Fi, apri `http://INDIRIZZO-DEL-PC:8000` (lo trovi con
`ipconfig`, voce *Indirizzo IPv4*). In alternativa copia la cartella `web\` sul telefono
(OneDrive, cavo) e apri `index.html`: funziona anche senza rete, perché i dati sono dentro
`data.js`. Sono circa 1 MB, quindi in locale si carica subito.

### Altri comandi

```bash
python cli.py llm-check                  # prova la connessione a Gemini
python cli.py scan --live                # ciclo con le analisi fatte da Gemini
python cli.py agent u1                   # la vista cliente in terminale: cosa dice l'agente oggi
python cli.py explain AMD --user u1      # un investimento spiegato in parole semplici
python cli.py opportunities --limit 20   # classifica Opportunity Score (BR-04)
python cli.py analyze AMD                # analisi on demand di un asset (BR-09)
python cli.py notify                     # decisioni di notifica per utente (BR-06/BR-07)
python cli.py portfolio u1               # monitoraggio portafoglio e alert (BR-08)
python cli.py triggers                   # trigger rilevati (BR-05)
python cli.py decisions                  # scelte di demo vs punti aperti dell'FDD
```

## Dati veri o dati sintetici

Il motore gira su due sorgenti, con la stessa forma di dati e lo stesso codice a valle:

| | `--real` (dati veri) | default (sintetico) |
|---|---|---|
| prezzi, volumi, storico | **Yahoo Finance**, 2 anni di sedute | generati con seme per ticker |
| bilanci | **Yahoo Finance**, annuali e trimestrali (ricavi, utile, EPS diluito, debito, patrimonio, free cash flow) | generati |
| notizie | **Yahoo Finance**, titolo, editore, data | titoli generati con polarità |
| cambi | **Yahoo Finance**, cambio del giorno | tabella fissa |
| operazioni degli insider | **non disponibili** senza contratto dati: trigger disattivato | generate |
| bilanci di ETF, obbligazioni, crypto, materie prime | **non disponibili**: nessuna stima di valore, strumento monitorato ma non proposto | generati |

Serve solo rete in uscita: niente chiavi, niente abbonamenti. Tutto passa da una cache
giornaliera in `.data_cache/`, quindi il secondo ciclo dello stesso giorno non tocca la rete.

```powershell
python cli.py data-check          # cosa è disponibile, strumento per strumento
python cli.py scan --real         # il ciclo sui dati veri
python build_web.py --real        # porta i dati veri nella dashboard
```

**Due cose che i dati veri cambiano nel motore.**

1. **Il multiplo giusto diventa relativo.** Con i numeri del 2026 — metà del listino
   tecnologico cresce oltre il 40% — una formula a premi assoluti direbbe "sottovalutato"
   per tutti. Sui dati veri il riferimento è il settore stesso: mediana dei multipli dei
   simili, corretta per crescita, redditività e debito (DEMO-26). La stima è limitata a
   −50%/+60% dal prezzo: oltre, il confronto con i simili non basta e la confidenza scende.
2. **La polarità delle notizie non è un dato, è un giudizio.** Dai provider arrivano i
   titoli, non il loro segno. Senza Gemini il componente "notizie" resta vuoto e il suo
   15% si ridistribuisce, dichiarandolo; con `--live` lo riempie il modello. È la
   differenza più visibile tra i due modi.

Controlli di sanità attivi sui dati veri: utile per azione convertito nella valuta del
prezzo quando l'emittente pubblica in un'altra valuta (TSMC pubblica in dollari di Taiwan
e quota a New York), scarto della stima se l'utile è negativo o il multiplo è fuori scala,
esclusione degli strumenti con meno di 260 sedute di storico.

## Usare l'agente sul proprio portafoglio

I tre clienti della demo servono a far vedere che la stessa analisi produce esiti diversi.
Per usarlo davvero serve il proprio profilo:

```powershell
python cli.py profilo-nuovo        # crea profilo.json
notepad profilo.json               # capitale, profilo di rischio, mercati, settori, posizioni
python cli.py agent me --real      # il ciclo sul proprio profilo, dati veri
```

Il file resta sul disco e non viene spedito da nessuna parte; a Gemini arrivano i dati
dello strumento da analizzare, non il portafoglio.

**Ricevere le segnalazioni su Telegram** (BR-07; Email, WhatsApp e push richiedono SMTP,
approvazione Meta e un'app, quindi restano da fare):

```powershell
# 1. su Telegram scrivi a @BotFather -> /newbot -> copia il token
$env:TELEGRAM_TOKEN = "il-token"
# 2. scrivi un messaggio qualsiasi al tuo bot, poi:
python cli.py telegram-id          # stampa il tuo chat id
$env:TELEGRAM_CHAT_ID = "il-numero"
# 3. il ciclo che scrive davvero:
python cli.py scan --real --live --telegram
```

Arriva la segnalazione in italiano semplice — la stessa che vede la vista cliente — oppure
un riepilogo del portafoglio quando non c'è niente sopra soglia. I messaggi partono solo per
il profilo di `profilo.json`, non per i clienti demo.

La soglia di notifica è un parametro: `--threshold 75` abbassa l'asticella di BR-06 per
vedere che cosa l'agente considera interessante nei giorni in cui niente supera 85.

## Le analisi le fa Gemini

OP-07 è chiuso: il provider LLM è **Gemini API**. Il modello non è una decorazione sui testi,
fa il lavoro di giudizio.

| Agente | Che cosa resta calcolato | Che cosa fa Gemini |
|---|---|---|
| Fundamental | indici di bilancio normalizzati | rivede il punteggio, ±10 punti motivati |
| Technical | RSI, MACD, EMA, Bollinger, ADX, volumi | rivede il punteggio, ±10 punti motivati |
| **AI Valuation** | valore da utili × multiplo giusto | **giudica la stima e dà il punteggio** |
| News & Sentiment | polarità grezza delle notizie | **legge le notizie e dà il punteggio** |
| Risk | volatilità, drawdown, leva, liquidità | rivede il punteggio, ±10 punti motivati |
| CIO (report) | numeri e scenari | **scrive l'Executive Summary e il rischio chiave** |

**Perché gli indicatori restano calcolati.** Un RSI o un ROIC devono dare lo stesso numero
ogni volta e devono poter essere verificati a mano: farli produrre da un modello linguistico
li renderebbe irriproducibili. Il modello fa quello che un calcolo non sa fare — leggere le
notizie, pesare una stima, scrivere il perché — e ogni sua uscita passa da una validazione
(campi presenti, numeri nel dominio atteso, valore entro il 25% dalla stima del motore, correzioni
entro ±10 punti). Quello che non passa viene scartato e si usa il nucleo deterministico, dichiarato
a schermo.

**Come si accende.**

```powershell
$env:GEMINI_API_KEY = "la-tua-chiave"     # da Google AI Studio
$env:GEMINI_MODEL   = "gemini-3.8-flash"  # opzionale, è il default
$env:GEMINI_THINKING = "1"                # opzionale: riaccende il ragionamento (DEMO-33)
python cli.py llm-check                   # verifica chiave, rete e modello
python cli.py scan --live                 # ciclo con le analisi del modello
python build_web.py                       # porta il risultato nella dashboard
```

I nomi dei modelli invecchiano in fretta: `gemini-2.5-flash` e `gemini-2.5-pro` rispondono già
`404 — no longer available to new users`. Quando capita, `llm-check` legge dal messaggio
dell'API il modello suggerito e stampa il comando `setx` da eseguire.

Senza chiave tutto gira identico sul nucleo deterministico: la dashboard lo scrive in chiaro
(*Scelte di demo → Chi fa le analisi*) e ogni analisi porta la sua provenienza.

**Quanto consuma.** Un ciclo live completo fa circa **140 chiamate** (34 asset in analisi
profonda × valutazione, notizie e revisione, più i report), nell'ordine di 70.000 token in
ingresso e 20.000 in uscita. Le risposte finiscono in `.llm_cache/`, quindi ripetere lo stesso
ciclo non costa niente (`--no-cache` per forzare chiamate nuove).

**Sul piano gratuito la quota è il vincolo, non il prezzo.** Misurato su una chiave nuova
(ottobre 2026): **una ventina di chiamate al giorno**, limite che l'API dichiara da sé nel
messaggio del 429 e che il client riporta a schermo. Il costo del ciclo è
**7 chiamate fisse + 4 per asset analizzato dal modello**:

| perimetro | chiamate | piano gratuito |
|---|---|---|
| `--llm-limit 2` | 15 | ci sta |
| `--llm-limit 3` | 19 | al limite |
| `--llm-limit 7` | 35 | quota esaurita a metà ciclo |
| nessun limite (34 asset) | 143 | serve la fatturazione |

```powershell
python cli.py scan --live --llm-limit 2 --llm-pace 5 --llm-budget 8
```

`--llm-budget 8` è un **tetto di chiamate per ciclo**: serve a dividere la quota giornaliera
tra più cicli (due cicli da 8 = 16, dentro la quota). Esaurito il tetto le analisi restanti
passano al calcolo e il ciclo lo dichiara nel log (DEMO-34).

Il modello lavora sui primi asset del prescreening — quelli che poi vengono notificati — e il
resto resta sul nucleo deterministico, **dichiarato asset per asset** nella pagina. `--llm-pace 5`
mette cinque secondi tra due chiamate. Esaurita la quota il ciclo non si ferma: dopo tre errori
di fila il client sospende per due minuti, poi riprova una volta (tre rifiuti di fila sono di
solito il limite di frequenza, non un guasto). Per l'analisi AI su tutto l'universo serve
attivare la fatturazione su Google AI Studio: a questi volumi sono centesimi.

**Quanto aspetti.** La latenza è alta e molto variabile: misurati 161 s sulla prima risposta e
33 s sulle successive, con `503 — high demand` quando il modello è carico (un nuovo tentativo è
automatico). Il timeout per singola chiamata è 240 s (`TIMEOUT_S` in `engine/llm.py`). Con
`--llm-limit 2` il ciclo dura qualche minuto; è comunque pensato per girare di notte con
`giornaliero.cmd` invece di essere aspettato davanti al terminale.

**Verifica senza chiave.** `python tools/selftest_llm.py` prova l'integrazione simulando le
risposte dell'API: controlla che la richiesta sia ben formata, che i numeri del modello
finiscano nei conti, che un valore fuori banda venga scartato e che un errore HTTP non fermi
la scansione.

**Limite noto.** La chat della vista cliente non chiama Gemini: una pagina statica aperta da
`file://` non può custodire una chiave API. Le risposte della chat sono generate dal motore
durante il ciclo (DEMO-21); con il backend FastAPI dell'FDD la domanda andrebbe a Gemini con
gli stessi dati in contesto. Il percorso live si prova da terminale con `--live`.

## Cosa fa la demo

Un ciclo (`python cli.py scan`, ~0,2 s) esegue in sequenza gli step del workflow 3.1:

| Step | Attore | Cosa fa nella demo |
|---|---|---|
| 2 | Scheduler | avvia il ciclo giornaliero (in produzione Celery + Cron) |
| 3 | Market Scanner Agent | acquisisce 48 asset, rileva i trigger, produce il ranking preliminare |
| 4 | 5 agenti specialistici | Fundamental, Technical, Analyst, Sentiment e Risk Score per ogni asset |
| 5 | Motore di scoring | Opportunity Score 0-100 e classificazione nelle 4 fasce di BR-04 |
| 6 | Chief Investment Officer Agent | filtra per profilo e preferenze apprese, applica soglia e limite settimanale |
| 7 | Sistema di notifica | compone e "invia" le notifiche sui canali dell'utente |
| 8 | Portfolio Agent | valuta le posizioni e genera gli alert |
| 9 | CIO Agent | genera i report on demand e li archivia |
| 10 | Sistema | aggiorna le preferenze apprese dalle interazioni |

**Universo:** 48 asset su 6 asset class (azioni, ETF, obbligazioni, crypto, commodities,
REIT) e 4 mercati (USA, Europa, Asia, Global) — BR-13, BR-14.
**Utenti:** 3 clienti retail con profili diversi (Bilanciato, Aggressivo, Conservativo),
portafogli, watchlist e storico di interazioni.

### Le tre regole che vale la pena guardare in azione

1. **Opportunity Score (BR-04).** Media pesata F30/T20/A25/S15/R10 con il rischio invertito
   come `100 − Risk` (A-05). Nel dettaglio di ogni asset la dashboard mostra i punti
   effettivi portati da ciascun agente e, sotto, le metriche che hanno generato ogni score:
   nessun numero è un valore magico.
2. **Notifiche selettive (BR-06).** Nel ciclo di esempio solo 2 asset su 48 superano 85.
   *Marco* ha già 2 notifiche nella settimana: ne riceve una e la seconda resta "idonea ma
   rinviata". *Giulia* ne riceve 2. *Alberto* nessuna: le due opportunità sono su un mercato
   fuori dal suo profilo. Ogni scarto è tracciato con il motivo — è la risposta alla domanda
   "perché non mi ha avvisato".
3. **Ogni asset class ha tutti e cinque i componenti.** È il guadagno collaterale di aver
   tolto gli analisti: crypto e commodities, che nessun analista copre, ora hanno una stima di
   valore come le azioni — rendimento atteso dai dati di rete o dal rapporto tra scorte e
   domanda invece di utili e multipli. Il Fundamental Agent usa set di metriche proxy per
   asset class (TER e crescita utili dell'indice, YTM e duration, attività on-chain, scorte e
   domanda) e lo dichiara.

## La vista cliente

È il prodotto: la vista che si apre e quella che un cliente userebbe. Tutto quello che
compare qui esce dai numeri del motore, tradotto da `engine/plain.py`.

**Le regole di scrittura**, che sono la parte che vale:

- **Niente punteggi in faccia.** "Technical Score 90, ADX 32" diventa "il prezzo ha
  superato il massimo degli ultimi tre mesi e lo ha fatto con 1,7 volte gli scambi
  abituali: vuol dire che in molti stanno comprando". Il voto da 0 a 100 resta disponibile,
  ma non è il messaggio.
- **Le percentuali diventano euro.** "upside +16,7%" non dice niente; "su 4.000 euro:
  circa 668 euro di guadagno se arriva all'obiettivo, circa 196 euro di perdita se scatta
  la protezione" dice tutto. L'importo di esempio è il 5% del capitale del profilo
  (DEMO-19) — è un esempio per far capire la posta in gioco, non un consiglio di quanto
  investire.
- **Un semaforo con la parola scritta accanto**, mai il colore da solo: "Da guardare
  adesso", "Interessante, ma non ancora", "Niente da fare oggi".
- **Nomi, non ticker.** "Advanced Micro Devices, produce i microchip usati nei computer e
  nei centri dati per l'intelligenza artificiale" invece di "AMD".
- **Il "lei", formale ma caldo**, e frasi corte. Nessun inglese dove esiste l'italiano:
  *vendita automatica di protezione* prima di *stop loss*, e lo stop loss spiegato nel
  glossario in fondo.
- **Quando non c'è niente da dire, lo dico.** Per il cliente conservativo la pagina si apre
  con "Oggi non ho niente per lei, e va bene così", seguita dai casi più vicini e dal
  motivo per cui li ho scartati.

**La parte agentica.** L'agente racconta che cosa ha fatto stanotte (48 investimenti, cinque
controlli per ognuno, 81 segnali, 2 sopra soglia, 1 dentro il profilo), dichiara **di che
cosa si occupa da qui in avanti** — segue i livelli di stop e target, ricorda una volta dopo
sette giorni, non compra e non vende niente al posto del cliente (DEMO-20, il perimetro
dell'autonomia che l'FDD lascia aperto in OP-02) — e accetta domande in italiano:
*"come vanno i miei investimenti?"*, *"conviene comprare Microsoft?"*, *"che cos'è un ETF?"*,
*"perché oggi non mi ha segnalato niente?"*. I bottoni **Mi interessa / Non mi interessa**
sono il canale di ritorno che alimenta le preferenze apprese (BR-12).

Le risposte sono generate dal motore (`engine/assistant.py`) e il browser riconosce la
domanda per parole chiave e nomi di asset (DEMO-21). In produzione la stessa domanda va
all'LLM con questi stessi dati in contesto: cambia chi scrive la risposta, non la vista.

## Vista analista (BR-10)

Cinque aree previste dall'FDD più due di servizio:

- **Home** — opportunità del ciclo, notifiche dell'utente, alert di portafoglio,
  distribuzione dell'Opportunity Score, watchlist.
- **Opportunity Center** — classifica filtrabile; una riga apre il dettaglio con grafico
  prezzo/EMA50/EMA200, piano operativo, trigger attivi, tabelle dei 5 agenti e news.
- **Portfolio** — posizioni convertite nella valuta del profilo, P/L, drawdown, rischio
  rispetto al tetto del profilo, asset allocation, alert.
- **Research** — analisi on demand su qualsiasi asset ("Analizza Microsoft", "Conviene
  comprare ASML oggi?") con Executive Summary, sezioni, rischi, scenari Bull/Base/Bear e
  valutazione finale.
- **Reports** — archivio dei report generati nel ciclo (BR-11).
- **Pipeline del ciclo** — il log dei 10 step con i tempi reali, il prescreening dello
  scanner, i trigger per tipo e la mappa dei provider. Il pulsante *Riesegui la scansione*
  rigioca il tracciato.
- **Scelte di demo** — le 35 decisioni prese sui punti aperti e la tracciabilità BR → modulo.

Deep link utili: `web/index.html?user=u3` (cliente conservativo, giornata senza
segnalazioni), `web/index.html?mode=expert#pipeline`, `web/index.html?asset=AMD&mode=expert`,
`web/index.html?ask=Conviene comprare Microsoft?`.

## Come è fatto

**Motore (Python, sola stdlib).**

| Modulo | Contenuto | FDD |
|---|---|---|
| `engine/providers.py` | adapter sui dati reali: Yahoo Finance, cache a scadenza per tipo (prezzi 90 min), campi mancanti dichiarati | 3.2 |
| `engine/real_universe.py` | universo investibile dai dati veri, con qualità del dato per strumento | 3.2 |
| `engine/universe.py` | generatore sintetico: 48 asset, OHLCV, bilanci, news, insider, earnings | 3.2 |
| `engine/profile_file.py` | il profilo dell'utente da `profilo.json` | BR-01 |
| `engine/channels.py` | invio reale delle notifiche su Telegram | BR-07 |
| `engine/indicators.py` | RSI, MACD, EMA50/200, Bollinger, ADX, ATR, volatilità, drawdown | 3.4 |
| `engine/agents.py` | i 5 agenti specialistici, ognuno con i propri driver pesati | BR-03 |
| `engine/valuation.py` | modello di valutazione: valore stimato, metodo, confidenza | BR-03, BR-04 |
| `engine/llm.py` | client Gemini: cache, validazione, fallback, misura dei token | OP-07 |
| `engine/scoring.py` | Opportunity Score, classificazione, valutazione finale, piano operativo | BR-04 |
| `engine/triggers.py` | i 6 trigger con le soglie in un unico dizionario | BR-05 |
| `engine/users.py` | profili, portafogli, interazioni, preferenze apprese | BR-01, BR-12 |
| `engine/portfolio.py` | Portfolio Agent e regole di alert | BR-08 |
| `engine/notifications.py` | decisione di notifica del CIO Agent, con motivi di scarto | BR-06, BR-07 |
| `engine/reports.py` | report on demand, scenari, narrativa | BR-09, BR-11 |
| `engine/plain.py` | traduttore in italiano semplice: spiegazioni, euro, rischio, impegni | BR-09, vista cliente |
| `engine/assistant.py` | risposte dell'assistente e riconoscimento delle domande | BR-09, OP-07 |
| `engine/pipeline.py` | orchestrazione dei 10 step e log di esecuzione | 3.1 |
| `engine/decisions.py` | registro delle scelte di demo sui punti aperti | — |

**Dashboard.** HTML + CSS + due script classici (`charts.js`, `app.js`). I grafici sono SVG
scritti a mano: l'FDD prevede Plotly, ma la demo deve restare apribile da disco senza
dipendenze. La palette è quella validata per la leggibilità in modalità chiara e scura e per
i deficit di visione dei colori (tema commutabile dal pulsante *Tema*).

### I dati sono sintetici e deterministici

Non ci sono chiamate ai data provider: `engine/universe.py` genera prezzi e fondamentali con
generatori seminati per ticker, quindi **lo stesso ciclo produce sempre gli stessi numeri** e
la demo si può raccontare due volte allo stesso modo. La ripartizione dei campi per provider
(Yahoo Finance, Polygon, FMP, Finnhub, Alpha Vantage) resta dichiarata in `PROVIDER_MAP` e
visibile nella dashboard: sostituirla con le API reali è un lavoro di adapter su un solo
modulo.

Le "forme" dei prezzi sono costruite per far scattare i casi d'uso dell'FDD: alcuni asset
sono in compressione e rottura (breakout con volumi), altri in correzione con fondamentali
intatti, gli altri in trend regolare.

### L'esempio AMD dell'FDD

L'FDD porta come esempio una notifica su AMD. La demo riproduce **lo stesso scenario**
(breakout con volumi, stima di valore rialzata, insider buying, rischio Moderato, notifica
con score sopra soglia e piano operativo completo) ma con i numeri che escono dai suoi dati:
score 87 anziché 91, target 201,71 anziché 205. Non è un valore ricopiato dal documento: è il
risultato della catena di calcolo, verificabile aprendo il dettaglio dell'asset.

## Scostamenti dall'FDD

Il passaggio all'analisi fatta dall'AI cambia alcuni paragrafi del documento. Sono questi,
e li trovi anche nella dashboard (*Scelte di demo → Scostamenti dall'FDD da recepire*):

| Riferimento | Che cosa cambia |
|---|---|
| BR-03 | l'Analyst Consensus Agent diventa **AI Valuation Agent**: nessun rating e nessun target price di analisti; il valore lo stima `engine/valuation.py` e lo giudica Gemini |
| BR-04 | il peso del 25% resta, cambia titolare: "Analyst 25%" → "Valutazione AI 25%" |
| BR-05 | il trigger "upgrade degli analisti" diventa "**stima di valore rialzata**": la guidance dell'emittente alza la stima del sistema di almeno il 3% in 30 giorni |
| 3.2 | dai provider arrivano solo fatti (prezzi, bilanci, guidance, insider, news, earnings); il provider LLM è Gemini API, che **chiude OP-07** |
| 3.4 | il modello dati perde rating e target price e acquisisce valore stimato, metodo, confidenza, revisione a 30 giorni e sorgente dell'analisi |
| OP-10 | si chiude per la parte di scoring: tutte le asset class hanno i cinque componenti. Resta aperto per il dominio "Asset preferiti" del profilo |

## Scelte di demo sui punti aperti dell'FDD

L'FDD lascia 18 punti aperti. Per avere un sistema eseguibile 18 scelte sono state prese e
dichiarate (`python cli.py decisions`, oppure l'area *Scelte di demo*). Le più rilevanti:

| Codice | Punto | Scelta |
|---|---|---|
| DEMO-01 | OP-12 | Risk Score → etichetta: ≤20 Basso, ≤45 Moderato, ≤70 Alto, >70 Molto alto |
| DEMO-02 | OP-10 | peso di un agente non applicabile ridistribuito, non contato come 0 |
| DEMO-04 | OP-12 | valutazione finale: ≥85 Strong Buy, ≥75 Buy, ≥55 Hold, ≥40 Sell, altrimenti Strong Sell |
| DEMO-05 | OP-12 | ingresso [prezzo−0,6 ATR; prezzo+0,2 ATR], stop a prezzo − k×ATR (k per livello di rischio, massimo −20%), target = il valore stimato dall'AI Valuation Agent |
| DEMO-07/08/09 | OP-11 | fondamentali invariati = Fundamental Score ≥ 70; insider significativo ≥ 1 M$ in 90 giorni da C-level; volumi elevati ≥ 1,5× la media a 20 giorni |
| DEMO-10 | BR-12 | le preferenze apprese agiscono sulla **priorità di presentazione** (0,85-1,15×), non sull'Opportunity Score, così il punteggio resta confrontabile tra utenti |
| DEMO-13/14 | OP-05 | soglie degli alert di portafoglio; gli alert **non** consumano il limite di 3 notifiche settimanali |
| DEMO-15 | BR-09 | scenari a 12 mesi dalla stima di valore e dalla volatilità, probabilità funzione dello score |
| DEMO-19 | OP-12 | importo di esempio per tradurre le percentuali in euro: 5% del capitale del profilo |
| DEMO-20 | OP-02 | perimetro dell'autonomia: osserva, avvisa sui livelli, ricorda una volta; non invia ordini |
| DEMO-21 | OP-07 | l'assistente risponde da risposte generate dal motore, con riconoscimento della domanda nel browser |
| DEMO-22 | BR-05 | trigger "stima di valore rialzata": revisione di almeno il 3% in 30 giorni |
| DEMO-23 | BR-03 | modello di valutazione: utile per azione × multiplo giusto (crescita, ROIC, margini, debito) |
| DEMO-24 | OP-07 | divisione del lavoro con Gemini e limiti di validazione delle sue uscite |
| DEMO-25 | OP-07 | modello di default `gemini-3.8-flash`, risposte in cache su disco |
| DEMO-26 | BR-03 | sui dati veri il multiplo giusto è relativo alla mediana di settore, con stima limitata a −50%/+60% dal prezzo |
| DEMO-33 | OP-07 | ragionamento interno del modello spento: i suoi token escono dal tetto della risposta, che altrimenti torna vuota |

Ognuna vive in un unico punto del codice (colonna *Dove* nella tabella) ed è pensata per
essere cambiata in review senza toccare il resto.

## Cosa la demo non fa

- **BR-15 portfolio optimization, BR-16 backtesting, BR-17 simulazioni Monte Carlo**: non
  implementati. Sono nel perimetro dell'FDD ma non servono a mostrare il comportamento del
  copilota, e ognuno è un progetto a sé.
- **BR-18 agente completamente autonomo (OP-02)**: la demo si ferma alla notifica con piano
  operativo. Non invia ordini a un broker, perché il perimetro dell'autonomia non è definito.
- **Sicurezza e GDPR (OP-15, OP-16)**: nessuna autenticazione, nessuna cifratura. I tre clienti
  della demo sono inventati; il profilo del questionario resta nel browser di chi lo compila.
- **Persistenza**: nessun database. Lo stato vive in memoria per la durata del ciclo e viene
  serializzato in `web/data.js`; in produzione l'FDD prevede PostgreSQL e Redis.
- **Report come documenti (OP-13)**: i report sono oggetti applicativi, senza PDF, naming né
  versioning.

## Dalla demo al sistema dell'FDD

L'architettura è già divisa secondo i confini del documento, quindi i passi sono circoscritti:

1. `engine/universe.py` → adapter sulle API reali dei cinque provider, con cache e gestione
   dei limiti di rate (OP-08 va chiuso prima: ripartizione dei campi e licenze d'uso).
2. Gemini è già collegato (`engine/llm.py`) per valutazione, notizie, revisione dei punteggi e
   report. Restano da fare: la chat della vista cliente dietro il backend FastAPI (oggi la
   chiave non può stare nel browser), i testi in italiano semplice generati dal modello invece
   che dai template di `engine/plain.py`, e una politica di retry e budget per i cicli live.
3. `engine/pipeline.py` → task Celery schedulati da Cron, con stato su PostgreSQL e cache
   Redis; gli step sono già funzioni separate.
4. `web/` → riscrittura in Next.js/TypeScript/Tailwind con Plotly, consumando le stesse
   strutture dati che oggi finiscono in `data.js` (il payload è lo schema di partenza
   dell'API FastAPI).
5. Notifiche → integrazione reale di Email, Telegram, WhatsApp e push, con consenso per
   canale (OP-15).

---

*Supporto decisionale su dati quantitativi: non sostituisce il consulente finanziario (S-01).
Dati di mercato sintetici, nessun ordine inviato ad alcun broker.*
