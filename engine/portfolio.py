"""Portfolio Agent (BR-08, step 8 del workflow).

Monitora posizioni, prezzo medio di carico, performance, rischio complessivo e
concentrazione settoriale e genera alert automatici. Soglie e canali degli alert
non sono definiti nell'FDD (OP-05): quelle usate qui sono DEMO-13 e sono
raccolte in ALERT_RULES.
"""

from __future__ import annotations

from .indicators import max_drawdown
from .universe import FX_TO_EUR
from .users import RISK_CEILING

# Un ETF azionario globale al 40% non è una concentrazione e non espone a una
# singola società: gli alert di concentrazione valgono solo dove il rischio è
# davvero di un singolo emittente (parte di DEMO-13).
SINGLE_ISSUER_CLASSES = {"Azioni", "REIT", "Crypto", "Commodities"}
CONCENTRATION_EXCLUDED_SECTORS = {"Diversificato", "Obbligazionario"}

ALERT_RULES = {
    "loss_pct": -0.15,            # perdita sulla posizione
    "gain_pct": 0.25,             # utile da valutare per ribilanciamento
    "position_drawdown": -0.20,   # drawdown dal massimo dall'ingresso
    "position_weight": 0.25,      # peso di una singola posizione
    "sector_weight": 0.35,        # concentrazione settoriale
    "hhi": 0.25,                  # indice Herfindahl sull'allocazione
}

# DEMO-14 (OP-05): gli alert di portafoglio NON rientrano nel limite di 3
# notifiche settimanali di BR-06, che riguarda le opportunità. Sono inviati
# sui canali configurati dall'utente.
ALERTS_COUNT_IN_WEEKLY_LIMIT = False


def _close_on(asset: dict, when: str) -> float:
    """Chiusura del giorno indicato (o della prima seduta successiva)."""
    dates, closes = asset["series"]["date"], asset["series"]["close"]
    idx = next((i for i, d in enumerate(dates) if d >= when), 0)
    return round(closes[idx], 4)


def _since_entry(asset: dict, opened_on: str) -> tuple[float, float]:
    """Drawdown corrente dal massimo registrato dopo l'ingresso e massimo
    drawdown nello stesso periodo."""
    dates = asset["series"]["date"]
    closes = asset["series"]["close"]
    idx = next((i for i, d in enumerate(dates) if d >= opened_on), 0)
    window = closes[idx:] or closes[-1:]
    peak = max(window)
    return round(window[-1] / peak - 1, 4), round(max_drawdown(window), 4)


def evaluate(user: dict, assets: dict, analyses: dict) -> dict:
    """Valori convertiti nella valuta di riferimento del profilo (EUR nei
    profili demo) usando i cambi di universe.FX_TO_EUR."""
    ref = user["profile"]["currency"]
    ref_fx = FX_TO_EUR[ref]
    rows = []
    missing: list[str] = []
    for pos in user["positions"]:
        if pos["ticker"] not in assets:
            missing.append(pos["ticker"])
            continue
        a = assets[pos["ticker"]]
        an = analyses[pos["ticker"]]
        price = a["tech"]["price"]
        if not pos.get("avg_price"):
            # prezzo di carico assente: si usa la chiusura del giorno di acquisto
            pos = {**pos, "avg_price": _close_on(a, pos["opened_on"])}
        fx = a["fx_to_eur"] / ref_fx          # valuta di quotazione -> valuta profilo
        value = price * pos["quantity"] * fx
        cost = pos["avg_price"] * pos["quantity"] * fx
        dd_now, dd_max = _since_entry(a, pos["opened_on"])
        rows.append({
            "ticker": pos["ticker"], "name": a["name"], "asset_class": a["asset_class"],
            "sector": a["sector"], "market": a["market"], "currency": a["currency"],
            "ref_currency": ref, "fx": round(fx, 6),
            "quantity": pos["quantity"], "avg_price": pos["avg_price"],
            "price": price, "value": round(value, 2), "cost": round(cost, 2),
            "pl": round(value - cost, 2),
            "pl_pct": round(value / cost - 1, 4),
            "drawdown": dd_now, "max_drawdown": dd_max,
            "risk_score": an["scores"]["risk"], "risk_label": an["risk_label"],
            "opportunity_score": an["opportunity_score"],
            "rating": an["final_rating"],
            "opened_on": pos["opened_on"],
        })

    total_value = sum(r["value"] for r in rows)
    total_cost = sum(r["cost"] for r in rows)
    capital = user["profile"].get("capital")
    for r in rows:
        r["weight"] = round(r["value"] / total_value, 4) if total_value else 0.0

    def group(key):
        g: dict[str, float] = {}
        for r in rows:
            g[r[key]] = g.get(r[key], 0.0) + r["weight"]
        return {k: round(v, 4) for k, v in sorted(g.items(), key=lambda kv: -kv[1])}

    by_class, by_sector, by_market = group("asset_class"), group("sector"), group("market")
    hhi = round(sum(w ** 2 for w in (r["weight"] for r in rows)), 4)
    risk_score = round(sum(r["risk_score"] * r["weight"] for r in rows), 1) if rows else 0.0
    ceiling = RISK_CEILING[user["profile"]["risk_profile"]]

    alerts = []

    def alert(level, title, detail, ticker=None, kind=None, values=None):
        # `kind` e `values` servono allo strato in linguaggio semplice
        # (engine/plain.py), che riscrive l'alert senza riusare questo testo.
        alerts.append({"level": level, "title": title, "detail": detail,
                       "ticker": ticker, "kind": kind, "values": values or {},
                       "channels": user["channels"],
                       "counts_in_weekly_limit": ALERTS_COUNT_IN_WEEKLY_LIMIT})

    for r in rows:
        common = {"name": r["name"], "pl": r["pl"], "pl_pct": r["pl_pct"],
                  "weight": r["weight"], "price": r["price"], "avg_price": r["avg_price"],
                  "rating": r["rating"], "score": r["opportunity_score"],
                  "currency": r["ref_currency"], "drawdown": r["drawdown"],
                  "max_drawdown": r["max_drawdown"]}
        if r["pl_pct"] <= ALERT_RULES["loss_pct"]:
            alert("critical", f"{r['ticker']}: perdita {r['pl_pct'] * 100:.1f}%",
                  f"Prezzo {r['price']} contro un carico medio di {r['avg_price']}. "
                  f"Rating corrente {r['rating']}, Opportunity Score {r['opportunity_score']}.",
                  r["ticker"], "loss", common)
        elif r["pl_pct"] >= ALERT_RULES["gain_pct"]:
            alert("good", f"{r['ticker']}: utile {r['pl_pct'] * 100:+.1f}%",
                  f"Posizione in utile di {r['pl']:,.0f} {r['ref_currency']}; "
                  f"peso salito al {r['weight'] * 100:.1f}% del portafoglio.",
                  r["ticker"], "gain", common)
        if r["drawdown"] <= ALERT_RULES["position_drawdown"]:
            alert("warning", f"{r['ticker']}: drawdown {r['drawdown'] * 100:.1f}% dal massimo",
                  f"Ritracciamento dal massimo registrato dopo l'acquisto "
                  f"(massimo drawdown del periodo {r['max_drawdown'] * 100:.1f}%).",
                  r["ticker"], "drawdown", common)
        if r["weight"] >= ALERT_RULES["position_weight"] \
                and r["asset_class"] in SINGLE_ISSUER_CLASSES:
            alert("warning", f"{r['ticker']}: peso {r['weight'] * 100:.1f}%",
                  f"Singola posizione oltre la soglia del "
                  f"{ALERT_RULES['position_weight'] * 100:.0f}%.",
                  r["ticker"], "weight", common)

    for sector, w in by_sector.items():
        if w >= ALERT_RULES["sector_weight"] and sector not in CONCENTRATION_EXCLUDED_SECTORS:
            alert("warning", f"Concentrazione settoriale: {sector} al {w * 100:.1f}%",
                  f"Soglia di attenzione {ALERT_RULES['sector_weight'] * 100:.0f}%. "
                  f"Valutare una diversificazione.",
                  None, "sector", {"sector": sector, "weight": w})

    if risk_score > ceiling:
        alert("serious", f"Rischio di portafoglio {risk_score} sopra il profilo "
                         f"{user['profile']['risk_profile']} (max {ceiling})",
              "Media dei Risk Score delle posizioni pesata per il valore di mercato.",
              None, "portfolio_risk",
              {"risk": risk_score, "ceiling": ceiling,
               "profile": user["profile"]["risk_profile"]})

    return {
        "user_id": user["id"],
        "positions": sorted(rows, key=lambda r: -r["value"]),
        "total_value": round(total_value, 2),
        "total_cost": round(total_cost, 2),
        "pl": round(total_value - total_cost, 2),
        "pl_pct": round(total_value / total_cost - 1, 4) if total_cost else 0.0,
        # liquidità calcolabile solo se l'utente ha dichiarato un capitale
        "cash": round(capital - total_cost, 2) if capital else None,
        "allocation_by_class": by_class,
        "allocation_by_sector": by_sector,
        "allocation_by_market": by_market,
        "hhi": hhi,
        "missing_tickers": missing,
        "risk_score": risk_score,
        "risk_ceiling": ceiling,
        "alerts": alerts,
    }
