"""Strato dati di mercato.

Nella demo sostituisce i data provider dell'FDD (3.2: Yahoo Finance, Finnhub,
Polygon, Alpha Vantage, Financial Modeling Prep) con un generatore
deterministico: stessi campi, stessa forma delle risposte, nessuna chiamata di
rete e nessuna licenza d'uso dei dati (OP-08). La ripartizione dei campi tra
provider è dichiarata in PROVIDER_MAP e usata nel log di esecuzione, così la
sostituzione con le API reali resta un lavoro di adapter.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from .valuation import fair_multiple, fair_value

TODAY = date.today()      # il ciclo è sempre quello di oggi
HISTORY_DAYS = 320

# Solo fatti pubblicati: prezzi, bilanci, guidance dell'azienda, operazioni
# degli insider, notizie. Nessun rating e nessun target price di analisti umani:
# il valore lo stima il sistema (engine/valuation.py) e il giudizio lo dà
# Gemini (engine/llm.py).
PROVIDER_MAP = {
    "Yahoo Finance": ["prezzi", "volumi", "storico OHLCV"],
    "Polygon": ["prezzi intraday", "volumi consolidati"],
    "Financial Modeling Prep": ["bilanci", "revenue", "EPS", "FCF", "ROE", "ROIC",
                                "debt/equity", "guidance dell'azienda"],
    "Finnhub": ["insider trading", "dati societari"],
    "Alpha Vantage": ["news", "earnings calendar", "earnings surprise"],
}

# ticker, nome, asset class, mercato, settore, dimensione, prezzo, qualità, trend, vol, forma
SPECS = [
    # --- Azioni USA ---
    ("AMD", "Advanced Micro Devices", "Azioni", "USA", "AI", "Large cap", 164.00, 0.90, 0.42, 0.44, "breakout"),
    ("MSFT", "Microsoft", "Azioni", "USA", "Tecnologia", "Mega cap", 498.50, 0.94, 0.18, 0.22, "steady"),
    ("NVDA", "NVIDIA", "Azioni", "USA", "AI", "Mega cap", 212.80, 0.95, 0.55, 0.42, "breakout"),
    ("GOOGL", "Alphabet", "Azioni", "USA", "Tecnologia", "Mega cap", 241.30, 0.90, 0.22, 0.26, "steady"),
    ("META", "Meta Platforms", "Azioni", "USA", "Tecnologia", "Mega cap", 712.40, 0.88, 0.25, 0.32, "correction"),
    ("AAPL", "Apple", "Azioni", "USA", "Tecnologia", "Mega cap", 268.90, 0.84, 0.10, 0.21, "steady"),
    ("JPM", "JPMorgan Chase", "Azioni", "USA", "Finanza", "Mega cap", 318.60, 0.80, 0.14, 0.19, "steady"),
    ("UNH", "UnitedHealth", "Azioni", "USA", "Healthcare", "Large cap", 352.10, 0.72, -0.06, 0.28, "correction"),
    ("LLY", "Eli Lilly", "Azioni", "USA", "Healthcare", "Mega cap", 905.00, 0.89, 0.20, 0.30, "steady"),
    ("XOM", "Exxon Mobil", "Azioni", "USA", "Energia", "Mega cap", 121.70, 0.68, 0.04, 0.23, "steady"),
    ("CAT", "Caterpillar", "Azioni", "USA", "Industriale", "Large cap", 445.20, 0.75, 0.16, 0.25, "steady"),
    ("KO", "Coca-Cola", "Azioni", "USA", "Consumer", "Mega cap", 74.60, 0.70, 0.05, 0.14, "steady"),
    # --- Azioni Europa ---
    ("ASML.AS", "ASML Holding", "Azioni", "Europa", "AI", "Mega cap", 892.00, 0.92, 0.28, 0.35, "correction"),
    ("SAP.DE", "SAP", "Azioni", "Europa", "Tecnologia", "Large cap", 262.40, 0.83, 0.19, 0.23, "steady"),
    ("NOVO-B.CO", "Novo Nordisk", "Azioni", "Europa", "Healthcare", "Large cap", 58.20, 0.78, -0.12, 0.31, "correction"),
    ("MC.PA", "LVMH", "Azioni", "Europa", "Consumer", "Large cap", 598.00, 0.76, -0.04, 0.27, "correction"),
    ("SIE.DE", "Siemens", "Azioni", "Europa", "Industriale", "Large cap", 241.90, 0.77, 0.15, 0.22, "steady"),
    ("AIR.PA", "Airbus", "Azioni", "Europa", "Industriale", "Large cap", 198.30, 0.74, 0.17, 0.24, "breakout"),
    ("ENEL.MI", "Enel", "Azioni", "Europa", "Energia", "Large cap", 8.42, 0.66, 0.09, 0.18, "steady"),
    ("ISP.MI", "Intesa Sanpaolo", "Azioni", "Europa", "Finanza", "Large cap", 5.12, 0.71, 0.12, 0.20, "steady"),
    ("STLAM.MI", "Stellantis", "Azioni", "Europa", "Consumer", "Mid cap", 9.86, 0.52, -0.22, 0.38, "correction"),
    # --- Azioni Asia ---
    ("TSM", "TSMC (ADR)", "Azioni", "Asia", "AI", "Mega cap", 268.00, 0.93, 0.34, 0.33, "steady"),
    ("7203.T", "Toyota Motor", "Azioni", "Asia", "Consumer", "Large cap", 3180.00, 0.73, 0.08, 0.21, "steady"),
    ("9984.T", "SoftBank Group", "Azioni", "Asia", "Tecnologia", "Large cap", 14250.00, 0.58, 0.30, 0.52, "breakout"),
    ("005930.KS", "Samsung Electronics", "Azioni", "Asia", "Tecnologia", "Mega cap", 92400.00, 0.79, 0.24, 0.30, "steady"),
    # --- ETF ---
    ("SPY", "SPDR S&P 500 ETF", "ETF", "USA", "Diversificato", "ETF", 712.30, 0.88, 0.12, 0.15, "steady"),
    ("QQQ", "Invesco QQQ Trust", "ETF", "USA", "Tecnologia", "ETF", 628.90, 0.86, 0.17, 0.20, "steady"),
    ("VWCE.DE", "Vanguard FTSE All-World", "ETF", "Global", "Diversificato", "ETF", 142.80, 0.87, 0.11, 0.14, "steady"),
    ("EXS1.DE", "iShares Core DAX", "ETF", "Europa", "Diversificato", "ETF", 198.40, 0.80, 0.10, 0.18, "steady"),
    ("SMH", "VanEck Semiconductor ETF", "ETF", "Global", "AI", "ETF", 348.60, 0.84, 0.31, 0.34, "breakout"),
    ("EEM", "iShares MSCI Emerging Markets", "ETF", "Asia", "Diversificato", "ETF", 56.20, 0.69, 0.07, 0.19, "steady"),
    # --- Obbligazioni ---
    ("IEF", "iShares 7-10Y Treasury", "Obbligazioni", "USA", "Obbligazionario", "Governativo", 97.40, 0.82, 0.03, 0.07, "steady"),
    ("TLT", "iShares 20+Y Treasury", "Obbligazioni", "USA", "Obbligazionario", "Governativo", 89.10, 0.74, -0.02, 0.14, "correction"),
    ("LQD", "iShares USD Investment Grade", "Obbligazioni", "USA", "Obbligazionario", "Corporate IG", 110.60, 0.79, 0.04, 0.08, "steady"),
    ("IEAC.AS", "iShares Core Euro Corp Bond", "Obbligazioni", "Europa", "Obbligazionario", "Corporate IG", 128.30, 0.78, 0.03, 0.06, "steady"),
    ("EMB", "iShares JPM USD EM Bond", "Obbligazioni", "Global", "Obbligazionario", "Emerging", 92.70, 0.63, 0.05, 0.11, "steady"),
    # --- Crypto ---
    ("BTC-USD", "Bitcoin", "Crypto", "Global", "Crypto", "Large cap", 118400.00, 0.80, 0.45, 0.58, "correction"),
    ("ETH-USD", "Ethereum", "Crypto", "Global", "Crypto", "Large cap", 4120.00, 0.72, 0.38, 0.68, "breakout"),
    ("SOL-USD", "Solana", "Crypto", "Global", "Crypto", "Mid cap", 243.00, 0.64, 0.52, 0.86, "breakout"),
    ("LINK-USD", "Chainlink", "Crypto", "Global", "Crypto", "Mid cap", 28.40, 0.55, 0.14, 0.78, "correction"),
    # --- Commodities ---
    ("XAUUSD", "Oro spot", "Commodities", "Global", "Materie prime", "Metalli preziosi", 4280.00, 0.81, 0.26, 0.17, "steady"),
    ("XAGUSD", "Argento spot", "Commodities", "Global", "Materie prime", "Metalli preziosi", 58.20, 0.70, 0.33, 0.31, "breakout"),
    ("CL=F", "Petrolio WTI", "Commodities", "Global", "Materie prime", "Energia", 61.40, 0.48, -0.14, 0.34, "correction"),
    ("HG=F", "Rame", "Commodities", "Global", "Materie prime", "Metalli industriali", 5.18, 0.67, 0.18, 0.25, "steady"),
    # --- REIT ---
    ("PLD", "Prologis", "REIT", "USA", "Immobiliare", "Logistica", 118.90, 0.76, 0.06, 0.22, "correction"),
    ("SPG", "Simon Property Group", "REIT", "USA", "Immobiliare", "Retail", 192.40, 0.69, 0.11, 0.24, "steady"),
    ("VNA.DE", "Vonovia", "REIT", "Europa", "Immobiliare", "Residenziale", 32.80, 0.58, 0.08, 0.28, "correction"),
    ("0823.HK", "Link REIT", "REIT", "Asia", "Immobiliare", "Retail", 38.60, 0.54, -0.09, 0.26, "correction"),
]

# Che cos'e' questo investimento, spiegato a chi non ha mai letto un bilancio.
# È il primo mattone della vista semplice: senza questa frase un ticker non
# significa niente per un cliente retail.
DESCRIPTIONS = {
    "AMD": "Produce i microchip usati nei computer e nei centri dati per l'intelligenza artificiale.",
    "MSFT": "È Microsoft: vende Windows, Office e i servizi informatici in cloud usati da aziende e scuole.",
    "NVDA": "Fa le schede grafiche e i chip su cui gira quasi tutta l'intelligenza artificiale.",
    "GOOGL": "È la società di Google: motore di ricerca, YouTube, Android e pubblicita' online.",
    "META": "È la società di Facebook, Instagram e WhatsApp: guadagna vendendo pubblicita'.",
    "AAPL": "È Apple: iPhone, Mac e iPad, più i servizi come iCloud e App Store.",
    "JPM": "La più grande banca americana: conti, prestiti, carte e gestione di patrimoni.",
    "UNH": "Assicurazioni sanitarie negli Stati Uniti: gestisce le cure di milioni di persone.",
    "LLY": "Casa farmaceutica americana, conosciuta per i farmaci contro diabete e obesità.",
    "XOM": "Petrolio e gas: estrae, raffina e vende carburanti in tutto il mondo.",
    "CAT": "Fa le macchine da cantiere: escavatori, ruspe e motori industriali.",
    "KO": "È Coca-Cola: bevande vendute in tutto il mondo.",
    "ASML.AS": "Olandese: costruisce i macchinari, unici al mondo, con cui si stampano i microchip.",
    "SAP.DE": "Tedesca: fa i programmi con cui le grandi aziende gestiscono conti, magazzino e personale.",
    "NOVO-B.CO": "Danese: produce insulina e i farmaci contro diabete e obesità più usati al mondo.",
    "MC.PA": "È LVMH, il gruppo francese del lusso: Louis Vuitton, Dior, champagne, orologi.",
    "SIE.DE": "È Siemens: tecnologia per fabbriche, treni e reti elettriche.",
    "AIR.PA": "È Airbus: costruisce aerei di linea, elicotteri e satelliti.",
    "ENEL.MI": "È Enel: produce e vende energia elettrica in Italia e in altri paesi.",
    "ISP.MI": "È Intesa Sanpaolo, la principale banca italiana.",
    "STLAM.MI": "È Stellantis, il gruppo di Fiat, Peugeot, Jeep e Citroen.",
    "TSM": "Taiwanese: fabbrica per conto di altre aziende la maggior parte dei microchip del mondo.",
    "7203.T": "È Toyota: il più grande produttore di automobili al mondo, forte sulle ibride.",
    "9984.T": "È SoftBank: un gruppo giapponese che investe in aziende tecnologiche.",
    "005930.KS": "È Samsung: telefoni, televisori e memorie per computer.",
    "SPY": "Un paniere che contiene insieme le 500 aziende americane più grandi.",
    "QQQ": "Un paniere delle 100 maggiori aziende tecnologiche americane.",
    "VWCE.DE": "Un paniere con migliaia di aziende di tutto il mondo: il modo più semplice di non puntare su una sola.",
    "EXS1.DE": "Un paniere con le 40 maggiori aziende tedesche.",
    "SMH": "Un paniere delle aziende che fanno microchip, in tutto il mondo.",
    "EEM": "Un paniere di aziende dei paesi emergenti: Cina, India, Brasile e altri.",
    "IEF": "Presta i suoi soldi allo Stato americano per 7-10 anni, in cambio di interessi.",
    "TLT": "Presta i suoi soldi allo Stato americano per oltre 20 anni: rende di più ma oscilla molto.",
    "LQD": "Presta i suoi soldi a grandi aziende americane solide, in cambio di interessi.",
    "IEAC.AS": "Presta i suoi soldi a grandi aziende europee solide, in euro.",
    "EMB": "Presta i suoi soldi agli Stati dei paesi emergenti: interessi più alti, rischio più alto.",
    "BTC-USD": "È il Bitcoin: una moneta digitale senza banca centrale, il prezzo sale e scende molto.",
    "ETH-USD": "È Ethereum: la rete su cui girano molte applicazioni digitali, con la sua moneta.",
    "SOL-USD": "È Solana: una rete digitale concorrente di Ethereum, più recente e più ballerina.",
    "LINK-USD": "È Chainlink: collega le reti digitali ai dati del mondo reale.",
    "XAUUSD": "È l'oro: il bene rifugio classico, si compra quando c'e' paura o inflazione.",
    "XAGUSD": "È l'argento: come l'oro, ma usato anche nell'industria, quindi oscilla di più.",
    "CL=F": "È il petrolio americano: il prezzo segue economia e tensioni internazionali.",
    "HG=F": "È il rame: serve a cavi, case e auto elettriche, e segue l'andamento dell'industria.",
    "PLD": "Affitta magazzini e centri logistici in tutto il mondo e incassa i canoni.",
    "SPG": "Possiede e affitta grandi centri commerciali negli Stati Uniti.",
    "VNA.DE": "È Vonovia: possiede e affitta centinaia di migliaia di appartamenti in Germania.",
    "0823.HK": "Possiede e affitta centri commerciali a Hong Kong.",
}

# Come si chiama questa asset class in italiano corrente.
CLASS_IN_WORDS = {
    "Azioni": "un'azione, cioè una piccola parte di un'azienda",
    "ETF": "un ETF, cioè un paniere che contiene tanti investimenti insieme",
    "Obbligazioni": "un'obbligazione, cioè un prestito che le fa incassare interessi",
    "Crypto": "una moneta digitale",
    "Commodities": "una materia prima",
    "REIT": "una società immobiliare quotata, che incassa affitti",
}

EQUITY_LIKE = {"Azioni", "REIT"}

# Valuta di quotazione per suffisso di ticker e cambi verso EUR, la valuta di
# riferimento dei profili demo (3.4: "valuta di riferimento").
CURRENCY_BY_SUFFIX = {".MI": "EUR", ".DE": "EUR", ".PA": "EUR", ".AS": "EUR",
                      ".CO": "EUR", ".T": "JPY", ".KS": "KRW", ".HK": "HKD"}
FX_TO_EUR = {"EUR": 1.0, "USD": 0.92, "JPY": 0.0057, "KRW": 0.00065, "HKD": 0.118}


def currency_of(ticker: str) -> str:
    for suffix, cur in CURRENCY_BY_SUFFIX.items():
        if ticker.endswith(suffix):
            return cur
    return "USD"


def _rng(ticker: str, salt: str) -> random.Random:
    return random.Random(f"{ticker}|{salt}|v1")


def trading_days(n: int, end: date = TODAY) -> list[str]:
    days: list[str] = []
    d = end
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d.isoformat())
        d -= timedelta(days=1)
    return list(reversed(days))


def _series(spec) -> dict:
    """OHLCV sintetico: GBM con drift annuo `trend`, volatilità `vol` e una
    'forma' che riproduce i casi d'uso dei trigger (breakout / correzione)."""
    ticker, _, _, _, _, _, price, _, trend, vol, shape = spec
    r = _rng(ticker, "px")
    n = HISTORY_DAYS
    dt = 1 / 252
    closes = [100.0]
    for i in range(1, n):
        drift, noise = trend, 1.0
        if shape == "breakout":
            # compressione laterale (da 70 a 12 sedute fa) e poi rottura
            if n - i <= 12:
                drift, noise = 2.80, 0.40
            elif n - i < 70:
                drift, noise = 0.0, 0.35
        elif shape == "correction":
            # salita fino al massimo relativo, poi ritracciamento
            if n - i <= 45:
                drift, noise = -1.30, 0.7
            else:
                drift = abs(trend) * 1.3
        shock = r.gauss(0, 1) * vol * noise * (dt ** 0.5)
        closes.append(closes[-1] * (1 + drift * dt + shock))
    scale = price / closes[-1]
    closes = [c * scale for c in closes]

    highs, lows, opens, volumes = [], [], [], []
    base_vol = 10 ** r.uniform(5.8, 7.6)
    for i, c in enumerate(closes):
        o = closes[i - 1] if i else c
        # il range intraday segue la direzione della seduta: così i
        # massimi/minimi restano coerenti con il trend e l'ADX è significativo
        rng_day = 0.45 * abs(c - o) + 0.25 * c * vol * (dt ** 0.5) * r.uniform(0.5, 1.1)
        highs.append(max(o, c) + rng_day * r.uniform(0.3, 0.9))
        lows.append(min(o, c) - rng_day * r.uniform(0.3, 0.9))
        opens.append(o)
        mult = 1.0
        if shape == "breakout" and n - i <= 4:
            mult = r.uniform(1.8, 2.6)
        volumes.append(base_vol * r.uniform(0.75, 1.25) * mult)
    return {
        "date": trading_days(n),
        "open": [round(x, 4) for x in opens],
        "high": [round(x, 4) for x in highs],
        "low": [round(x, 4) for x in lows],
        "close": [round(x, 4) for x in closes],
        "volume": [round(x) for x in volumes],
    }


def _fundamentals(spec, snap, mis: float) -> dict:
    """Dati fondamentali. Per le asset class senza bilancio l'FDD non definisce
    il set di metriche (OP-10): la demo usa un set proxy per asset class,
    dichiarato nel campo `basis`."""
    ticker, _, acls, _, sector, _, price, q, trend, vol, shape = spec
    r = _rng(ticker, "fund")
    j = lambda lo, hi: r.uniform(lo, hi)  # noqa: E731

    if acls in EQUITY_LIKE:
        growth_sector = {"AI": 1.7, "Tecnologia": 1.05, "Healthcare": 0.85,
                         "Finanza": 0.6, "Energia": 0.45, "Industriale": 0.7,
                         "Consumer": 0.5, "Immobiliare": 0.45}.get(sector, 0.7)
        rev_g = (0.02 + 0.20 * q ** 2) * growth_sector * j(0.85, 1.15)
        f = {
            "basis": "bilancio",
            "revenue_growth": round(rev_g, 4),
            "eps_growth": round(rev_g * j(1.0, 1.9), 4),
            "gross_margin": round(0.22 + 0.45 * q * j(0.85, 1.15), 4),
            "net_margin": round(0.02 + 0.28 * q ** 1.5 * j(0.8, 1.2), 4),
            "fcf_margin": round(0.01 + 0.26 * q ** 1.4 * j(0.8, 1.2), 4),
            "roe": round(0.03 + 0.32 * q ** 1.3 * j(0.85, 1.15), 4),
            "roic": round(0.02 + 0.26 * q ** 1.3 * j(0.85, 1.15), 4),
            "debt_to_equity": round(max(0.05, (1.9 - 1.5 * q) * j(0.7, 1.4)), 3),
            "cash_usd_m": round(10 ** j(2.4, 4.9)),
            # revisione della guidance dell'azienda negli ultimi 30 giorni: è un
            # fatto comunicato dall'emittente, non l'opinione di un analista
            "guidance_change_30d": round(
                (j(0.01, 0.07) if (shape == "breakout" and q > 0.8)
                 else j(-0.05, -0.01) if q < 0.6
                 else j(-0.02, 0.03)), 4),
        }
        # Il prezzo di mercato nasce dal valore: il multiplo pagato oggi è il
        # multiplo giusto scontato dello scostamento di prezzo (_mispricing).
        f["pe"] = round(max(5.0, fair_multiple(f) * (1 - mis)), 1)
        if acls == "REIT":
            f.update(ffo_growth=round(rev_g * 0.7, 4),
                     occupancy=round(0.82 + 0.16 * q, 4),
                     ltv=round(0.55 - 0.2 * q, 4),
                     dividend_yield=round(0.028 + 0.035 * (1 - q), 4))
        return f

    # Per le asset class senza utili lo scostamento dal valore entra come
    # `valuation_gap` (o, per le obbligazioni, come movimento atteso dei tassi):
    # il modello di valutazione lo usa in engine/valuation.py.
    gap = round(mis * 0.35, 4)
    revision = round(j(-0.02, 0.05) * (0.5 + q), 4)

    if acls == "ETF":
        return {"basis": "proxy ETF",
                "expense_ratio": round(0.0003 + 0.0045 * (1 - q), 5),
                "aum_usd_m": round(10 ** j(3.0, 5.6)),
                "dividend_yield": round(0.004 + 0.022 * (1 - q), 4),
                "tracking_difference": round(j(-0.0012, 0.0012), 5),
                "index_earnings_growth": round(0.02 + 0.16 * q * j(0.8, 1.2), 4),
                "valuation_gap": gap, "estimate_revision_30d": revision}

    if acls == "Obbligazioni":
        return {"basis": "proxy obbligazionario",
                "yield_to_maturity": round(0.022 + 0.045 * (1 - q) * j(0.8, 1.2), 4),
                "duration": round(j(2.0, 18.0), 1),
                "credit_quality": {True: "AAA-AA", False: "BBB"}[q > 0.78],
                "spread_bp": round(j(5, 320) * (1.2 - q)),
                "real_yield": round(j(-0.004, 0.021), 4),
                "expected_rate_change_1y": round(max(-0.012, min(0.008, -mis * 0.09)), 4),
                "estimate_revision_30d": round(revision * 0.3, 4)}

    if acls == "Crypto":
        return {"basis": "proxy crypto on-chain",
                "market_cap_usd_m": round(10 ** j(4.0, 6.3)),
                "active_addresses_growth_90d": round(j(-0.15, 0.55) * q * 2, 4),
                "developer_activity_index": round(20 + 75 * q * j(0.85, 1.1), 1),
                "supply_inflation": round(j(0.0, 0.065) * (1.2 - q), 4),
                "fees_growth_90d": round(j(-0.25, 0.9) * q, 4),
                "valuation_gap": gap, "estimate_revision_30d": revision}

    return {"basis": "proxy commodity",
            "inventory_trend_90d": round(j(-0.22, 0.25) * (1 - q) * 2, 4),
            "real_yield_context": round(j(-0.01, 0.022), 4),
            "dollar_index_trend_90d": round(j(-0.07, 0.07), 4),
            "demand_proxy_growth": round(j(-0.1, 0.22) * q * 1.6, 4),
            "valuation_gap": gap, "estimate_revision_30d": revision}


def _mispricing(spec) -> float:
    """Di quanto il mercato prezza l'asset sotto il suo valore.

    È il parametro con cui il generatore crea il lavoro dell'AI Valuation
    Agent: il prezzo di mercato viene costruito a partire dal valore, non il
    contrario. Un numero positivo significa prezzo sotto il valore, quindi
    spazio di rivalutazione."""
    ticker, _, acls, _, _, _, _, q, trend, vol, shape = spec
    r = _rng(ticker, "mis")
    base = {"steady": 0.12, "breakout": 0.14, "correction": 0.28}[shape]
    return round(base + r.gauss(0, 0.07) + 0.35 * max(q - 0.75, 0.0), 4)


# Titoli di stampa per asset class: il lessico di un'azione non vale per un
# ETF, un titolo di stato o una commodity, e il Sentiment Agent legge questi.
HEADLINES = {
    "Azioni": (
        ["{name}: ricavi trimestrali oltre le attese, guidance alzata",
         "{name} annuncia un nuovo contratto pluriennale con un cliente hyperscaler",
         "Broker alza il target price su {name} dopo i dati di settore",
         "{name}: domanda sostenuta e portafoglio ordini in crescita"],
        ["{name}: margini sotto pressione per l'aumento dei costi",
         "Rallenta la domanda nel segmento principale di {name}",
         "{name} rinvia il lancio del prodotto atteso nel trimestre",
         "Indagine regolatoria apre un fronte di rischio su {name}"],
        ["{name} conferma il piano industriale senza modifiche",
         "Riunione annuale di {name}: nessuna revisione della guidance",
         "{name}: volumi di scambio in linea con la media del periodo"],
    ),
    "ETF": (
        ["Flussi netti in ingresso su {name} per la quarta settimana consecutiva",
         "{name}: l'indice sottostante aggiorna i massimi di periodo",
         "Revisione al rialzo delle stime di utile sui titoli dell'indice di {name}"],
        ["Deflussi da {name} dopo la revisione delle stime di settore",
         "{name}: aumenta la dispersione dei rendimenti tra i titoli dell'indice",
         "Pressione sui pesi principali dell'indice replicato da {name}"],
        ["{name}: ribilanciamento trimestrale dell'indice senza variazioni rilevanti",
         "{name}: patrimonio gestito stabile nell'ultimo mese"],
    ),
    "Obbligazioni": (
        ["Attesa di tassi più bassi: domanda sostenuta sul segmento di {name}",
         "{name}: spread in restringimento dopo l'asta",
         "Raccolta positiva sui fondi obbligazionari del comparto di {name}"],
        ["Risalita dei rendimenti di mercato: pressione sui prezzi di {name}",
         "{name}: allargamento degli spread dopo i dati sull'inflazione",
         "Revisione al rialzo delle attese sui tassi: penalizzata la duration di {name}"],
        ["{name}: composizione e duration del portafoglio confermate",
         "{name}: cedole incassate in linea con il profilo del comparto"],
    ),
    "Crypto": (
        ["Afflussi record sugli ETP collegati a {name}",
         "{name}: indirizzi attivi e commissioni di rete in crescita",
         "Nuove integrazioni di pagamento sostengono l'adozione di {name}"],
        ["Indagine regolatoria apre un fronte di rischio su {name}",
         "{name}: deflussi dagli ETP e liquidità in calo sugli exchange",
         "Liquidazioni a leva amplificano la correzione di {name}"],
        ["{name}: volumi on-chain stabili nell'ultima settimana",
         "{name}: nessuna modifica rilevante al protocollo"],
    ),
    "Commodities": (
        ["Scorte in calo: domanda industriale sostenuta su {name}",
         "{name}: offerta sotto le attese dopo i tagli alla produzione",
         "Tassi reali in discesa: interesse degli investitori su {name}"],
        ["Scorte in aumento e domanda debole su {name}",
         "Dollaro forte pesa sui prezzi di {name}",
         "{name}: rallentamento dei consumi industriali nei dati mensili"],
        ["{name}: prezzi stabili, mercato in attesa dei dati sulle scorte",
         "{name}: posizioni speculative nette invariate"],
    ),
    "REIT": (
        ["{name}: canoni in crescita e tasso di occupazione ai massimi",
         "{name} completa una cessione di portafoglio sopra il valore di libro",
         "Attesa di tassi più bassi: rivalutazione del portafoglio di {name}"],
        ["{name}: sfitto in aumento e rinegoziazione dei canoni",
         "Costo del debito più alto: pressione sul FFO di {name}",
         "Svalutazioni di portafoglio attese per {name}"],
        ["{name} conferma la politica di distribuzione",
         "{name}: valutazioni del portafoglio immobiliare invariate"],
    ),
}


def _news(spec, snap) -> list[dict]:
    ticker, name, acls, _, _, _, _, q, trend, vol, shape = spec
    r = _rng(ticker, "news")
    pos, neg, neu = HEADLINES.get(acls, HEADLINES["Azioni"])
    bias = (q - 0.72) * 1.3 + (0.20 if shape == "breakout" else 0) - (0.28 if shape == "correction" else 0)
    out = []
    for i in range(r.randint(4, 6)):
        p = r.gauss(bias, 0.38)
        pool = pos if p > 0.25 else neg if p < -0.25 else neu
        out.append({
            "date": (TODAY - timedelta(days=r.randint(0, 13))).isoformat(),
            "headline": r.choice(pool).format(name=name),
            "source": r.choice(["Reuters", "Bloomberg", "MarketWatch", "Il Sole 24 Ore"]),
            "polarity": round(max(-1.0, min(1.0, p)), 3),
        })
    return sorted(out, key=lambda x: x["date"], reverse=True)


def _insider(spec) -> dict:
    ticker, _, acls, _, _, _, _, q, trend, vol, shape = spec
    if acls not in EQUITY_LIKE:
        return {"coverage": False}
    r = _rng(ticker, "ins")
    roles = ["CEO", "CFO", "COO", "Direttore divisione", "Membro del board"]
    role = r.choice(roles)
    net = r.choice([0, 0, 1]) * r.uniform(0.2, 9.0) * 1_000_000
    if shape in ("breakout", "correction") and q > 0.75:
        net = max(net, r.uniform(1.5, 12.0) * 1_000_000)
    return {"coverage": True, "window_days": 90,
            "net_buy_usd": round(net), "top_role": role,
            "transactions": r.randint(1, 7)}


def _earnings(spec) -> dict:
    ticker, _, acls, _, _, _, _, q, trend, vol, shape = spec
    if acls not in EQUITY_LIKE:
        return {"coverage": False}
    r = _rng(ticker, "earn")
    eps_est = r.uniform(0.4, 6.0)
    surprise = r.gauss((q - 0.62) * 0.12, 0.05)
    rev_surprise = r.gauss((q - 0.62) * 0.08, 0.03)
    return {"coverage": True,
            "report_date": (TODAY - timedelta(days=r.randint(5, 40))).isoformat(),
            "eps_estimate": round(eps_est, 2),
            "eps_actual": round(eps_est * (1 + surprise), 2),
            "eps_surprise": round(surprise, 4),
            "revenue_surprise": round(rev_surprise, 4)}


def load_universe() -> list[dict]:
    """Restituisce l'universo investibile con dati grezzi + indicatori."""
    from .indicators import snapshot

    out = []
    for spec in SPECS:
        ticker, name, acls, market, sector, size, price, q, trend, vol, shape = spec
        series = _series(spec)
        snap = snapshot(series)
        mis = _mispricing(spec)
        cur = currency_of(ticker)
        out.append({
            "ticker": ticker, "name": name, "asset_class": acls, "market": market,
            "sector": sector, "size": size, "currency": cur, "fx_to_eur": FX_TO_EUR[cur],
            "description": DESCRIPTIONS.get(ticker, ""),
            "class_in_words": CLASS_IN_WORDS.get(acls, acls),
            "series": series, "tech": snap,
            "fundamentals": _fundamentals(spec, snap, mis),
            "mispricing": mis,
            "news": _news(spec, snap),
            "insider": _insider(spec),
            "earnings": _earnings(spec),
            "_shape": shape,
        })
        # stima di valore del sistema: sostituisce il target price degli analisti
        out[-1]["valuation"] = fair_value(out[-1])
    return out
