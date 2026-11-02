"""Motore di scoring (BR-04, step 5 del workflow).

Pesi dell'FDD, con un solo cambio di titolare: Fundamental 30%, Technical 20%,
**AI Valuation 25%** (al posto di Analyst Consensus), Sentiment 15%, Risk 10%.
Il Risk Score entra invertito come (100 - Risk) secondo A-05.

Effetto collaterale utile del cambio: con la valutazione fatta in casa ogni
asset class ha tutti e cinque i componenti, anche crypto e commodities, che con
il consensus degli analisti restavano senza copertura (era OP-10). La
ridistribuzione dei pesi resta come rete di sicurezza, ma in pratica non scatta
più.
"""

from __future__ import annotations

from .agents import (ai_review, fundamental_agent, risk_agent, risk_label,
                     sentiment_agent, technical_agent, valuation_agent)

WEIGHTS = {"fundamental": 0.30, "technical": 0.20, "valuation": 0.25,
           "sentiment": 0.15, "risk": 0.10}

COMPONENT_LABELS = {"fundamental": "Conti e bilancio", "technical": "Andamento del prezzo",
                    "valuation": "Prezzo contro valore", "sentiment": "Notizie",
                    "risk": "Rischio"}

BANDS = [(90, 100, "Opportunità eccezionale"), (80, 89, "Opportunità forte"),
         (70, 79, "Da monitorare"), (0, 69, "Nessuna azione")]

REVIEWABLE = ("fundamental", "technical", "risk")


def classify(score: int) -> str:
    for lo, hi, label in BANDS:
        if lo <= score <= hi:
            return label
    return "Nessuna azione"


def final_rating(opportunity: int, risk: int) -> str:
    """DEMO-04 (OP-12): criterio di assegnazione della valutazione finale.
    Fasce sull'Opportunity Score, con un gradino di prudenza se il rischio è
    molto alto."""
    ladder = ["Strong Sell", "Sell", "Hold", "Buy", "Strong Buy"]
    idx = 4 if opportunity >= 85 else 3 if opportunity >= 75 else \
        2 if opportunity >= 55 else 1 if opportunity >= 40 else 0
    if risk > 70 and idx > 0:
        idx -= 1
    return ladder[idx]


def operational_plan(asset: dict, risk: int, fair_value: float) -> dict:
    """DEMO-05 (OP-12): calcolo di ingresso, stop loss e target.
    Ingresso: [prezzo - 0,6 ATR ; prezzo + 0,2 ATR].
    Stop loss: prezzo - k x ATR, con k funzione del livello di rischio.
    Target: il valore stimato dall'AI Valuation Agent (non più un target price
    di analisti)."""
    t = asset["tech"]
    price = t["price"]
    atr = max(t["atr"], price * 0.005)
    k = {"Basso": 2.0, "Moderato": 2.5, "Alto": 3.0, "Molto alto": 3.5}[risk_label(risk)]
    target = round(fair_value, 2)
    stop = round(max(price - k * atr, price * 0.80), 2)
    return {
        "entry_low": round(price - 0.6 * atr, 2),
        "entry_high": round(price + 0.2 * atr, 2),
        "stop_loss": stop,
        "target": target,
        "atr": atr,
        "risk_reward": round((target - price) / max(price - stop, 1e-9), 2),
        "downside_to_stop": round(stop / price - 1, 4),
        "upside_to_target": round(target / price - 1, 4),
    }


def analyze_asset(asset: dict, llm=None) -> dict:
    """Esegue i cinque agenti e calcola l'Opportunity Score. Con `llm` attivo,
    valutazione e sentiment li produce Gemini e i tre punteggi calcolati passano
    dalla sua revisione (massimo ±10 punti, motivata)."""
    res = {
        "fundamental": fundamental_agent(asset),
        "technical": technical_agent(asset),
        "valuation": valuation_agent(asset, llm),
        "sentiment": sentiment_agent(asset, llm),
        "risk": risk_agent(asset),
    }

    review = ai_review(asset, res, llm)
    if review:
        for key in REVIEWABLE:
            delta = review["adjustments"].get(key, 0)
            if delta:
                before = res[key]["score"]
                res[key]["score"] = max(0, min(100, before + delta))
                res[key]["ai_adjustment"] = delta
                res[key]["source"] = review["source"]
                res[key]["note"] = (f"{res[key]['note']} Revisione AI {delta:+d} punti "
                                    f"(da {before}): {review['reasoning']}").strip()

    scores = {k: v["score"] for k, v in res.items()}

    # DEMO-02 (OP-10): se un componente non è calcolabile per l'asset class il
    # suo peso viene ridistribuito in proporzione sui componenti disponibili.
    available = {k: w for k, w in WEIGHTS.items() if scores.get(k) is not None}
    norm = sum(available.values())
    contributions = []
    total = 0.0
    for key, w in available.items():
        wn = w / norm
        value = (100 - scores["risk"]) if key == "risk" else scores[key]
        total += value * wn
        contributions.append({
            "component": key,
            "label": COMPONENT_LABELS[key],
            "score": scores[key],
            "effective_value": round(value, 1),
            "weight": round(wn, 4),
            "points": round(value * wn, 2),
        })
    opportunity = int(round(total))
    redistributed = [k for k in WEIGHTS if scores.get(k) is None]

    return {
        "ticker": asset["ticker"],
        "scores": scores,
        "agents": res,
        "opportunity_score": opportunity,
        "classification": classify(opportunity),
        "risk_label": risk_label(scores["risk"]),
        "contributions": contributions,
        "weights_redistributed": redistributed,
        "final_rating": final_rating(opportunity, scores["risk"]),
        "plan": operational_plan(asset, scores["risk"], res["valuation"]["fair_value"]),
        "ai_review": review,
        "ai_sources": {k: v.get("source", "modello quantitativo") for k, v in res.items()},
    }
