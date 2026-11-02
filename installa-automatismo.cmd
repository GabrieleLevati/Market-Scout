@echo off
rem =====================================================================
rem  Registra il controllo OGNI DUE ORE in Utilita' di pianificazione.
rem  Da lanciare UNA VOLTA SOLA, con doppio clic.
rem
rem  Dodici cicli al giorno, uno ogni due ore ai minuti :05.
rem  Dieci sono SOLO CALCOLO: durano secondi e non costano niente.
rem  Due usano l'AI (10:05 e 22:05) con un tetto di 8 chiamate ciascuno:
rem  la quota gratuita di Gemini e' di circa 20 al giorno, 8+8 ci sta.
rem
rem  PERCHE' L'AI SOLO DUE VOLTE. Il controllo ogni due ore serve a vedere
rem  se qualcosa supera la soglia: quello lo fa il calcolo, che e' gratis e
rem  istantaneo. Il giudizio del modello serve sulle cose che emergono, non
rem  dodici volte al giorno sulle stesse.
rem
rem  Prima servono le variabili PERMANENTI (setx, non $env:):
rem    setx GEMINI_API_KEY "la-tua-chiave"
rem    setx GEMINI_MODEL   "gemini-3.8-flash"
rem    setx NTFY_TOPIC     "un-nome-lungo-e-non-indovinabile"
rem
rem  Per disinstallare tutto:  disinstalla-automatismo.cmd
rem =====================================================================

setlocal
set SCRIPT=%~dp0giornaliero.cmd

echo.
echo  AI Market Scout - controllo ogni due ore
echo  ---------------------------------------
echo.

for %%H in (00 02 04 06 08 12 14 16 18 20) do (
  schtasks /create /f /tn "Market Scout %%H" /sc daily /st %%H:05 /tr "\"%SCRIPT%\" 0" >nul
  if errorlevel 1 goto errore
  echo   %%H:05  solo calcolo
)
schtasks /create /f /tn "Market Scout 10" /sc daily /st 10:05 /tr "\"%SCRIPT%\" 8" >nul
if errorlevel 1 goto errore
echo   10:05  con AI, tetto 8 chiamate
schtasks /create /f /tn "Market Scout 22" /sc daily /st 22:05 /tr "\"%SCRIPT%\" 8" >nul
if errorlevel 1 goto errore
echo   22:05  con AI, tetto 8 chiamate

echo.
echo  Fatto: dodici controlli al giorno.
echo.
echo  Provane uno adesso, senza aspettare:
echo      schtasks /run /tn "Market Scout 12"
echo  poi apri giornaliero.log: deve finire con "ciclo concluso".
echo.
pause
exit /b 0

:errore
echo.
echo  Accesso negato: apri PowerShell come amministratore e rilancia da li'.
echo.
pause
exit /b 1
