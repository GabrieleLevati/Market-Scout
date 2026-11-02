@echo off
rem =====================================================================
rem  AI Market Scout - ciclo automatico
rem
rem  Esegue la scansione sui dati veri con le analisi di Gemini, invia le
rem  segnalazioni su Telegram e aggiorna la dashboard.
rem
rem  NOTIFICHE. Il ciclo chiede --notifica: annuncia solo le opportunita'
rem  NUOVE, non tutte quelle sopra soglia, altrimenti con dodici controlli al
rem  giorno arriverebbero dodici messaggi sulle stesse cose. Dove arrivano lo
rem  decidono le variabili d'ambiente:
rem    setx NTFY_TOPIC "un-nome-lungo-e-non-indovinabile"   notifica sul telefono
rem    setx SMTP_HOST / SMTP_USER / SMTP_PASS / SMTP_TO     email
rem    setx TELEGRAM_TOKEN / TELEGRAM_CHAT_ID               Telegram
rem  Se non ne imposti nessuna, il ciclo gira e lo scrive nel log, senza inviare.
rem
rem  USO
rem    giornaliero.cmd            ciclo con AI, tetto 8 chiamate (default)
rem    giornaliero.cmd 8          come sopra, tetto scritto a mano
rem    giornaliero.cmd 0          solo calcolo: nessuna chiamata all'AI,
rem                               dura secondi e non consuma quota
rem
rem  PERCHE' UN TETTO. Il piano gratuito di Gemini concede una ventina di
rem  chiamate al giorno. Il ciclo costa 7 chiamate fisse + 4 per strumento
rem  analizzato dal modello. Con tetto 8 ogni ciclo spende 8: due cicli al
rem  giorno fanno 16 e restano dentro la quota.
rem
rem  Prima di pianificarlo servono le variabili d'ambiente PERMANENTI
rem  (setx, non $env:, altrimenti l'operazione pianificata non le vede):
rem
rem    setx GEMINI_API_KEY   "la-tua-chiave"
rem    setx GEMINI_MODEL     "gemini-3.8-flash"
rem    setx TELEGRAM_TOKEN   "il-token-del-bot"
rem    setx TELEGRAM_CHAT_ID "il-tuo-chat-id"
rem
rem  DUE AGGIORNAMENTI AL GIORNO (una volta sola, da PowerShell):
rem
rem    schtasks /create /tn "Market Scout mattina" /sc daily /st 07:40 ^
rem             /tr "\"%~f0\" 8"
rem    schtasks /create /tn "Market Scout sera" /sc daily /st 22:30 ^
rem             /tr "\"%~f0\" 8"
rem
rem  Gli orari contano: alle 07:40 i mercati americani e asiatici hanno
rem  chiuso, alle 22:30 ha chiuso anche New York. A mercati aperti l'ultima
rem  candela giornaliera e' ancora incompleta, quindi l'analisi userebbe un
rem  prezzo provvisorio. Se vuoi un aggiornamento anche a meta' giornata,
rem  usalo senza AI:  /tr "\"%~f0\" 0"
rem
rem  Per fermarli:  schtasks /delete /tn "Market Scout mattina" /f
rem =====================================================================

cd /d "%~dp0"

set TETTO=%1
if "%TETTO%"=="" set TETTO=8

rem  SOGLIA. Quella dell'FDD e' 85 su 100, ma sui dati veri quasi nessuno la
rem  supera: a 85 la pagina dice "niente oggi" quasi ogni giorno. A 70 si
rem  vedono gli strumenti della fascia "da monitorare" del motore. Cambia qui
rem  e cambia per tutti i cicli: e' l'unico posto dove e' scritta.
set SOGLIA=70

rem  FINE SETTIMANA: niente AI. Sabato e domenica le borse sono chiuse, i
rem  prezzi sono quelli di venerdi' e non cambiano: far giudicare al modello
rem  gli stessi numeri brucerebbe la quota per avere la stessa risposta. Il
rem  ciclo gira comunque, sul solo calcolo, e lo scrive nel log.
python -c "import datetime,sys; sys.exit(0 if datetime.date.today().weekday()>=5 else 1)"
if not errorlevel 1 (
  if not "%TETTO%"=="0" (
    echo [%date% %time%] fine settimana: borse chiuse, niente chiamate all AI ^(quota risparmiata^)>> giornaliero.log
    set TETTO=0
  )
)

if "%TETTO%"=="0" (
  set MODO=solo calcolo
  set FLAGS=--real --threshold %SOGLIA%
) else (
  set MODO=con AI, tetto %TETTO% chiamate
  set FLAGS=--real --live --llm-limit 2 --llm-pace 5 --llm-budget %TETTO% --threshold %SOGLIA%
)

echo [%date% %time%] avvio ciclo (%MODO%)>> giornaliero.log

python cli.py scan %FLAGS% --notifica>> giornaliero.log 2>&1
set ESITO=%errorlevel%
if not "%ESITO%"=="0" (
  echo [%date% %time%] ERRORE nella scansione, codice %ESITO%>> giornaliero.log
)

rem  build_web.py rifa il ciclo per suo conto: con gli stessi flag riusa le
rem  risposte dalla cache e non consuma un'altra volta la quota. Con flag
rem  diversi ricomincerebbe da capo.
python build_web.py %FLAGS%>> giornaliero.log 2>&1
set ESITO=%errorlevel%
if not "%ESITO%"=="0" (
  rem  Il codice di uscita e' l'unica traccia che resta quando il processo
  rem  muore senza stampare niente: senza di esso un errore notturno non si
  rem  puo' diagnosticare la mattina dopo.
  echo [%date% %time%] ERRORE nell aggiornamento della dashboard, codice %ESITO%>> giornaliero.log
  echo [%date% %time%]   codice 1 = eccezione Python, vedi le righe qui sopra>> giornaliero.log
  echo [%date% %time%]   codice -1073741510 = interrotto, 3221225786 = Ctrl+C>> giornaliero.log
)

rem --- La cartella "sito" si rigenera a ogni ciclo, cosi' e' sempre pronta da
rem     trascinare su Cloudflare. Non contiene il tuo profilo ne' le tue
rem     posizioni, e il controllo subito dopo lo verifica: se trova dati
rem     personali scrive l'allarme nel log e tu NON devi pubblicare.
python build_web.py %FLAGS% --pubblico --cartella sito>> giornaliero.log 2>&1
python tools\selftest_pubblico.py>> giornaliero.log 2>&1
set ESITO=%errorlevel%
if not "%ESITO%"=="0" (
  echo [%date% %time%] ATTENZIONE: il controllo privacy NON e passato, non pubblicare la cartella sito>> giornaliero.log
)

rem --- Pubblicazione automatica (facoltativa): togli il "rem" dalle righe
rem     seguenti SOLO dopo aver fatto una volta il git init dentro sito e
rem     preparare e pubblicare ogni volta la cartella per gli amici. Il
rem     data.js pubblico NON contiene il tuo profilo ne le tue posizioni.
rem     Serve aver fatto una volta il git init dentro sito (vedi ISTRUZIONI.md).
rem python build_web.py %FLAGS% --pubblico --cartella sito>> giornaliero.log 2>&1
rem python tools\selftest_pubblico.py>> giornaliero.log 2>&1
rem pushd sito
rem git add -A>> ..\giornaliero.log 2>&1
rem git commit -m "ciclo del %date% %time%">> ..\giornaliero.log 2>&1
rem git push>> ..\giornaliero.log 2>&1
rem popd

echo [%date% %time%] ciclo concluso (%MODO%)>> giornaliero.log
