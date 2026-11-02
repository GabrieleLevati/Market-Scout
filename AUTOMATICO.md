# Tutto automatico, anche col computer spento

Oggi il ciclo gira sul tuo PC e la pubblicazione la fai a mano. Dopo questi
passaggi gira su una macchina di GitHub ogni due ore, pubblica da sola su
Cloudflare, e **il tuo computer può essere spento**.

Tempo: mezz'ora, una volta sola. Costo: zero.

---

## Come funziona, in una figura

```
   GITHUB (ogni 2 ore, PC spento)              CLOUDFLARE
   ────────────────────────────────            ──────────
   scarica i prezzi veri da Yahoo
   rifà i calcoli                      ──┐
   alle 10:05 e 22:05 chiama l'AI        │
   esegue i test                         │
   controlla la privacy                  │
   salva la cartella "sito" nel repo   ──┴──►  vede il commit
                                               ripubblica il sito
                                               ↓
                                        gli amici vedono i dati nuovi
```

Nessun passaggio dal tuo computer. Il PC ti serve solo se vuoi guardare la
dashboard privata con il tuo profilo (`web\index.html`).

---

## Passo 1 — La chiave di Groq (4 minuti)

Serve perché l'AI giri in tempi umani: Gemini risponde in 30-180 secondi,
Groq in circa uno. Su una macchina di GitHub il tempo è il vincolo.

1. **console.groq.com** → entra con Google → **API Keys** → *Create API Key*
2. Copia la chiave (inizia per `gsk_`) e **tienila da parte**: serve al passo 4.

Groq è il secondo modello: entra in gioco solo quando Gemini non può
rispondere (quota finita, tetto raggiunto, sovraccarico). Mai entrambi per la
stessa domanda.

Se vuoi provarlo anche sul PC: `setx LLM2_FORNITORE "groq"` e
`setx LLM2_KEY "gsk_..."`, poi riapri il terminale e `python cli.py llm-check`:
deve rispondere OK su **due** blocchi.

---

## Passo 2 — Il repository su GitHub (10 minuti)

1. **github.com** → crea un account se non ne hai.
2. In alto a destra **+** → **New repository**.
   - Nome: `market-scout`
   - **Private** ← importante: non c'è nulla di segreto nel codice, ma non c'è
     motivo di darlo in pasto ai motori di ricerca
   - Non aggiungere README, .gitignore o licenza: ci sono già
   - **Create repository**
3. GitHub ti mostra due righe con l'indirizzo del repository. Tienile aperte.
4. Nella cartella del progetto, da PowerShell:

```powershell
cd C:\Users\levati2\ai-market-scout-demo
git init
git add -A
git commit -m "AI Market Scout"
git branch -M main
git remote add origin https://github.com/TUO-UTENTE/market-scout.git
git push -u origin main
```

Alla prima `git push` GitHub ti chiede di entrare: segui la finestra che si
apre.

**Che cosa NON finisce nel repository**, ed è deliberato (`.gitignore`):
`profilo.json` (il tuo profilo), `web/data.js` (la dashboard privata, che il
profilo lo contiene), `giornaliero.log`, le cache. Nel repository va il
codice, e la cartella `sito` che per costruzione non ha dati personali.

---

## Passo 3 — Le chiavi, al sicuro (3 minuti)

Le chiavi **non** vanno nel codice. Si mettono nella cassaforte di GitHub.

Nel repository: **Settings** → **Secrets and variables** → **Actions** →
**New repository secret**, una per volta:

| Nome | Valore | Serve a |
|---|---|---|
| `GEMINI_API_KEY` | la tua chiave `AIza...` | il primo modello |
| `LLM2_KEY` | la chiave `gsk_...` di Groq | il secondo modello |
| `NTFY_TOPIC` | un nome lungo e non indovinabile | la notifica sul telefono (facoltativa) |

Le puoi rileggere? No: GitHub le mostra una volta sola. Le puoi sostituire in
qualunque momento.

---

## Passo 4 — Cloudflare guarda il repository (5 minuti)

Finora caricavi i file a mano. Da adesso Cloudflare li prende da sé.

1. **dash.cloudflare.com** → **Workers & Pages** → **Create** → scheda
   **Pages** → **Connect to Git**
2. Autorizza GitHub e scegli il repository `market-scout`
3. Impostazioni di build:
   - *Framework preset*: **None**
   - *Build command*: **lascia vuoto**
   - *Build output directory*: **`sito`** ← questa è la riga che conta
4. **Save and Deploy**

Dopo un minuto hai un indirizzo `nome.pages.dev`. Da quel momento **ogni volta
che il ciclo salva dati nuovi, Cloudflare ripubblica da sé**.

> Il progetto Worker che hai adesso puoi lasciarlo o cancellarlo: questo è un
> progetto nuovo, con un indirizzo nuovo. Quando il nuovo funziona, manda
> quello agli amici.

---

## Passo 5 — Provalo subito, senza aspettare due ore

Nel repository: **Actions** → **ciclo** → **Run workflow** → spunta
*con_ai* se vuoi provare anche il modello → **Run workflow**.

Dopo un paio di minuti clicca sull'esecuzione: trovi un riepilogo leggibile,
con quante opportunità sono uscite, quali sono nuove, quali sono scese sotto
soglia, e per ognuna se l'ha analizzata il modello o il calcolo.

Se il ciclo **fallisce**, non pubblica niente: il sito resta all'ultima
versione buona. I controlli automatici girano *prima* della pubblicazione
proprio per questo.

---

## Passo 6 — Spegni l'automatismo locale

Non serve più, e due automatismi che fanno la stessa cosa si pestano i piedi.

```powershell
cd C:\Users\levati2\ai-market-scout-demo
.\disinstalla-automatismo.cmd
```

Il PC resta utile per due cose: guardare la dashboard privata con il tuo
profilo, e provare le modifiche prima di mandarle online con `git push`.

---

## Gli orari

| Ora italiana | Che fa | Perché |
|---|---|---|
| 02:23, 04:23, 06:23, 08:23 | solo calcolo | prezzi aggiornati, costa zero |
| **10:23** | **con AI** | dopo il rinnovo della quota giornaliera |
| 12:23, 14:23, 16:23, 18:23, 20:23 | solo calcolo | segue la giornata |
| **22:23** | **con AI** | dopo la chiusura di New York |
| ogni push sul codice | solo calcolo | una modifica si vede online subito |
| sabato e domenica | niente AI | borse chiuse: i prezzi non cambiano |

Gli orari nel file sono in UTC (`.github/workflows/ciclo.yml`): d'inverno
l'Italia è un'ora avanti, d'estate due.

**Due inneschi, non uno, e non è pignoleria.** Lo scheduler di GitHub è
dichiaratamente *best effort*: accoda le esecuzioni programmate e nei momenti
di carico le ritarda o le salta. Su questo repository, con i cron ai minuti
`:05`, **non è partito niente**: quattro slot consecutivi a vuoto in cinque
ore, mentre i lanci a mano riuscivano al primo colpo. Da qui due scelte: i
minuti spostati a `:23`, fuori dall'inizio dell'ora dove la coda è più lunga,
e un secondo innesco `push` che non dipende dallo scheduler.

Se un giorno anche così i giri programmati non arrivassero, la via d'uscita
esiste e non passa da GitHub: uno *scheduler esterno* che chiama l'API di
GitHub per lanciare il workflow — un Cron Trigger di Cloudflare Workers
(sei già su Cloudflare, e i cron sono nel piano gratuito) oppure un servizio
come cron-job.org. Serve un token con permesso di avviare i workflow, ed è
l'unico modo di avere una cadenza garantita.

### Che cosa si rinnova davvero, e ogni quanto

Un ciclo ogni due ore non vuol dire che tutto si riscarica ogni due ore: ogni
tipo di dato scade quando ha senso che scada (`engine/providers.py`, `TTL_S`).

| Dato | Scade dopo | Perché |
|---|---|---|
| Prezzi e andamento | 90 minuti | si muovono durante la seduta: è il dato che vedi cambiare |
| Notizie | 3 ore | arrivano durante il giorno, ma non ogni ora |
| Bilanci societari | fine giornata | sono trimestrali: chiederli più spesso è spreco |

Per cambiare la freschezza dei prezzi senza toccare il codice c'è
`DATI_TTL_MIN` (minuti). Un valore basso rende i prezzi più vivi e moltiplica
le richieste a Yahoo e le pubblicazioni su Cloudflare; `0` scarica sempre.

In pagina, in alto, c'è l'orario a cui quei prezzi si riferiscono — **«prezzi
delle 15:40»** a mercati aperti, **«chiusura delle 22:00»** dopo. È l'ora
dell'ultimo scambio dichiarata dalla borsa, non quella del ciclo: a mercati
chiusi resta ferma, invece di far sembrare appena presi dei prezzi di dieci
ore prima.

A mercati chiusi, quindi, i cicli notturni girano, non trovano niente di
nuovo e **non pubblicano**: è giusto così, e si riconosce dal run verde con la
riga «Nessuna modifica: niente da pubblicare».

## Quanto costa

Zero. I repository privati hanno 2.000 minuti di Actions al mese: i dieci
cicli senza AI costano un paio di minuti ciascuno, i due con AI dipendono da
quanto è lento il modello — ed è il motivo per cui Groq conviene. Cloudflare
Pages è gratuito fino a 500 pubblicazioni al mese; qui sono una dozzina al
giorno nel caso peggiore, cioè circa 360.

Se un mese ti avvicinassi al limite, la leva è una: meno cicli al giorno.

## Se qualcosa non va

| Sintomo | Dove guardare |
|---|---|
| il sito non si aggiorna | GitHub → **Actions**: l'ultimo ciclo è verde? |
| il ciclo è rosso | aprilo: il passo che ha fallito è segnato in rosso |
| «controllo privacy non passato» | il ciclo si è fermato da sé e non ha pubblicato: è il comportamento giusto, segnalalo |
| l'AI non lavora mai | Actions → il riepilogo dice `analisi: offline`: controlla il segreto `GEMINI_API_KEY` |
| Cloudflare non pubblica | il progetto Pages punta al ramo `main` e a `sito`? |
