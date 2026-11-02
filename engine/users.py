"""Profili utente (BR-01), portafogli (BR-08), storico interazioni e
apprendimento delle preferenze (BR-12).

Le modalità di caricamento delle posizioni non sono definite nell'FDD (OP-05):
nella demo le posizioni sono inserite manualmente con quantità e prezzo medio
di carico.
"""

from __future__ import annotations

from datetime import timedelta

from .universe import TODAY

# Fasce di rischio ammesse per profilo - DEMO-11: l'FDD dice che "le
# raccomandazioni si adattano al profilo" (BR-01) senza quantificare.
RISK_CEILING = {"Conservativo": 40, "Bilanciato": 60, "Aggressivo": 85}

# DEMO-12 (OP-10): il dominio "Asset preferiti" del profilo non comprende
# Commodities e REIT, che però sono supportati (BR-13). Nella demo i REIT
# sono trattati sotto "Azioni" e le Commodities restano fuori dalle notifiche
# finché OP-10 non è chiuso; gli asset esclusi per questo motivo sono
# marcati nel log, non scartati in silenzio.
ASSET_CLASS_MAP = {"Azioni": ["Azioni", "REIT"], "ETF": ["ETF"],
                   "Obbligazioni": ["Obbligazioni"], "Crypto": ["Crypto"]}

USERS = [
    {
        "id": "u1", "name": "Marco Bianchi", "email": "marco.bianchi@example.com",
        "profile": {
            "capital": 85_000, "horizon": "Medio (3-5 anni)", "currency": "EUR",
            "country": "Italia", "risk_profile": "Bilanciato",
            "markets": ["USA", "Europa"],
            "sectors": ["Tecnologia", "AI", "Healthcare"],
            "asset_classes": ["Azioni", "ETF"],
        },
        "channels": ["Email", "Telegram", "Push"],
        "positions": [
            {"ticker": "MSFT", "quantity": 22, "avg_price": 402.10, "opened_on": "2025-06-12"},
            {"ticker": "ASML.AS", "quantity": 8, "avg_price": 712.50, "opened_on": "2025-09-03"},
            {"ticker": "QQQ", "quantity": 15, "avg_price": 561.40, "opened_on": "2025-02-20"},
            {"ticker": "NOVO-B.CO", "quantity": 230, "avg_price": 70.40, "opened_on": "2025-11-14"},
            {"ticker": "AMD", "quantity": 30, "avg_price": 138.20, "opened_on": "2026-03-05"},
            {"ticker": "SAP.DE", "quantity": 25, "avg_price": 228.70, "opened_on": "2026-01-22"},
        ],
        "watchlist": ["NVDA", "TSM", "SMH", "LLY"],
        "notifications_this_week": 2,
    },
    {
        "id": "u2", "name": "Giulia Ferrari", "email": "giulia.ferrari@example.com",
        "profile": {
            "capital": 40_000, "horizon": "Lungo (oltre 5 anni)", "currency": "EUR",
            "country": "Italia", "risk_profile": "Aggressivo",
            "markets": ["USA", "Asia", "Global"],
            "sectors": ["AI", "Tecnologia", "Energia"],
            "asset_classes": ["Azioni", "ETF", "Crypto"],
        },
        "channels": ["Telegram", "WhatsApp", "Push"],
        "positions": [
            {"ticker": "NVDA", "quantity": 40, "avg_price": 151.30, "opened_on": "2025-08-01"},
            {"ticker": "BTC-USD", "quantity": 0.12, "avg_price": 94_200.00, "opened_on": "2025-10-17"},
            {"ticker": "ETH-USD", "quantity": 2.5, "avg_price": 3_480.00, "opened_on": "2026-02-11"},
            {"ticker": "SMH", "quantity": 12, "avg_price": 291.80, "opened_on": "2026-04-08"},
            {"ticker": "9984.T", "quantity": 100, "avg_price": 11_900.00, "opened_on": "2026-06-19"},
        ],
        "watchlist": ["AMD", "SOL-USD", "TSM", "005930.KS"],
        "notifications_this_week": 1,
    },
    {
        "id": "u3", "name": "Alberto Conti", "email": "alberto.conti@example.com",
        "profile": {
            "capital": 250_000, "horizon": "Lungo (oltre 5 anni)", "currency": "EUR",
            "country": "Svizzera", "risk_profile": "Conservativo",
            "markets": ["Europa", "Global"],
            "sectors": ["Healthcare", "Finanza", "Consumer"],
            "asset_classes": ["Obbligazioni", "ETF", "Azioni"],
        },
        "channels": ["Email"],
        "positions": [
            {"ticker": "VWCE.DE", "quantity": 700, "avg_price": 118.60, "opened_on": "2024-11-05"},
            {"ticker": "IEAC.AS", "quantity": 500, "avg_price": 124.10, "opened_on": "2025-01-30"},
            {"ticker": "IEF", "quantity": 500, "avg_price": 94.80, "opened_on": "2025-03-18"},
            {"ticker": "MC.PA", "quantity": 20, "avg_price": 672.00, "opened_on": "2025-07-09"},
            {"ticker": "ISP.MI", "quantity": 6000, "avg_price": 4.21, "opened_on": "2025-05-14"},
        ],
        "watchlist": ["LQD", "EXS1.DE", "KO"],
        "notifications_this_week": 0,
    },
]

# Storico interazioni: input dell'apprendimento delle preferenze (BR-12).
# action: opened | ignored | saved | analyzed
INTERACTIONS = [
    ("u1", 2, "AMD", "AI", "opened"), ("u1", 5, "NVDA", "AI", "opened"),
    ("u1", 6, "SMH", "AI", "saved"), ("u1", 9, "KO", "Consumer", "ignored"),
    ("u1", 11, "TSM", "AI", "opened"), ("u1", 13, "JPM", "Finanza", "ignored"),
    ("u1", 16, "MSFT", "Tecnologia", "opened"), ("u1", 18, "XOM", "Energia", "ignored"),
    ("u1", 21, "SAP.DE", "Tecnologia", "analyzed"), ("u1", 24, "LLY", "Healthcare", "opened"),
    ("u1", 27, "UNH", "Healthcare", "ignored"), ("u1", 30, "AMD", "AI", "analyzed"),
    ("u2", 1, "SOL-USD", "Crypto", "opened"), ("u2", 3, "BTC-USD", "Crypto", "opened"),
    ("u2", 4, "NVDA", "AI", "opened"), ("u2", 8, "XOM", "Energia", "ignored"),
    ("u2", 12, "ETH-USD", "Crypto", "saved"), ("u2", 15, "TSM", "AI", "opened"),
    ("u2", 19, "SPY", "Diversificato", "ignored"), ("u2", 22, "SMH", "AI", "analyzed"),
    ("u3", 3, "IEAC.AS", "Obbligazionario", "opened"), ("u3", 7, "LQD", "Obbligazionario", "opened"),
    ("u3", 10, "NVDA", "AI", "ignored"), ("u3", 14, "VWCE.DE", "Diversificato", "saved"),
    ("u3", 20, "MC.PA", "Consumer", "opened"), ("u3", 26, "SOL-USD", "Crypto", "ignored"),
    ("u3", 29, "ISP.MI", "Finanza", "opened"),
]

ACTION_VALUE = {"opened": 1.0, "saved": 1.5, "analyzed": 1.3, "ignored": -0.6}


def interactions(user_id: str) -> list[dict]:
    return [{"date": (TODAY - timedelta(days=d)).isoformat(), "ticker": t,
             "sector": s, "action": a}
            for u, d, t, s, a in INTERACTIONS if u == user_id]


def learned_preferences(user_id: str) -> dict:
    """DEMO-10 (BR-12): affinità per settore calcolata sulle interazioni
    degli ultimi 30 giorni, con decadimento temporale. L'affinità non modifica
    l'Opportunity Score: agisce solo come priorità di presentazione, così il
    punteggio resta confrontabile tra utenti."""
    raw: dict[str, float] = {}
    for u, days, _t, sector, action in INTERACTIONS:
        if u != user_id:
            continue
        decay = 1.0 / (1 + days / 15)
        raw[sector] = raw.get(sector, 0.0) + ACTION_VALUE[action] * decay
    if not raw:
        return {"affinity": {}, "top_sectors": []}
    peak = max(abs(v) for v in raw.values()) or 1.0
    affinity = {s: round(max(-1.0, min(1.0, v / peak)), 3) for s, v in raw.items()}
    top = sorted(affinity.items(), key=lambda kv: -kv[1])[:3]
    return {"affinity": affinity, "top_sectors": [s for s, v in top if v > 0.25]}


def priority_boost(user_id: str, sector: str) -> float:
    """Moltiplicatore di priorità nell'ordinamento: 0,85 - 1,15."""
    aff = learned_preferences(user_id)["affinity"].get(sector, 0.0)
    return round(1 + 0.15 * aff, 4)
