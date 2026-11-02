"""Il profilo di chi usa l'agente, letto da un file.

I tre clienti della demo servono a mostrare che la stessa analisi produce esiti
diversi per profili diversi. Per **usare** l'agente serve il proprio profilo: lo
si scrive in `profilo.json` nella cartella del progetto e il motore lo carica al
posto (o a fianco) dei clienti demo.

    python cli.py profilo-nuovo        # crea il file da compilare
    python cli.py agent me --real      # il ciclo sul proprio profilo

Il file resta sul disco e non viene mandato da nessuna parte. Con Gemini attivo,
al modello arrivano i dati dell'asset da analizzare, non il portafoglio.
"""

from __future__ import annotations

import json
from pathlib import Path

PROFILE_PATH = Path(__file__).resolve().parent.parent / "profilo.json"

TEMPLATE = {
    "id": "me",
    "name": "Il mio profilo",
    "first_name": "",
    "email": "",
    "profile": {
        "capital": None,
        "horizon": "Medio (3-5 anni)",
        "currency": "EUR",
        "country": "Italia",
        "risk_profile": "Bilanciato",
        "markets": ["USA", "Europa"],
        "sectors": ["Tecnologia", "AI", "Healthcare"],
        "asset_classes": ["Azioni", "ETF"],
    },
    "channels": ["Telegram"],
    "weekly_limit": 2,
    "positions": [
        {"ticker": "VWCE.DE", "quantity": 100, "avg_price": 120.0, "opened_on": "2025-01-15"},
        {"ticker": "MSFT", "quantity": 10, "avg_price": 400.0, "opened_on": "2025-06-01"},
    ],
    "watchlist": ["AMD", "NVDA", "SPY"],
    "notifications_this_week": 0,
    "_note": [
        "ticker = simbolo Yahoo Finance (AMD, ASML.AS, VWCE.DE, BTC-USD, GC=F...)",
        "avg_price = prezzo medio di carico nella valuta di quotazione dello strumento",
        "risk_profile = Conservativo | Bilanciato | Aggressivo",
        "markets = USA, Europa, Asia, Global · asset_classes = Azioni, ETF, Obbligazioni, Crypto",
        "settori ammessi: Tecnologia, AI, Healthcare, Finanza, Energia, Industriale, Consumer",
    ],
}

# `capital` non è obbligatorio: chi non vuole dichiararlo non deve. Senza
# capitale le percentuali vengono tradotte su una base neutra di 1.000 euro.
REQUIRED_PROFILE_KEYS = ("horizon", "currency", "country", "risk_profile",
                         "markets", "sectors", "asset_classes")
RISK_PROFILES = ("Conservativo", "Bilanciato", "Aggressivo")
# Domini ammessi: un valore scritto a mano fuori dominio azzererebbe il
# perimetro in silenzio, quindi va segnalato.
DOMAINS = {
    "markets": {"USA", "Europa", "Asia", "Global"},
    "sectors": {"Tecnologia", "AI", "Healthcare", "Finanza", "Energia", "Industriale",
                "Consumer", "Immobiliare"},
    "asset_classes": {"Azioni", "ETF", "Obbligazioni", "Crypto"},
}


def write_template(path: Path | None = None) -> Path:
    path = path or PROFILE_PATH
    path.write_text(json.dumps(TEMPLATE, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load(path: Path | None = None) -> tuple[dict | None, list[str]]:
    """Restituisce (utente, problemi). Un file sbagliato non fa cadere il ciclo:
    segnala che cosa manca e si continua con i profili demo."""
    path = path or PROFILE_PATH
    if not path.exists():
        return None, []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return None, [f"{path.name} non è un JSON valido: {e}"]

    problems: list[str] = []
    prof = data.get("profile") or {}
    for key in REQUIRED_PROFILE_KEYS:
        if key not in prof:
            problems.append(f"manca profile.{key}")
    if prof.get("risk_profile") not in RISK_PROFILES:
        problems.append(f"profile.risk_profile deve essere uno di {', '.join(RISK_PROFILES)}")
    cap = prof.get("capital")
    if cap is not None and (not isinstance(cap, (int, float)) or cap <= 0):
        problems.append("profile.capital, se presente, deve essere un numero positivo "
                        "(oppure null per non dichiararlo)")
    for field, allowed in DOMAINS.items():
        values = prof.get(field) or []
        if not isinstance(values, list):
            problems.append(f"profile.{field} deve essere un elenco")
            continue
        unknown = [v for v in values if v not in allowed]
        if unknown:
            problems.append(f"profile.{field}: valori non riconosciuti {unknown} "
                            f"(ammessi: {', '.join(sorted(allowed))})")
    for i, pos in enumerate(data.get("positions") or []):
        if not pos.get("ticker"):
            problems.append(f"positions[{i}]: manca il ticker")
        if not isinstance(pos.get("quantity"), (int, float)):
            problems.append(f"positions[{i}] ({pos.get('ticker')}): quantity deve essere un numero")
    if problems:
        return None, problems

    user = {
        "id": data.get("id") or "me",
        "name": data.get("name") or "Il mio profilo",
        "first_name": (data.get("first_name") or "").strip(),
        "email": data.get("email", ""),
        "profile": prof,
        "channels": data.get("channels") or ["Email"],
        "positions": data.get("positions") or [],
        "watchlist": data.get("watchlist") or [],
        "notifications_this_week": int(data.get("notifications_this_week") or 0),
        # il limite settimanale scelto in onboarding viaggia con il profilo
        "weekly_limit": int(data.get("weekly_limit") or 0) or None,
        "wants_portfolio": bool(data.get("wants_portfolio")),
        "answers": data.get("_risposte") or data.get("answers") or {},
        "from_file": True,
    }
    return user, []
