@echo off
rem =====================================================================
rem  Prepara la cartella da mettere online, con le analisi di Gemini.
rem
rem  Doppio clic su questo file e aspetta. Alla fine trovi la cartella
rem  "pubblica" pronta da trascinare su Cloudflare Pages.
rem
rem  Che cosa fa, in ordine:
rem    1. il ciclo sui dati veri con le analisi dell'AI (tetto 8 chiamate)
rem    2. aggiorna la TUA dashboard in web\
rem    3. prepara sito\ SENZA il tuo profilo e le tue posizioni
rem    4. controlla che in sito\ non ci siano dati personali
rem
rem  Il passo 4 deve dire "Nessuna fuga di dati personali": se dice altro,
rem  NON pubblicare e chiedi aiuto.
rem =====================================================================

cd /d "%~dp0"

set FLAGS=--real --live --llm-limit 2 --llm-pace 5 --llm-budget 8

echo.
echo  [1/4] Ciclo con le analisi di Gemini. Ci vogliono alcuni minuti:
echo        ogni risposta del modello arriva in 30-160 secondi.
echo.
python cli.py scan %FLAGS%
if errorlevel 1 goto errore

echo.
echo  [2/4] Aggiorno la tua dashboard (web\index.html)
python build_web.py %FLAGS%
if errorlevel 1 goto errore

echo.
echo  [3/4] Preparo la cartella "sito", senza i tuoi dati
python build_web.py %FLAGS% --pubblico --cartella sito
if errorlevel 1 goto errore

echo.
echo  [4/4] Controllo privacy
python tools\selftest_pubblico.py
if errorlevel 1 goto nonpubblicare

echo.
echo  ==================================================================
echo   Pronto. Ora trascina la cartella "sito" su Cloudflare Pages:
echo   dash.cloudflare.com - Workers ^& Pages - il tuo progetto -
echo   Create new deployment - trascina la cartella - Deploy.
echo  ==================================================================
echo.
start "" "%~dp0"
pause
exit /b 0

:nonpubblicare
echo.
echo  FERMATI: il controllo privacy non e' passato. Non pubblicare questa
echo  cartella. Guarda il messaggio qui sopra.
echo.
pause
exit /b 1

:errore
echo.
echo  Un passo ha restituito un errore. Guarda il messaggio qui sopra.
echo  Se parla di quota o di 429, la quota giornaliera di Gemini e'
echo  esaurita: riprova domani, oppure togli --live dalla riga FLAGS
echo  qui dentro per pubblicare comunque con il solo calcolo.
echo.
pause
exit /b 1
