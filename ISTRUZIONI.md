# Istruzioni passo a passo

Dal nulla a un prodotto che gira ogni mattina e ti scrive su Telegram. Sei passi, ognuno con
un **controllo**: se vedi quello che è scritto nel controllo, quel passo è a posto e puoi
andare avanti. Se un passo non funziona, i successivi non servono.

Tutti i comandi si lanciano da PowerShell, in questa cartella:

```powershell
cd C:\Users\levati2\ai-market-scout-demo
```

---

## Passo 0 — Prerequisiti (2 minuti)

```powershell
python --version
```

**Controllo:** risponde `Python 3.11` o superiore. Non serve altro: nessun `pip install`,
nessun `npm install`, nessuna libreria esterna.

---

## Passo 1 — Provarlo subito, senza dati veri e senza chiavi

```powershell
start web\index.html
```

Si apre il **questionario iniziale**: otto domande a risposta chiusa, nessun importo da
dichiarare, nessuna posizione da elencare. Alla fine ti mostra come ti ha capito ("profilo
bilanciato, orizzonte medio, mercati USA ed Europa…") e poi la tua pagina: che cosa ti
segnala oggi, perché, quanto rischi, che cosa farebbe al tuo posto.

**Controllo:** dopo il questionario vedi il saluto *"Buongiorno. Ho una cosa da farle
vedere"* (oppure *"Oggi non ho niente di urgente"*, che è una risposta legittima) e almeno un
riquadro con un nome di società, i tre numeri (prezzo di oggi / dove può arrivare / dove esco
se va male) e la frase in euro *"Ogni 1.000 euro investiti…"*.

In questo passo i dati di mercato sono **sintetici**: servono a far vedere come ragiona, non a
dare prezzi veri. Il pulsante *Vista analista* in alto a destra apre la dashboard tecnica con
tutti i punteggi; *Rifaccio il questionario* in fondo alla pagina rifà la profilazione.

---

## Passo 2 — Collegare i dati di mercato veri

Nessuna chiave, serve solo la rete. I dati arrivano da Yahoo Finance e finiscono in una cache
giornaliera (`.data_cache\`), quindi il secondo ciclo dello stesso giorno non tocca la rete.

```powershell
python cli.py data-check
```

**Controllo:** una tabella con circa 48 strumenti, la data dell'ultima seduta (quella di
borsa più recente), quante voci di bilancio sono state trovate e quante notizie. In fondo:
`48 strumenti, 27 valutabili, 0 esclusi`. Gli strumenti non valutabili sono dichiarati con il
motivo (ETF e obbligazioni non hanno bilanci accessibili senza un contratto dati: vengono
monitorati ma non proposti).

Poi il ciclo vero e la dashboard:

```powershell
python cli.py scan --real
python build_web.py --real
start web\index.html
```

**Controllo:** nella prima riga del terminale leggi `Dati: Yahoo Finance (dati reali) · ultima
seduta …`. Nella dashboard, in alto, la stessa dicitura; i prezzi ora sono quelli veri.

Nota: senza il modello linguistico la colonna **notizie** resta `n.d.` per tutti. Non è un
difetto: i titoli vengono raccolti ma leggerli è un giudizio, e quel giudizio lo dà Gemini
(passo 3). Il peso di quel componente viene ridistribuito sugli altri e il sistema lo scrive.

---

## Passo 3 — Collegare l'intelligenza artificiale (Gemini)

Serve una chiave API da Google AI Studio (`aistudio.google.com`, sezione *API key*).

```powershell
$env:GEMINI_API_KEY = "la-tua-chiave"
python cli.py llm-check
```

**Controllo:** `OK modello gemini-3.8-flash: connessione riuscita`. Se risponde questo, il
resto funziona. Se dà errore, vedi *Se qualcosa non va* in fondo.

```powershell
python cli.py scan --real --live --llm-limit 2 --llm-pace 5
python build_web.py --real --live --llm-limit 2 --llm-pace 5
```

**Perché 2 e non 7.** Il piano gratuito concede **una ventina di chiamate al giorno** (il
numero lo dichiara l'API stessa quando lo supera, e cambia nel tempo). Il ciclo costa
**7 chiamate fisse + 4 per ogni strumento analizzato dal modello**, misurate:

| perimetro | chiamate |
|---|---|
| `--llm-limit 2` | 15 — sta dentro la quota |
| `--llm-limit 3` | 19 — al limite |
| `--llm-limit 7` | 35 — la quota finisce a metà ciclo |

Oltre la quota il ciclo **non si ferma**: quello che resta lo fa il calcolo deterministico e
lo dichiara asset per asset. Ma è meglio scegliere il perimetro in partenza che scoprirlo a
metà. `--llm-pace 5` mette cinque secondi tra due chiamate.

I due comandi vogliono **gli stessi flag**: `build_web.py` rifa il ciclo per suo conto, e con
flag identici riusa le risposte dalla cache (`.llm_cache\`) senza consumare un'altra volta la
quota. Con flag diversi ricomincia da capo.

**Metti pazienza.** Sul piano gratuito una risposta arriva in 30-160 secondi, e il modello
risponde anche `503 - high demand` quando è carico: il client riprova una volta e poi passa
al calcolo. Con `--llm-limit 2` il ciclo dura qualche minuto; il terminale sembra fermo e non
lo è.

**Se vuoi l'AI su tutti i 34 strumenti** servono 143 chiamate: fuori portata per il piano
gratuito. Si attiva la fatturazione su Google AI Studio (per questo volume sono centesimi) e
si togliono `--llm-limit` e `--llm-pace`.

**Controllo:** nel terminale `Analisi qualitative: live · modello gemini-3.8-flash · 35
chiamate`. Nella dashboard, *Vista analista → Scelte di demo → Chi fa le analisi*: modalità
`live`, numero di chiamate e token. Nel dettaglio di un asset, il riquadro *Chi ha prodotto
questa analisi* dice per ogni agente se il punteggio viene da Gemini o dal calcolo.

---

## Passo 4 — Il tuo profilo, senza dichiarare importi

Due strade, scegli quella che preferisci. Il risultato è lo stesso file `profilo.json`.

**Dal browser** (più comodo): fai il questionario nella vista cliente, poi in fondo alla
pagina premi *Scarico il profilo per il computer* e sposta `profilo.json` in questa cartella.

Per mostrarlo a qualcuno saltando la compilazione, le risposte si possono mettere
nell'indirizzo:
`web\index.html?risposte=orizzonte:lungo,perdita:aspetto,esperienza:azioni|panieri,strumenti:azioni|panieri,mercati:usa|europa,settori:ai|tech,frequenza:due,canale:telegram`
(aggiungi `&conferma=1` per andare diretto alla pagina finale).

**Dal terminale:**

```powershell
python cli.py onboarding
```

Le stesse domande, una per volta; alla fine mostra il riepilogo e chiede se salvarlo.

**Controllo:**

```powershell
python cli.py agent me --real
```

Risponde con il saluto, *Che cosa ho fatto* (con i numeri del ciclo), *Che cosa le segnalo
oggi* e *Di che cosa mi occupo io*. Dove ci sono le percentuali, parla di "ogni 1.000 euro":
è la base neutra che usa quando non hai dichiarato nessun importo.

Il portafoglio resta facoltativo. Se un giorno vuoi che controlli anche quello che hai già,
aggiungi le posizioni in `profilo.json`:

```json
"positions": [
  { "ticker": "VWCE.DE", "quantity": 100, "avg_price": 120.0, "opened_on": "2025-01-15" }
]
```

`ticker` è il simbolo Yahoo Finance; se lasci `avg_price` a `null`, il prezzo di carico viene
preso dalla chiusura del giorno che indichi in `opened_on`.

---

## Passo 5 — Riceverle su Telegram

È il canale che si attiva in due minuti. Email, WhatsApp e push richiedono rispettivamente un
server SMTP, un numero approvato da Meta e un'app installata: restano da fare.

```powershell
# 1. su Telegram scrivi a @BotFather, comando /newbot, copia il token
$env:TELEGRAM_TOKEN = "il-token"
# 2. scrivi un messaggio qualsiasi al tuo bot (serve perché possa risponderti), poi:
python cli.py telegram-id
# 3. copia il numero che stampa:
$env:TELEGRAM_CHAT_ID = "il-numero"
# 4. il ciclo che scrive davvero:
python cli.py scan --real --live --telegram
```

**Controllo:** sul telefono arriva un messaggio con la segnalazione in italiano semplice — la
stessa che vedi nella vista cliente — oppure, se oggi non c'è niente sopra soglia, un
riepilogo. Nel terminale: `Telegram attivo: 1 messaggi inviati`.

I messaggi partono **solo** per il profilo di `profilo.json`, non per i clienti dimostrativi, e
**solo se quel profilo ha Telegram tra i suoi canali**: nel questionario è la domanda «dove
vuole che le scriva» (chi risponde *«da nessuna parte: guardo io la pagina»* non riceve niente,
ed è il comportamento giusto). Se nel terminale leggi `Telegram attivo: 0 messaggi inviati`
mentre il token funziona, apri `profilo.json` e controlla la riga `"channels"`: ci deve essere
`"Telegram"`.

---

## Passo 6 — Farlo girare da solo, due volte al giorno

Le variabili d'ambiente vanno rese permanenti, altrimenti l'operazione pianificata non le
vede (`$env:` vale solo nella finestra aperta):

```powershell
setx GEMINI_API_KEY   "la-tua-chiave"
setx GEMINI_MODEL     "gemini-3.8-flash"
setx TELEGRAM_TOKEN   "il-token"
setx TELEGRAM_CHAT_ID "il-numero"
```

Poi, una volta sola: **doppio clic su `installa-automatismo.cmd`**, che registra i quattro
cicli. A mano sarebbero:

```powershell
schtasks /create /tn "Market Scout mattina"    /sc daily /st 07:40 /tr "C:\Users\levati2\ai-market-scout-demo\giornaliero.cmd 0"
schtasks /create /tn "Market Scout AI mattina" /sc daily /st 10:30 /tr "C:\Users\levati2\ai-market-scout-demo\giornaliero.cmd 8"
schtasks /create /tn "Market Scout pranzo"     /sc daily /st 13:30 /tr "C:\Users\levati2\ai-market-scout-demo\giornaliero.cmd 0"
schtasks /create /tn "Market Scout sera"       /sc daily /st 22:30 /tr "C:\Users\levati2\ai-market-scout-demo\giornaliero.cmd 8"
```

L'ultimo numero è il **tetto di chiamate all'AI**: `0` nessuna chiamata (solo calcolo, dura
secondi e costa zero), `8` fino a otto. Due cicli da 8 fanno 16, dentro la quota gratuita di
circa venti al giorno.

**Perché l'AI non gira alle 07:40.** La quota giornaliera si rinnova su orario americano, cioè
a metà mattina da noi. Un ciclo con AI alle 07:40 troverebbe la quota ancora spesa dal ciclo
della sera prima e girerebbe sul solo calcolo, senza che si capisca perché. Quindi alle 07:40
prezzi freschi gratis, e alle 10:30 il modello, che a quell'ora ha la quota piena.

**Perché non a mercati aperti.** L'ultima candela giornaliera è ancora in formazione, quindi un
ciclo di metà giornata lavora su un prezzo provvisorio: per questo quello delle 13:30 è senza
AI — aggiorna i prezzi e non spende giudizio su un dato incompleto.

`giornaliero.cmd` fa la scansione sui dati veri, invia su Telegram e aggiorna la dashboard;
scrive tutto in `giornaliero.log`.

**Controllo:** lancialo una volta a mano senza AI (`.\giornaliero.cmd 0`, dura secondi), poi apri
`giornaliero.log`: devi trovare `avvio ciclo` e `ciclo concluso` senza righe di errore in mezzo.
Per fermarli: `schtasks /delete /tn "Market Scout mattina" /f` (e così per gli altri).

**La pagina online non si aggiorna da sola.** `giornaliero.cmd` aggiorna la dashboard *sul tuo
computer*. Per aggiornare anche il sito che vedono gli amici servono le righe di pubblicazione
in fondo a `giornaliero.cmd`: togli i `rem` dopo aver fatto una volta il `git init` descritto
più sotto.

---

## Metterlo online e installarlo sul telefono

I passi, nell'ordine giusto: prima l'AI (così quello che pubblichi contiene le sue analisi),
poi la cartella, poi Cloudflare, poi il telefono.

### A. La chiave di Gemini

1. Vai su **aistudio.google.com**, entra col tuo account Google.
2. Cerca **Get API key** (o *Chiave API*) → **Create API key** → scegli o crea un progetto →
   copia la chiave. È una stringa lunga che inizia per `AIza...`.
3. In PowerShell, nella cartella del progetto:

   ```powershell
   setx GEMINI_API_KEY "incolla-qui-la-chiave"
   ```

   `setx` la rende permanente: **chiudi e riapri PowerShell**, altrimenti la sessione corrente
   non la vede. (Per una prova volante basta `$env:GEMINI_API_KEY = "..."`, valida solo in
   quella finestra.)
4. Verifica:

   ```powershell
   python cli.py llm-check
   ```

   Deve rispondere `OK modello gemini-3.8-flash: connessione riuscita`. Se dice che la chiave
   non è valida, è stata incollata con uno spazio; se dà 404 sul modello,
   `llm-check` ti dice quale usare: `setx GEMINI_MODEL "<quello>"`, riapri il terminale e riprova.

**La chiave non esce mai dal tuo computer.** Non finisce nella cartella pubblicata: è una
variabile d'ambiente, la legge solo il motore quando gira qui.

### B. La cartella da pubblicare

**Doppio clic su `aggiorna-sito.cmd`** e aspetta. Fa tutto da solo e in ordine: il ciclo con le
analisi di Gemini, la tua dashboard, la cartella `da-caricare\` senza i tuoi dati, e il
controllo privacy. Alla fine apre la cartella, pronta da trascinare.

A mano, se preferisci vedere i passaggi:

```powershell
python cli.py scan --real --live --llm-limit 2 --llm-pace 5 --llm-budget 8
python build_web.py --real --live --llm-limit 2 --llm-pace 5 --llm-budget 8
python build_web.py --real --live --llm-limit 2 --llm-pace 5 --llm-budget 8 --pubblico --cartella da-caricare
python tools\selftest_pubblico.py
```

L'ultima riga **deve** dire «Nessuna fuga di dati personali». Se dice altro, non pubblicare.
`da-caricare\` e' circa 1 MB; `web\` resta la tua, con il tuo profilo dentro.

**La cartella `sito\` non si genera dal PC.** Quella la rigenera e la pubblica il ciclo nel
cloud ogni due ore ([AUTOMATICO.md](AUTOMATICO.md)). Se la riscrivi anche da qui, lo stesso
file generato ha due autori e git ci scrive dentro i propri marcatori di conflitto: il
`data.js` smette di essere leggibile e la pagina diventa bianca. È già capitato una volta.

**La cache del telefono si invalida da sola.** Il nome della cache dentro `sw.js` pubblicato è
l'impronta dei file della pagina (DEMO-35): quando cambi la grafica, l'impronta cambia e chi ha
già il sito aperto riceve la versione nuova. Senza questo accorgimento gli amici resterebbero
sulla versione vecchia senza che tu possa farci niente a distanza.

### C. Cloudflare Pages

Il modo più rapido, senza installare niente (le voci del pannello possono chiamarsi leggermente
diverso: Cloudflare cambia spesso i nomi):

1. **dash.cloudflare.com** → crea un account gratuito e conferma la mail.
2. Nel menù a sinistra: **Workers & Pages** → **Create** → scheda **Pages** →
   **Upload assets** (caricamento diretto).
3. Dai un nome al progetto: diventa l'indirizzo, `nome-che-scegli.pages.dev`.
4. Trascina dentro la cartella **`sito`** (tutta la cartella, non i file singoli) →
   **Deploy**.
5. Dopo mezzo minuto hai `https://nome-che-scegli.pages.dev`. È già in HTTPS, e serve: senza
   HTTPS il telefono non propone l'installazione come app.

**Per aggiornare**: stesso progetto → **Create new deployment** → trascini di nuovo la
cartella. Un minuto al giorno.

**Per automatizzarlo** (hai git installato), una volta sola:

```powershell
cd sito
git init
git add -A
git commit -m "prima pubblicazione"
git branch -M main
git remote add origin https://github.com/TUO-UTENTE/market-scout.git
git push -u origin main
```

Poi su Cloudflare: **Workers & Pages → Create → Pages → Connect to Git**, scegli quel
repository, *framework preset* **None**, comando di build vuoto, cartella di output `/`. Da quel
momento ogni `git push` ripubblica il sito. Le due righe pronte per il ciclo giornaliero sono in
fondo a `giornaliero.cmd` (basta togliere i `rem`). La cartella `sito\` si può rigenerare
quante volte vuoi: il `.git` dentro non viene toccato.

**Per renderlo privato** (solo gli amici invitati): Cloudflare **Zero Trust → Access →
Applications → Add an application → Self-hosted**, dominio `nome.pages.dev`, e una policy
*Allow* con **Emails** = gli indirizzi dei tuoi amici e metodo **One-time PIN**. Chi apre il
link riceve un codice per email e solo allora entra. Il piano gratuito copre fino a 50 persone;
la prima volta Cloudflare chiede di attivare Zero Trust sull'account.

### D. Installarlo sul telefono

1. Apri il link `https://nome.pages.dev` dal telefono.
2. **Android (Chrome)**: menù ⋮ → **Installa app** (o *Aggiungi a schermata Home*).
3. **iPhone**: devi usare **Safari** → tasto **Condividi** → **Aggiungi alla schermata Home** →
   *Aggiungi*.
4. Compare l'icona: si apre a schermo pieno, senza barre del browser.
5. Alla prima apertura fai il questionario **su quel telefono**: il profilo resta lì, non viene
   mandato da nessuna parte. Ogni amico fa il suo, sul suo telefono.

Dopo la prima apertura l'app funziona **anche senza rete**: mostra l'ultimo ciclo scaricato.
Quando c'è campo controlla da sola se ne è stato pubblicato uno nuovo.

La data del ciclo è scritta in alto, accanto al nome: se il tuo computer non ha girato stamattina,
si vede dalla data.

## Verifiche automatiche

```powershell
python tools\selftest_onboarding.py   # questionario: regole, comportamento, parità pagina/motore
python tools\selftest_pubblico.py     # il file da pubblicare non contiene dati personali
python tools\selftest_llm.py          # integrazione Gemini, simulando le risposte dell API
python tools\confronto_profili.py --threshold 70   # chi riceve che cosa, a parità di analisi
node tools\selftest_vista.js          # la pagina eseguita davvero: questionario, profilo, due viste
```

L'ultimo richiede Node (`node --version`); se non c'è, gli altri quattro restano validi:
quello controlla la pagina, non il motore.

## Il prodotto è testabile quando

- [ ] il questionario si completa e la pagina mostra la tua situazione
- [ ] `data-check` elenca gli strumenti con la data dell'ultima seduta di borsa
- [ ] `llm-check` risponde OK e il ciclo `--live` riporta chiamate fatte
- [ ] `agent me --real` parla del tuo profilo, senza che tu abbia dichiarato importi
- [ ] su Telegram arriva la segnalazione o il riepilogo
- [ ] `giornaliero.cmd` scrive `ciclo concluso` nel log
- [ ] `python tools\selftest_pubblico.py` dice "Nessuna fuga di dati personali" (da ripetere
      ogni volta che pubblichi la pagina online)

## Se qualcosa non va

| Messaggio | Che cosa fare |
|---|---|
| `Python was not found` | installa Python 3.11+ da python.org e riapri PowerShell |
| `GEMINI_API_KEY non impostata` | la chiave non è in *questa* finestra: ripeti il passo 3 (o usa `setx` e riapri) |
| `HTTP 400 … API key not valid` | chiave errata o incollata con spazi |
| `HTTP 404` sul modello | **la chiave funziona**: è il nome del modello a essere superato. `llm-check` ti stampa quello da usare, preso dal messaggio dell'API: `setx GEMINI_MODEL "<quello-suggerito>"`, riapri il terminale, riprova |
| `HTTP 429` | quota del piano esaurita (una ventina di chiamate al giorno) oppure troppe richieste al minuto. Il client riprova dopo 15 s e, se arrivano tre rifiuti di fila, sospende per due minuti e poi riprende; il terminale ti dice dopo quante chiamate è finita. Il ciclo non si ferma mai: il resto lo fa il calcolo e lo dichiara. Rimedi: `--llm-limit 2`, `--llm-pace 10`, aspettare il giorno dopo |
| `HTTP 503 … high demand` | il modello è sovraccarico, non è colpa tua: un nuovo tentativo è automatico, poi quell'analisi la fa il calcolo. Riprova più tardi |
| `CERTIFICATE_VERIFY_FAILED` | è l'ispezione TLS della rete aziendale: la CA aziendale deve stare nelle *Autorità di certificazione radice attendibili* di Windows |
| `TimeoutError: read operation timed out` | la risposta ha superato i 240 s: capita sul piano gratuito quando è carico. Il ciclo continua sul calcolo; rilancia più tardi o alza `TIMEOUT_S` in `engine\llm.py` |
| `risposta troncata dal tetto di … token` | il modello ha speso l'uscita nel ragionamento. Non dovrebbe più succedere (il ragionamento è spento, DEMO-33): se capita, segnalalo perché vuol dire che l'API ha cambiato comportamento |
| sembra bloccato, non scrive niente per minuti | normale con `--live`: 30-160 s per risposta. Senza `--live` il ciclo dura secondi |
| `solo N sedute disponibili` su uno strumento | lo strumento ha meno di 260 sedute di storico: viene escluso e lo dice |
| Telegram: `chat not found` | non hai ancora scritto al bot: mandagli un messaggio e rifai `telegram-id` |
| la dashboard mostra dati vecchi | ricorda `python build_web.py --real --live` dopo ogni scansione |

## Per farlo usare a qualcun altro

Tre strade, spiegate per esteso in [COME-FUNZIONA.md](COME-FUNZIONA.md):

1. **gli mandi la cartella `web\`** (1 MB): apre `index.html`, fa il suo questionario, vede la
   sua pagina. Dati fermi al giorno in cui hai generato il file, nessuna notifica;
2. **metti la cartella online** su Cloudflare Pages (gratis) e lasci che si aggiorni da sé
   ogni due ore, anche a PC spento, con il ciclo nel cloud ([AUTOMATICO.md](AUTOMATICO.md)):
   un solo link per tutti, con i dati del giorno. È il punto di equilibrio migliore, ed è
   la strada che questo progetto usa. Se il cloud è fermo e devi caricare a mano, generi con
   `python build_web.py --real --live --pubblico --cartella da-caricare` (tiene fuori il tuo
   profilo e le tue posizioni, e non tocca la tua dashboard privata);
3. **prodotto multiutente** (backend, database, login, canali per utente): è l'architettura
   dell'FDD, ed è il grosso del lavoro che resta.

Per mostrarlo in dieci secondi senza compilare niente: `index.html?esempio=1`.

## Limiti noti, da sapere prima di usarlo

- **Non è un consulente.** È un programma che legge dati e spiega che cosa ha trovato: nessuna
  garanzia di rendimento, nessuna raccomandazione personalizzata. Le decisioni restano tue.
- **Non compra e non vende.** L'agente osserva, avvisa sui livelli e ricorda una volta; non
  invia ordini a nessun broker.
- **Dati senza contratto.** Operazioni degli insider, bilanci di ETF e obbligazioni e metriche
  on-chain delle crypto non sono disponibili: quegli strumenti vengono monitorati ma non
  proposti, e il motivo è scritto a schermo.
- **La chat della vista cliente non chiama Gemini.** Una pagina statica non può custodire una
  chiave API: le risposte sono quelle preparate dal motore. Il percorso con il modello si
  prova da terminale con `--live`.
- **Un solo canale reale.** Telegram. Email, WhatsApp e push sono previsti dal documento ma
  non implementati.
