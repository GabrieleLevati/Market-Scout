"""Gli agenti specialistici (BR-03, step 3-4 del workflow).

Scostamento dall'FDD richiesto dal committente: **nessun consensus di analisti
umani**. L'Analyst Consensus Agent è sostituito dall'**AI Valuation Agent**, che
stima il valore con il modello proprietario di `valuation.py` e lo fa giudicare
da Gemini. Il peso del 25% resta dov'era (BR-04), cambia chi produce il numero.

Chi fa che cosa, quando c'è la chiave Gemini (`--live`):

| Agente | Nucleo deterministico | Ruolo di Gemini |
|---|---|---|
| Fundamental | indici di bilancio normalizzati | revisione del punteggio, +/-10 punti motivati |
| Technical | RSI, MACD, EMA, Bollinger, ADX, volumi | revisione del punteggio, +/-10 punti motivati |
| AI Valuation | valore stimato da utili e multiplo giusto | giudizio sulla stima e punteggio |
| News & Sentiment | polarità delle notizie | lettura delle notizie e punteggio |
| Risk | volatilità, drawdown, leva, liquidità | revisione del punteggio, +/-10 punti motivati |

I numeri calcolabili restano calcolati: un modello linguistico non deve fare
aritmetica che deve essere riproducibile e verificabile. Il modello fa il
lavoro di giudizio — leggere le notizie, pesare la stima di valore, scrivere il
perché — e ogni sua uscita passa da una validazione prima di entrare nei conti.
Senza chiave, tutti gli agenti restano sul nucleo deterministico e lo dichiarano
nel campo `source`.


Ogni agente è una funzione pura `asset -> {score, drivers, notes}`: lo score è
un intero 0-100 (A-04) e i `drivers` espongono il contributo di ogni metrica,
così la notifica può citare i "motivi principali" senza inventarli.

"""

from __future__ import annotations

import math

from . import llm as llm_mod
from .valuation import EQUITY_LIKE, fair_value

MAX_REVIEW_ADJUSTMENT = 10          # quanto Gemini può spostare un punteggio calcolato
MAX_VALUE_DEVIATION = 0.25          # quanto può scostarsi dalla stima del modello


def lin(x: float, lo: float, hi: float) -> float:
    """Normalizzazione lineare su 0-100 con clamp (funziona anche se lo > hi)."""
    if hi == lo:
        return 50.0
    v = (x - lo) / (hi - lo) * 100
    return max(0.0, min(100.0, v))


def band(x: float, best_lo: float, best_hi: float, lo: float, hi: float) -> float:
    """100 nella fascia ottimale, decrescente verso gli estremi."""
    if best_lo <= x <= best_hi:
        return 100.0
    if x < best_lo:
        return lin(x, lo, best_lo)
    return lin(x, hi, best_hi)


def _combine(parts: list[tuple[str, float, float, str]]) -> tuple[int, list[dict]]:
    """parts = [(label, score_0_100, peso, valore_leggibile)] -> media pesata."""
    tot = sum(p[2] for p in parts) or 1.0
    score = sum(p[1] * p[2] for p in parts) / tot
    drivers = [{"label": p[0], "score": round(p[1]), "weight": round(p[2] / tot, 3),
                "value": p[3]} for p in parts]
    drivers.sort(key=lambda d: -d["weight"] * d["score"])
    return int(round(score)), drivers


def pct(x: float, digits: int = 1) -> str:
    return f"{x * 100:+.{digits}f}%"


# --------------------------------------------------------------------------
# Fundamental Analysis Agent -> Fundamental Score
# --------------------------------------------------------------------------
def fundamental_agent(a: dict, llm=None) -> dict:
    f, acls = a["fundamentals"], a["asset_class"]
    if str(f.get("basis", "")).startswith("solo prezzo"):
        # Sui dati reali ETF, obbligazioni, crypto e materie prime non hanno
        # bilanci accessibili: il componente resta vuoto e il peso si
        # ridistribuisce (DEMO-02), invece di inventare un punteggio.
        return {"agent": "Fundamental Analysis Agent", "score": None, "drivers": [],
                "note": "Nessun dato di bilancio disponibile per questo strumento: "
                        "servirebbe un contratto dati (OP-08).",
                "basis": f.get("basis", ""), "source": "dato non disponibile"}
    if acls in EQUITY_LIKE:
        # Sui dati reali una voce può mancare: si esclude dalla media e si
        # dichiara, invece di assumere un valore.
        missing: list[str] = []

        def metric(label, key, lo, hi, weight, fmt=pct):
            v = f.get(key)
            if v is None:
                missing.append(label)
                return None
            return (label, lin(v, lo, hi), weight, fmt(v))

        parts = [p for p in [
            metric("Crescita ricavi", "revenue_growth", 0.0, 0.30, 0.20),
            metric("Crescita EPS", "eps_growth", 0.0, 0.35, 0.15),
            metric("FCF margin", "fcf_margin", 0.0, 0.28, 0.15),
            metric("ROE", "roe", 0.05, 0.35, 0.15),
            metric("ROIC", "roic", 0.03, 0.28, 0.15),
            metric("Margine netto", "net_margin", 0.0, 0.30, 0.10),
            metric("Debt/Equity", "debt_to_equity", 2.2, 0.2, 0.10,
                   lambda v: f"{v:.2f}x"),
        ] if p]
        if not parts:
            return {"agent": "Fundamental Analysis Agent", "score": None, "drivers": [],
                    "note": "Nessuna voce di bilancio utilizzabile.",
                    "basis": f.get("basis", ""), "source": "dato non disponibile"}
        note = ("Set completo da bilancio." if not missing
                else f"Voci non disponibili, escluse dalla media: {', '.join(missing)}.")
    elif acls == "ETF":
        parts = [
            ("Crescita utili indice", lin(f["index_earnings_growth"], 0.0, 0.18), 0.40, pct(f["index_earnings_growth"])),
            ("TER", lin(f["expense_ratio"], 0.006, 0.0003), 0.25, f"{f['expense_ratio'] * 100:.2f}%"),
            ("AUM", lin(math.log10(max(f["aum_usd_m"], 1)), 2.7, 4.7), 0.15,
             f"{f['aum_usd_m']:,}M$"),
            ("Tracking difference", lin(abs(f["tracking_difference"]), 0.0012, 0.0), 0.20,
             f"{f['tracking_difference'] * 100:+.3f}%"),
        ]
        note = "Nessun bilancio: set proxy ETF (OP-10)."
    elif acls == "Obbligazioni":
        parts = [
            ("Yield to maturity", lin(f["yield_to_maturity"], 0.015, 0.070), 0.35, pct(f["yield_to_maturity"], 2)),
            ("Rendimento reale", lin(f["real_yield"], -0.005, 0.020), 0.25, pct(f["real_yield"], 2)),
            ("Qualità creditizia", 85.0 if f["credit_quality"] == "AAA-AA" else 60.0, 0.25, f["credit_quality"]),
            ("Duration", lin(f["duration"], 18, 2), 0.15, f"{f['duration']:.1f} anni"),
        ]
        note = "Nessun bilancio: set proxy obbligazionario (OP-10)."
    elif acls == "Crypto":
        parts = [
            ("Indirizzi attivi 90g", lin(f["active_addresses_growth_90d"], -0.10, 0.50), 0.30,
             pct(f["active_addresses_growth_90d"])),
            ("Attività sviluppo", lin(f["developer_activity_index"], 20, 95), 0.25,
             f"{f['developer_activity_index']:.0f}/100"),
            ("Crescita fee di rete", lin(f["fees_growth_90d"], -0.20, 0.80), 0.25, pct(f["fees_growth_90d"])),
            ("Inflazione supply", lin(f["supply_inflation"], 0.06, 0.0), 0.20, pct(f["supply_inflation"], 2)),
        ]
        note = "Nessun bilancio: set proxy on-chain (OP-10)."
    else:
        parts = [
            ("Domanda", lin(f["demand_proxy_growth"], -0.05, 0.20), 0.35, pct(f["demand_proxy_growth"])),
            ("Scorte 90g", lin(f["inventory_trend_90d"], 0.20, -0.20), 0.30, pct(f["inventory_trend_90d"])),
            ("Dollaro 90g", lin(f["dollar_index_trend_90d"], 0.05, -0.05), 0.20, pct(f["dollar_index_trend_90d"])),
            ("Tassi reali", lin(f["real_yield_context"], 0.020, -0.005), 0.15, pct(f["real_yield_context"], 2)),
        ]
        note = "Nessun bilancio: set proxy commodity (OP-10)."

    score, drivers = _combine(parts)
    return {"agent": "Fundamental Analysis Agent", "score": score, "drivers": drivers,
            "note": note, "basis": a["fundamentals"]["basis"],
            "source": "modello quantitativo"}


# --------------------------------------------------------------------------
# Technical Analysis Agent -> Technical Score
# --------------------------------------------------------------------------
def technical_agent(a: dict, llm=None) -> dict:
    t = a["tech"]
    trend_score = (50 if t["above_ema50"] else 0) + (25 if t["above_ema200"] else 0) + \
                  (15 if t["golden_cross"] else 0)
    parts = [
        ("Trend su EMA50/EMA200", float(trend_score), 0.30,
         ("sopra" if t["above_ema50"] else "sotto") + " EMA50, " +
         ("sopra" if t["above_ema200"] else "sotto") + " EMA200"),
        ("RSI", band(t["rsi"], 50, 72, 22, 92), 0.15, f"{t['rsi']:.0f}"),
        ("MACD", 0.6 * lin(t["macd_line_pct"], -1.0, 1.5) +
                 0.4 * (100.0 if t["macd_positive"] else 20.0), 0.15,
         f"linea {t['macd_line_pct']:+.2f}% del prezzo, istogramma " +
         ("positivo" if t["macd_positive"] else "negativo")),
        ("Posizione in Bollinger", band(t["bb_position"], 0.55, 0.95, 0.0, 1.25), 0.10,
         f"{t['bb_position']:.2f}"),
        ("ADX", lin(t["adx"], 12, 40), 0.15, f"{t['adx']:.0f}"),
        ("Volumi vs media 20g", lin(t["volume_ratio"], 0.5, 1.5), 0.15, f"{t['volume_ratio']:.2f}x"),
    ]
    score, drivers = _combine(parts)
    if t["breakout"] and t["volume_ratio"] > 1.5:
        score = min(100, score + 6)  # conferma di rottura con volumi (DEMO-03)
    return {"agent": "Technical Analysis Agent", "score": score, "drivers": drivers,
            "source": "modello quantitativo",
            "note": "Breakout confermato dai volumi: +6 punti." if t["breakout"] and t["volume_ratio"] > 1.5 else ""}


# --------------------------------------------------------------------------
# Analyst Consensus Agent -> Analyst Score
# --------------------------------------------------------------------------
VALUATION_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "fair_value": {"type": "NUMBER"},
        "score": {"type": "INTEGER"},
        "confidence": {"type": "INTEGER"},
        "reasoning": {"type": "STRING"},
        "drivers": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["fair_value", "score", "confidence", "reasoning", "drivers"],
}


def _valuation_prompt(a: dict, v: dict) -> str:
    f = a["fundamentals"]
    if a["asset_class"] in EQUITY_LIKE:
        facts = (f"crescita ricavi {pct(f['revenue_growth'])}, crescita utile per azione "
                 f"{pct(f['eps_growth'])}, margine netto {pct(f['net_margin'])}, "
                 f"margine di cassa {pct(f['fcf_margin'])}, ROE {pct(f['roe'])}, "
                 f"ROIC {pct(f['roic'])}, debito/patrimonio {f['debt_to_equity']:.2f}x, "
                 f"multiplo sugli utili pagato dal mercato {f['pe']:.1f}x, "
                 f"revisione della guidance aziendale negli ultimi 30 giorni "
                 f"{pct(f.get('guidance_change_30d', 0.0))}")
    else:
        facts = ", ".join(f"{k.replace('_', ' ')}: {val}" for k, val in f.items()
                          if k != "basis" and not isinstance(val, str))
    t = a["tech"]
    return (
        f"Valuta {a['name']} ({a['ticker']}), {a['asset_class']} del mercato {a['market']}, "
        f"settore {a['sector']}.\n"
        f"Prezzo attuale: {t['price']} {a['currency']}. Performance: 1 mese "
        f"{pct(t['perf_1m'])}, 3 mesi {pct(t['perf_3m'])}, 6 mesi {pct(t['perf_6m'])}. "
        f"Volatilità annualizzata {pct(t['volatility'], 0)}.\n"
        f"Dati di base ({f['basis']}): {facts}.\n"
        f"Stima del modello interno: valore {v['value']} {a['currency']} "
        f"(metodo: {v['method']}), scostamento dal prezzo {pct(v['upside'])}, "
        f"revisione della stima negli ultimi 30 giorni {pct(v['revision_30d'])}, "
        f"confidenza sui dati {v['confidence']}/100.\n\n"
        f"Compito: dì se la stima di valore è ragionevole sui soli dati forniti. "
        f"Restituisci:\n"
        f"- fair_value: il valore per unità che ritieni corretto, in {a['currency']}, "
        f"entro il {int(MAX_VALUE_DEVIATION * 100)}% dalla stima del modello;\n"
        f"- score: 0-100, quanto è attraente il rapporto tra prezzo e valore oggi "
        f"(50 = prezzo giusto, oltre 75 = chiaramente sotto il valore);\n"
        f"- confidence: 0-100, quanta fiducia meriti la stima dati questi numeri;\n"
        f"- reasoning: una frase in italiano, massimo 240 caratteri, senza gergo;\n"
        f"- drivers: 2 o 3 motivi brevi, ciascuno con il numero che lo sostiene."
    )


def valuation_agent(a: dict, llm=None) -> dict:
    """AI Valuation Agent: stima il valore e quanto il prezzo se ne discosta.
    Sostituisce l'Analyst Consensus Agent dell'FDD: nessun rating e nessun
    target price di analisti umani entra nel sistema."""
    v = a.get("valuation") or fair_value(a)
    if v.get("valuable") is False:
        return {"agent": "AI Valuation Agent", "score": None, "drivers": v["drivers"],
                "note": v["method"] + ": questo strumento viene monitorato ma non proposto.",
                "source": "dato non disponibile", "fair_value": v["value"],
                "confidence": v["confidence"], "model_value": v["value"],
                "method": v["method"]}
    parts = [
        ("Prezzo contro valore stimato", lin(v["upside"], 0.0, 0.28), 0.60, pct(v["upside"])),
        ("Revisione della stima (30g)", lin(v["revision_30d"], -0.02, 0.08), 0.25,
         pct(v["revision_30d"])),
        ("Confidenza sui dati", float(v["confidence"]), 0.15, f"{v['confidence']}/100"),
    ]
    score, drivers = _combine(parts)
    out = {
        "agent": "AI Valuation Agent",
        "score": score,
        "drivers": drivers + [{"label": d["label"], "score": None, "weight": 0.0,
                               "value": str(d["value"])} for d in v["drivers"]],
        "note": (f"Valore stimato {v['value']} {a['currency']} ({pct(v['upside'])} dal prezzo), "
                 f"metodo: {v['method']}. Nessun target price di analisti."),
        "source": "modello quantitativo",
        "fair_value": v["value"],
        "confidence": v["confidence"],
        "model_value": v["value"],
        "method": v["method"],
    }

    if llm is not None and (llm.enabled or llm.use_cache):
        data = llm.generate_json(_valuation_prompt(a, v), VALUATION_SCHEMA,
                                cache_key=f"valuation|{a['ticker']}|{v['value']}")
        if data:
            lo = v["value"] * (1 - MAX_VALUE_DEVIATION)
            hi = v["value"] * (1 + MAX_VALUE_DEVIATION)
            ai_value = llm_mod.num(data.get("fair_value"), lo, hi)
            ai_score = llm_mod.score_0_100(data.get("score"))
            ai_conf = llm_mod.score_0_100(data.get("confidence"))
            reasoning = llm_mod.text(data.get("reasoning"), 260)
            if ai_value is not None and ai_score is not None:
                upside = ai_value / a["tech"]["price"] - 1
                out.update({
                    "score": ai_score,
                    "fair_value": round(ai_value, 2),
                    "confidence": ai_conf if ai_conf is not None else v["confidence"],
                    "source": f"Gemini ({llm.model})",
                    "note": (f"Valore stimato dall'AI {round(ai_value, 2)} {a['currency']} "
                             f"({pct(upside)} dal prezzo); il modello quantitativo diceva "
                             f"{v['value']}. {reasoning}"),
                    "ai_reasoning": reasoning,
                    "ai_drivers": llm_mod.str_list(data.get("drivers"), 3, 160),
                })
            else:
                out["note"] += " Risposta del modello scartata dalla validazione."
    return out


# --------------------------------------------------------------------------
# News & Sentiment Agent -> Sentiment Score (in produzione: LLM, OP-07)
# --------------------------------------------------------------------------
SENTIMENT_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "score": {"type": "INTEGER"},
        "summary": {"type": "STRING"},
        "drivers": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["score", "summary", "drivers"],
}


def _sentiment_prompt(a: dict) -> str:
    lines = "\n".join(f"- {n['date']} ({n['source']}): {n['headline']}" for n in a["news"])
    e = a["earnings"]
    extra = ""
    if e.get("coverage") and e.get("basis") == "crescita anno su anno":
        extra = (f"\nUltimo trimestre pubblicato ({e.get('report_date')}): ricavi "
                 f"{pct(e.get('revenue_yoy') or 0)} e utile per azione "
                 f"{pct(e.get('eps_yoy') or 0)} rispetto allo stesso trimestre dell'anno "
                 f"precedente.")
    elif e.get("coverage"):
        extra = (f"\nUltimo bilancio trimestrale ({e.get('report_date')}): utile per azione "
                 f"{e.get('eps_actual')} contro {e.get('eps_estimate')} previsto "
                 f"({pct(e.get('eps_surprise') or 0)}), ricavi "
                 f"{pct(e.get('revenue_surprise') or 0)} rispetto alle attese.")
    return (
        f"Notizie sulle ultime due settimane su {a['name']} ({a['ticker']}, "
        f"{a['asset_class']}, settore {a['sector']}):\n{lines}{extra}\n\n"
        f"Compito: leggi queste notizie e dammi il clima informativo sull'asset. "
        f"Restituisci:\n"
        f"- score: 0-100 (50 = neutro, sotto 35 = clima negativo, sopra 70 = positivo);\n"
        f"- summary: una frase in italiano, massimo 200 caratteri, che un cliente senza "
        f"competenze finanziarie capisca;\n"
        f"- drivers: 2 o 3 punti brevi, ciascuno riferito a una notizia dell'elenco.\n"
        f"Importante: i titoli arrivano da una ricerca per nome e alcuni possono riguardare "
        f"altre società o essere generici. Scarta quelli non pertinenti, dillo nel summary "
        f"e abbassa il peso che dai al resto. Non aggiungere notizie che non sono nell'elenco."
    )


def sentiment_agent(a: dict, llm=None) -> dict:
    """Legge il clima informativo. La polarità di un titolo non è un dato: è un
    giudizio. Sui dati sintetici arriva col generatore, sui dati reali la
    produce il modello: senza modello il componente resta vuoto e lo dichiara,
    invece di inventare un punteggio neutro."""
    news = a["news"]
    scored = [n for n in news if isinstance(n.get("polarity"), (int, float))]
    e = a["earnings"]
    has_earnings = e.get("coverage") and isinstance(e.get("eps_surprise"), (int, float))
    can_ask = llm is not None and (llm.enabled or llm.use_cache)

    if not news:
        return {"agent": "News & Sentiment Agent", "score": None, "drivers": [],
                "note": "Nessuna notizia trovata su questo strumento nel periodo.",
                "source": "nessun dato", "headlines": []}

    # Prima il modello, quando c'è: è il suo lavoro.
    if can_ask:
        data = llm.generate_json(_sentiment_prompt(a), SENTIMENT_SCHEMA,
                                 cache_key=f"sentiment|{a['ticker']}|{len(news)}|"
                                           f"{news[0]['date']}")
        if data:
            ai_score = llm_mod.score_0_100(data.get("score"))
            summary = llm_mod.text(data.get("summary"), 220)
            if ai_score is not None and summary:
                return {"agent": "News & Sentiment Agent", "score": ai_score,
                        "drivers": [], "note": summary,
                        "source": f"Gemini ({llm.model})",
                        "ai_drivers": llm_mod.str_list(data.get("drivers"), 3, 160),
                        "headlines": news}

    if not scored:
        return {"agent": "News & Sentiment Agent", "score": None, "drivers": [],
                "note": f"{len(news)} notizie raccolte ma non lette: il giudizio sulle "
                        f"notizie lo produce il modello linguistico (usa --live).",
                "source": "da leggere con il modello", "headlines": news}

    weights = [1.0 / (1 + i * 0.4) for i in range(len(scored))]
    avg = sum(n["polarity"] * w for n, w in zip(scored, weights)) / sum(weights)
    parts = [("Polarità news 14g", lin(avg, -0.5, 0.55), 0.75, f"{avg:+.2f}"),
             ("Copertura (n. news)", lin(len(news), 0, 6), 0.10, f"{len(news)} notizie")]
    if has_earnings:
        parts.append(("Crescita ultimi conti", lin(e["eps_surprise"], -0.05, 0.12), 0.15,
                      f"utile {pct(e['eps_surprise'])}"))
    score, drivers = _combine(parts)
    top = max(scored, key=lambda n: abs(n["polarity"]))
    return {"agent": "News & Sentiment Agent", "score": score, "drivers": drivers,
            "note": f"Titolo più rilevante: \"{top['headline']}\" ({top['source']}).",
            "source": "modello quantitativo", "headlines": news}


# --------------------------------------------------------------------------
# Revisione AI dei punteggi calcolati (fondamentale, tecnico, rischio)
# --------------------------------------------------------------------------
REVIEW_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "fundamental_adjustment": {"type": "NUMBER"},
        "technical_adjustment": {"type": "NUMBER"},
        "risk_adjustment": {"type": "NUMBER"},
        "reasoning": {"type": "STRING"},
    },
    "required": ["fundamental_adjustment", "technical_adjustment",
                 "risk_adjustment", "reasoning"],
}


def _review_prompt(a: dict, res: dict) -> str:
    def lines(key):
        return "; ".join(f"{d['label']} {d['value']} (punteggio {d['score']})"
                         for d in res[key]["drivers"][:6] if d.get("score") is not None)
    return (
        f"{a['name']} ({a['ticker']}), {a['asset_class']} del mercato {a['market']}.\n"
        f"Punteggi calcolati dal motore e metriche che li producono:\n"
        f"- Fondamentale {res['fundamental']['score']}/100: {lines('fundamental')}\n"
        f"- Tecnico {res['technical']['score']}/100: {lines('technical')}\n"
        f"- Rischio {res['risk']['score']}/100 (alto = rischioso): {lines('risk')}\n\n"
        f"Compito: i punteggi sono calcolati con pesi fissi e possono perdere il quadro "
        f"d'insieme. Proponi una correzione per ciascuno, da -{MAX_REVIEW_ADJUSTMENT} a "
        f"+{MAX_REVIEW_ADJUSTMENT} punti, solo se i dati la giustificano (altrimenti 0), "
        f"e una riga di spiegazione in italiano. Il rischio va alzato se vedi fragilità "
        f"che le metriche non catturano."
    )


def ai_review(a: dict, res: dict, llm=None) -> dict | None:
    """Una sola chiamata per asset: Gemini rivede i tre punteggi calcolabili
    entro un limite stretto e motiva. Il limite serve a tenere il sistema
    auditabile: il modello non può ribaltare un calcolo, solo correggerlo."""
    if llm is None or not (llm.enabled or llm.use_cache):
        return None
    key = (f"review|{a['ticker']}|{res['fundamental']['score']}|"
           f"{res['technical']['score']}|{res['risk']['score']}")
    data = llm.generate_json(_review_prompt(a, res), REVIEW_SCHEMA, cache_key=key)
    if not data:
        return None
    m = MAX_REVIEW_ADJUSTMENT
    adj = {
        "fundamental": llm_mod.num(data.get("fundamental_adjustment"), -m, m, 0.0),
        "technical": llm_mod.num(data.get("technical_adjustment"), -m, m, 0.0),
        "risk": llm_mod.num(data.get("risk_adjustment"), -m, m, 0.0),
    }
    reasoning = llm_mod.text(data.get("reasoning"), 300)
    if not reasoning or not any(abs(v) >= 0.5 for v in adj.values()):
        return {"adjustments": {k: 0 for k in adj}, "reasoning": reasoning,
                "source": f"Gemini ({llm.model})"}
    return {"adjustments": {k: int(round(v)) for k, v in adj.items()},
            "reasoning": reasoning, "source": f"Gemini ({llm.model})"}


# --------------------------------------------------------------------------
# Risk Agent -> Risk Score (alto = rischio alto, S-04)
# --------------------------------------------------------------------------
SIZE_RISK = {"Mega cap": 15, "Large cap": 30, "Mid cap": 55, "ETF": 25,
             "Governativo": 10, "Corporate IG": 20, "Emerging": 55,
             "Metalli preziosi": 35, "Metalli industriali": 50, "Energia": 60,
             "Logistica": 35, "Retail": 45, "Residenziale": 45}
CLASS_RISK = {"Azioni": 40, "ETF": 25, "Obbligazioni": 15, "Crypto": 85,
              "Commodities": 55, "REIT": 45}


def risk_agent(a: dict, llm=None) -> dict:
    t, f = a["tech"], a["fundamentals"]
    parts = [
        ("Volatilità annualizzata", lin(t["volatility"], 0.08, 0.75), 0.35, pct(t["volatility"], 0)),
        ("Max drawdown 15 mesi", lin(t["max_drawdown"], 0.0, -0.50), 0.20, pct(t["max_drawdown"], 0)),
        ("Liquidità/dimensione", float(SIZE_RISK.get(a["size"], 45)), 0.10, a["size"]),
        ("Rischio di asset class", float(CLASS_RISK.get(a["asset_class"], 40)), 0.10, a["asset_class"]),
    ]
    if a["asset_class"] in EQUITY_LIKE:
        if f.get("debt_to_equity") is not None:
            parts.append(("Leva finanziaria", lin(f["debt_to_equity"], 0.2, 2.5), 0.15,
                          f"{f['debt_to_equity']:.2f}x"))
        if f.get("pe") is not None:
            parts.append(("Valutazione (P/E)", lin(f["pe"], 10, 60), 0.10, f"{f['pe']:.0f}x"))
    elif a["asset_class"] == "Obbligazioni" and f.get("duration") is not None:
        parts.append(("Duration", lin(f["duration"], 2, 18), 0.25, f"{f['duration']:.1f} anni"))
    score, drivers = _combine(parts)
    return {"agent": "Risk Agent", "score": score, "drivers": drivers,
            "note": "Scala 0-100, valore alto = rischio alto (S-04).",
            "source": "modello quantitativo", "label": risk_label(score)}


def risk_label(score: int) -> str:
    """DEMO-01 (OP-12): corrispondenza Risk Score -> etichetta di rischio."""
    if score <= 20:
        return "Basso"
    if score <= 45:
        return "Moderato"
    if score <= 70:
        return "Alto"
    return "Molto alto"


AGENTS = [fundamental_agent, technical_agent, valuation_agent, sentiment_agent, risk_agent]
