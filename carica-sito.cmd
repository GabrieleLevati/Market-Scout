@echo off
rem =====================================================================
rem  Prepara il caricamento su Cloudflare. Doppio clic.
rem
rem  Non ricalcola niente: ci pensano i cicli automatici ogni due ore, che
rem  rigenerano la cartella "sito" da soli. Questo comando serve a sapere
rem  SE e' il momento di caricare, e ad aprire quello che ti serve.
rem
rem  Che cosa fa:
rem    1. controlla che non ci sia un ciclo in corso (caricare a meta'
rem       scrittura vorrebbe dire pubblicare file incoerenti)
rem    2. dice di quando e' la cartella e cosa contiene
rem    3. rifa il controllo privacy, perche' si pubblica solo se passa
rem    4. apre la cartella e il pannello di Cloudflare
rem =====================================================================

cd /d "%~dp0"
setlocal

echo.
echo  AI Market Scout - caricamento su Cloudflare
echo  ===========================================
echo.

rem --- 1. c'e' un ciclo in corso? ------------------------------------------
tasklist /fi "imagename eq python.exe" 2>nul | find /i "python.exe" >nul
if not errorlevel 1 (
  echo  ATTENZIONE: c'e' un processo python in esecuzione.
  echo  Potrebbe essere un ciclo che sta ancora scrivendo la cartella.
  echo  Guarda le ultime righe di giornaliero.log: se non c'e' ancora
  echo  "ciclo concluso", aspetta che finisca prima di caricare.
  echo.
  powershell -NoProfile -Command "Get-Content giornaliero.log -Tail 3 | ForEach-Object { '    ' + $_ }" 2>nul
  echo.
  choice /c SN /m "Vuoi continuare comunque"
  if errorlevel 2 goto fine
  echo.
)

rem --- 2. di quando e' la cartella ------------------------------------------
echo  --- La cartella da caricare -------------------------------------
powershell -NoProfile -Command "$f = Get-Item 'sito\data.js' -ErrorAction SilentlyContinue; if ($f) { '  dati del ciclo:  ' + $f.LastWriteTime.ToString('dd/MM/yyyy HH:mm') } else { '  MANCA sito\data.js: lancia prima giornaliero.cmd 0' }" 2>nul
powershell -NoProfile -Command "$n = (Get-ChildItem 'sito' -File -ErrorAction SilentlyContinue).Count; '  file da caricare: ' + $n + ' (devono essere 11)'" 2>nul
powershell -NoProfile -Command "$d = Get-Content 'sito\data.js' -Raw -ErrorAction SilentlyContinue; if ($d -match '\""data_mode\"":\s*\""([a-z]+)\""') { '  tipo di dati:     ' + $Matches[1] }; if ($d -match '\""mode\"":\s*\""(live[^\""]*)\""') { '  analisi AI:       ' + $Matches[1] }" 2>nul
echo.

rem --- 3. il controllo privacy, sempre -------------------------------------
echo  --- Controllo privacy -------------------------------------------
python tools\selftest_pubblico.py
if errorlevel 1 goto nonpubblicare
echo.

rem --- 4. apri quello che serve --------------------------------------------
echo  --- Che cosa fare ora -------------------------------------------
echo.
echo   1. Nella finestra che si apre: CTRL+A per selezionare gli 11 file
echo   2. Su Cloudflare: il tuo progetto - Create new deployment
echo   3. Trascina i file. Controlla che ci sia index.html e nessun .cmd
echo   4. Deploy
echo.
echo   Se hai cambiato la grafica, dopo il deploy DISINSTALLA e REINSTALLA
echo   l'app: l'indirizzo di partenza lo legge quando la installi.
echo.
start "" "%~dp0sito"
start "" "https://dash.cloudflare.com"
goto fine

:nonpubblicare
echo.
echo  FERMATI: il controllo privacy non e' passato. NON caricare questa
echo  cartella. Guarda il messaggio qui sopra.
echo.

:fine
pause
