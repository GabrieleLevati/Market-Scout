@echo off
rem =====================================================================
rem  Un ciclo completo adesso, a mano, con le analisi dell'AI.
rem
rem  NORMALMENTE NON SERVE: il ciclo nel cloud fa la stessa cosa ogni due
rem  ore, anche a PC spento, e pubblica da solo (AUTOMATICO.md). Questo
rem  comando serve quando vuoi vedere il risultato subito, senza aspettare.
rem
rem  Che cosa fa, in ordine:
rem    1. il ciclo sui dati veri con le analisi dell'AI (tetto 8 chiamate)
rem    2. aggiorna la TUA dashboard in web\
rem    3. prepara da-caricare\ SENZA il tuo profilo e le tue posizioni
rem    4. controlla che in da-caricare\ non ci siano dati personali
rem
rem  Scrive in "da-caricare" e non in "sito" di proposito: "sito" e' la
rem  cartella che il cloud rigenera e pubblica, e due autori sullo stesso
rem  file generato significa conflitti dentro i dati (e' gia' successo).
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
echo  [3/4] Preparo la cartella "da-caricare", senza i tuoi dati
python build_web.py %FLAGS% --pubblico --cartella da-caricare
if errorlevel 1 goto errore

echo.
echo  [4/4] Controllo privacy
python tools\selftest_pubblico.py
if errorlevel 1 goto nonpubblicare

echo.
echo  ==================================================================
echo   Pronto. I dati nuovi sono nella tua dashboard (web\index.html).
echo   Se vuoi anche metterli online subito senza aspettare il ciclo
echo   automatico, lancia carica-sito.cmd: carica "da-caricare".
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
