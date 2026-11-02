@echo off
rem  Toglie i controlli automatici. Non cancella niente della demo: solo le
rem  operazioni pianificate di Windows.
echo.
echo  Rimozione dei controlli automatici di AI Market Scout
echo.
for %%H in (00 02 04 06 08 10 12 14 16 18 20 22) do (
  schtasks /delete /f /tn "Market Scout %%H" 2>nul
)
rem  nomi delle versioni precedenti, se erano state create
for %%N in ("Market Scout mattina" "Market Scout AI mattina" "Market Scout pranzo" "Market Scout sera" "AI Market Scout") do (
  schtasks /delete /f /tn %%N 2>nul
)
echo.
echo  Fatto: da ora i dati si aggiornano solo quando lanci tu un ciclo.
echo.
pause
