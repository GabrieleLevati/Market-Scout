"""Motore di AI Market Scout & Investment Copilot (demo FDD AI-MARKET-SCOUT).

Mappa moduli -> FDD:
  universe.py      3.2 data provider (dati sintetici)
  indicators.py    3.4 indicatori tecnici
  valuation.py     BR-03 modello di valutazione (sostituisce il consensus analisti)
  llm.py           OP-07 client Gemini: cache, validazione, fallback
  agents.py        BR-03 agenti specialistici
  scoring.py       BR-04 Opportunity Score, OP-12 piano operativo
  triggers.py      BR-05 trigger di opportunità
  users.py         BR-01 profilo, BR-12 preferenze apprese
  portfolio.py     BR-08 monitoraggio portafoglio
  notifications.py BR-06/BR-07 notifiche selettive multicanale
  reports.py       BR-09/BR-11 report on demand e archivio
  plain.py         traduzione in italiano semplice per la vista cliente
  assistant.py     risposte dell'assistente a domande
  pipeline.py      3.1 workflow in 10 step
  decisions.py     scelte di demo contro i punti aperti dell'FDD
"""

__version__ = "0.1.0"
