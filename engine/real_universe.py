"""Universo investibile costruito sui dati veri.

Produce esattamente la stessa forma di dati di `universe.load_universe()`, così
tutto il resto del motore — indicatori, agenti, scoring, trigger, notifiche,
vista cliente — non cambia di una riga. È la cucitura prevista dall'FDD: cambia
il provider, non il sistema.

Che cosa è reale e che cosa manca, per ogni asset, sta in `data_quality` e viene
mostrato a schermo. Senza un contratto dati a pagamento non sono disponibili:

* operazioni degli insider (serve Finnhub o simili) -> trigger disattivato;
* bilanci di ETF, obbligazioni, crypto e materie prime -> nessuna stima di
  valore, quindi l'asset viene monitorato ma non proposto;
* la polarità delle notizie, che qui non è un dato ma un giudizio: la produce
  Gemini (con `--live`), altrimenti il sentiment resta neutro e lo dice.
"""

from __future__ import annotations

from datetime import date

from .indicators import snapshot
from .providers import DataError, Yahoo, derive_fundamentals, statement_currency
from .universe import CLASS_IN_WORDS, DESCRIPTIONS, FX_TO_EUR
from .valuation import fair_value, peer_stats

# simbolo Yahoo, nome, asset class, mercato, settore, dimensione, query per le news
REAL_SPECS = [
    ("AMD", "Advanced Micro Devices", "Azioni", "USA", "AI", "Large cap", "AMD"),
    ("MSFT", "Microsoft", "Azioni", "USA", "Tecnologia", "Mega cap", "Microsoft"),
    ("NVDA", "NVIDIA", "Azioni", "USA", "AI", "Mega cap", "Nvidia"),
    ("GOOGL", "Alphabet", "Azioni", "USA", "Tecnologia", "Mega cap", "Alphabet Google"),
    ("META", "Meta Platforms", "Azioni", "USA", "Tecnologia", "Mega cap", "Meta Platforms"),
    ("AAPL", "Apple", "Azioni", "USA", "Tecnologia", "Mega cap", "Apple"),
    ("JPM", "JPMorgan Chase", "Azioni", "USA", "Finanza", "Mega cap", "JPMorgan"),
    ("UNH", "UnitedHealth", "Azioni", "USA", "Healthcare", "Large cap", "UnitedHealth"),
    ("LLY", "Eli Lilly", "Azioni", "USA", "Healthcare", "Mega cap", "Eli Lilly"),
    ("XOM", "Exxon Mobil", "Azioni", "USA", "Energia", "Mega cap", "Exxon Mobil"),
    ("CAT", "Caterpillar", "Azioni", "USA", "Industriale", "Large cap", "Caterpillar"),
    ("KO", "Coca-Cola", "Azioni", "USA", "Consumer", "Mega cap", "Coca-Cola"),
    ("ASML.AS", "ASML Holding", "Azioni", "Europa", "AI", "Mega cap", "ASML"),
    ("SAP.DE", "SAP", "Azioni", "Europa", "Tecnologia", "Large cap", "SAP SE"),
    ("NOVO-B.CO", "Novo Nordisk", "Azioni", "Europa", "Healthcare", "Large cap", "Novo Nordisk"),
    ("MC.PA", "LVMH", "Azioni", "Europa", "Consumer", "Large cap", "LVMH"),
    ("SIE.DE", "Siemens", "Azioni", "Europa", "Industriale", "Large cap", "Siemens AG"),
    ("AIR.PA", "Airbus", "Azioni", "Europa", "Industriale", "Large cap", "Airbus"),
    ("ENEL.MI", "Enel", "Azioni", "Europa", "Energia", "Large cap", "Enel SpA"),
    ("ISP.MI", "Intesa Sanpaolo", "Azioni", "Europa", "Finanza", "Large cap", "Intesa Sanpaolo"),
    ("STLAM.MI", "Stellantis", "Azioni", "Europa", "Consumer", "Mid cap", "Stellantis"),
    ("TSM", "TSMC (ADR)", "Azioni", "Asia", "AI", "Mega cap", "TSMC"),
    ("7203.T", "Toyota Motor", "Azioni", "Asia", "Consumer", "Large cap", "Toyota Motor"),
    ("9984.T", "SoftBank Group", "Azioni", "Asia", "Tecnologia", "Large cap", "SoftBank Group"),
    ("005930.KS", "Samsung Electronics", "Azioni", "Asia", "Tecnologia", "Mega cap",
     "Samsung Electronics"),
    ("SPY", "SPDR S&P 500 ETF", "ETF", "USA", "Diversificato", "ETF", "S&P 500 ETF"),
    ("QQQ", "Invesco QQQ Trust", "ETF", "USA", "Tecnologia", "ETF", "Nasdaq 100 ETF"),
    ("VWCE.DE", "Vanguard FTSE All-World", "ETF", "Global", "Diversificato", "ETF",
     "Vanguard FTSE All-World"),
    ("EXS1.DE", "iShares Core DAX", "ETF", "Europa", "Diversificato", "ETF", "DAX ETF"),
    ("SMH", "VanEck Semiconductor ETF", "ETF", "Global", "AI", "ETF", "semiconductor ETF"),
    ("EEM", "iShares MSCI Emerging Markets", "ETF", "Asia", "Diversificato", "ETF",
     "emerging markets ETF"),
    ("IEF", "iShares 7-10Y Treasury", "Obbligazioni", "USA", "Obbligazionario", "Governativo",
     "Treasury bond ETF"),
    ("TLT", "iShares 20+Y Treasury", "Obbligazioni", "USA", "Obbligazionario", "Governativo",
     "long Treasury ETF"),
    ("LQD", "iShares USD Investment Grade", "Obbligazioni", "USA", "Obbligazionario",
     "Corporate IG", "investment grade bond ETF"),
    ("IEAC.AS", "iShares Core Euro Corp Bond", "Obbligazioni", "Europa", "Obbligazionario",
     "Corporate IG", "euro corporate bond ETF"),
    ("EMB", "iShares JPM USD EM Bond", "Obbligazioni", "Global", "Obbligazionario", "Emerging",
     "emerging market bond ETF"),
    ("BTC-USD", "Bitcoin", "Crypto", "Global", "Crypto", "Large cap", "Bitcoin"),
    ("ETH-USD", "Ethereum", "Crypto", "Global", "Crypto", "Large cap", "Ethereum"),
    ("SOL-USD", "Solana", "Crypto", "Global", "Crypto", "Mid cap", "Solana"),
    ("LINK-USD", "Chainlink", "Crypto", "Global", "Crypto", "Mid cap", "Chainlink"),
    ("GC=F", "Oro (future)", "Commodities", "Global", "Materie prime", "Metalli preziosi",
     "gold price"),
    ("SI=F", "Argento (future)", "Commodities", "Global", "Materie prime", "Metalli preziosi",
     "silver price"),
    ("CL=F", "Petrolio WTI (future)", "Commodities", "Global", "Materie prime", "Energia",
     "crude oil price"),
    ("HG=F", "Rame (future)", "Commodities", "Global", "Materie prime", "Metalli industriali",
     "copper price"),
    ("PLD", "Prologis", "REIT", "USA", "Immobiliare", "Logistica", "Prologis"),
    ("SPG", "Simon Property Group", "REIT", "USA", "Immobiliare", "Retail", "Simon Property"),
    ("VNA.DE", "Vonovia", "REIT", "Europa", "Immobiliare", "Residenziale", "Vonovia"),
    ("0823.HK", "Link REIT", "REIT", "Asia", "Immobiliare", "Retail", "Link REIT"),
]

# descrizioni in parole semplici: le stesse della demo, con i simboli che cambiano
DESCRIPTION_ALIASES = {"GC=F": "XAUUSD", "SI=F": "XAGUSD"}

MIN_FUNDAMENTAL_FIELDS = 8      # sotto questa soglia l'asset non si può valutare


def peer_for_label(asset: dict, peers: dict) -> dict | None:
    from .valuation import peer_for
    p = peer_for(asset, peers)
    if not p:
        return None
    sector = asset["sector"] if asset["sector"] in peers.get("sectors", {}) else "tutto il listino"
    return {"reference": sector, "pe_median": round(p["pe"], 1),
            "growth_median": round(p.get("growth") or 0.0, 4), "n": p["n"]}


def _description(symbol: str) -> str:
    return DESCRIPTIONS.get(DESCRIPTION_ALIASES.get(symbol, symbol), "")


def _earnings_from_fundamentals(f: dict) -> dict:
    """"Conti migliori del previsto" senza previsioni di analisti: confronto
    con lo stesso trimestre dell'anno prima, che è un fatto pubblicato."""
    rev, eps = f.get("quarterly_revenue_yoy"), f.get("quarterly_eps_yoy")
    if rev is None and eps is None:
        return {"coverage": False, "reason": "nessun bilancio trimestrale disponibile"}
    return {"coverage": True, "basis": "crescita anno su anno",
            "report_date": f.get("last_report_date") or date.today().isoformat(),
            "revenue_yoy": rev, "eps_yoy": eps,
            # campi usati dagli agenti: qui la "sorpresa" è la crescita reale
            "revenue_surprise": rev, "eps_surprise": eps}


def load_real_universe(provider: Yahoo | None = None, only: list[str] | None = None,
                       on_progress=None) -> tuple[list[dict], list[dict]]:
    """Scarica e normalizza l'universo. Restituisce (asset, scartati)."""
    y = provider or Yahoo()
    specs = [s for s in REAL_SPECS if not only or s[0] in only]
    fx_cache: dict[str, float] = {}
    assets: list[dict] = []
    skipped: list[dict] = []

    for i, (symbol, name, acls, market, sector, size, query) in enumerate(specs):
        if on_progress:
            on_progress(i + 1, len(specs), symbol)
        try:
            chart = y.chart(symbol)
        except DataError as e:
            skipped.append({"ticker": symbol, "reason": str(e)})
            continue

        price = chart["close"][-1]
        cur = chart["currency"] or "USD"
        if cur not in fx_cache:
            fx_cache[cur] = y.fx_to_eur(cur) or FX_TO_EUR.get(cur) or 1.0
        series = {k: chart[k] for k in ("date", "open", "high", "low", "close", "volume")}

        try:
            statements = y.statements(symbol)
        except DataError:
            statements = {}

        # L'utile per azione va portato nella valuta del prezzo, altrimenti il
        # rapporto prezzo/utili non significa niente.
        stmt_cur = statement_currency(statements)
        eps_fx, fx_note = 1.0, None
        if stmt_cur and stmt_cur != cur:
            if stmt_cur not in fx_cache:
                fx_cache[stmt_cur] = y.fx_to_eur(stmt_cur) or FX_TO_EUR.get(stmt_cur) or 0.0
            if fx_cache[stmt_cur] and fx_cache[cur]:
                eps_fx = fx_cache[stmt_cur] / fx_cache[cur]
                fx_note = f"utile per azione convertito da {stmt_cur} a {cur}"
            else:
                fx_note = f"bilanci in {stmt_cur}, prezzo in {cur}: cambio non disponibile"

        f = derive_fundamentals(statements, price, eps_fx=eps_fx)
        has_fundamentals = f["fields_available"] >= MIN_FUNDAMENTAL_FIELDS
        if not has_fundamentals:
            f = {"basis": "solo prezzo (nessun bilancio disponibile senza contratto dati)",
                 "fields_available": f["fields_available"]}

        # Controllo di sanità: un utile per azione negativo o un multiplo fuori
        # scala rendono la stima di valore priva di senso. Si dichiara, non si
        # pubblica un numero sbagliato.
        valuation_note = fx_note
        valuable = has_fundamentals
        if has_fundamentals:
            pe = f.get("pe")
            if not f.get("eps_ttm") or f["eps_ttm"] <= 0:
                valuable, valuation_note = False, "utile per azione negativo o nullo"
            elif not pe or pe < 3 or pe > 150:
                valuable = False
                valuation_note = (f"rapporto prezzo/utili fuori scala ({pe:.0f}x)" if pe
                                  else "rapporto prezzo/utili non calcolabile")

        news = y.news(symbol, query=query)
        asset = {
            "ticker": symbol, "name": name, "asset_class": acls, "market": market,
            "sector": sector, "size": size, "currency": cur,
            "fx_to_eur": fx_cache[cur],
            "description": _description(symbol),
            "class_in_words": CLASS_IN_WORDS.get(acls, acls),
            "series": series, "tech": snapshot(series),
            "fundamentals": f,
            "news": news,
            "insider": {"coverage": False,
                        "reason": "dati insider non disponibili senza contratto dati"},
            "earnings": _earnings_from_fundamentals(f) if has_fundamentals
            else {"coverage": False, "reason": "nessun bilancio trimestrale disponibile"},
            "valuable": valuable,
            "valuation_note": valuation_note,
            "data_quality": {
                "source": "Yahoo Finance",
                "bars": len(series["close"]),
                "last_bar": series["date"][-1],
                # L'ora dell'ultimo scambio secondo la borsa. Sta qui e non in
                # "series" perche' series e' un dizionario di liste parallele,
                # che gli indicatori e il grafico scorrono per indice: un
                # valore singolo in mezzo le romperebbe.
                "market_time": chart.get("market_time"),
                "fundamental_fields": f.get("fields_available", 0),
                "fundamentals": has_fundamentals,
                "valuable": valuable,
                "note": valuation_note or "",
                "news": len(news),
                "news_polarity": "da modello" if news else "nessuna notizia",
                "insider": False,
                "fx_live": cur in fx_cache and cur != "EUR",
            },
            "_shape": "reale",
        }
        assets.append(asset)

    # Secondo passaggio: il multiplo giusto si misura sui simili, quindi serve
    # prima avere tutto il listino (DEMO-26).
    peers = peer_stats(assets)
    for a in assets:
        a["valuation"] = fair_value(a, peers)
        a["peers"] = peer_for_label(a, peers)
    return assets, skipped
