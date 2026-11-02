"""Chief Investment Officer Agent: sintesi, report on demand e scenari
(BR-03, BR-09, BR-11, step 9 del workflow).

La sintesi finale è il punto in cui l'FDD prevede il provider LLM: con la chiave
Gemini l'Executive Summary lo scrive il modello, a partire dagli stessi numeri
che il template userebbe, e passa da una validazione (lunghezza, presenza del
testo) prima di entrare nel report. Senza chiave resta il template
deterministico, dichiarato nel campo `narrative_engine`.

Nel report non c'è nessun "target price degli analisti": il prezzo obiettivo è
la stima dell'AI Valuation Agent, con il suo metodo e la sua confidenza.
"""

from __future__ import annotations

from . import llm as llm_mod
from .indicators import ema
from .universe import TODAY

TEMPLATE_ENGINE = "template deterministico (nessuna chiamata al modello)"

SCENARIO_RATIONALE = {
    "Azioni": ("Trigger confermati, esecuzione sui risultati trimestrali e multipli in espansione.",
               "Deterioramento del momentum e compressione dei multipli, in linea con la volatilità storica."),
    "REIT": ("Canoni in crescita e rivalutazione del portafoglio con tassi in discesa.",
             "Sfitto in aumento e costo del debito più alto, con svalutazioni di portafoglio."),
    "ETF": ("Trend dell'indice sottostante confermato e flussi netti in ingresso.",
            "Correzione dell'indice sottostante in linea con la volatilità storica."),
    "Obbligazioni": ("Discesa dei rendimenti di mercato: la duration lavora a favore.",
                     "Risalita dei rendimenti e allargamento degli spread di credito."),
    "Crypto": ("Afflussi sugli ETP e crescita dell'attività di rete.",
               "Deflussi e contrazione della liquidità, in linea con la volatilità storica."),
    "Commodities": ("Offerta sotto le attese e domanda sostenuta, con tassi reali in discesa.",
                    "Scorte in aumento, domanda debole e dollaro in rafforzamento."),
}

SUMMARY_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "executive_summary": {"type": "STRING"},
        "key_risk": {"type": "STRING"},
    },
    "required": ["executive_summary", "key_risk"],
}


def _scenarios(asset: dict, analysis: dict) -> list[dict]:
    """DEMO-15: scenari a 12 mesi costruiti su volatilità annualizzata e stima
    di valore; probabilità funzione dell'Opportunity Score."""
    t = asset["tech"]
    price, sigma = t["price"], max(t["volatility"], 0.05)
    base = analysis["plan"]["target"]
    bull = round(price * (1 + max(base / price - 1, 0.0) + 0.6 * sigma), 2)
    bear = round(price * (1 - 0.9 * sigma), 2)
    score = analysis["opportunity_score"]
    p_bull = max(0.10, min(0.55, 0.20 + (score - 50) * 0.006))
    p_bear = max(0.10, min(0.50, 0.35 - (score - 50) * 0.004))
    p_base = round(1 - p_bull - p_bear, 2)
    bull_why, bear_why = SCENARIO_RATIONALE.get(asset["asset_class"],
                                                SCENARIO_RATIONALE["Azioni"])
    val = analysis["agents"]["valuation"]
    base_why = (f"Il prezzo converge sul valore stimato dal sistema "
                f"({val['method']}, confidenza {val['confidence']}/100) nei 12 mesi.")
    rows = [
        ("Bull", bull, round(p_bull, 2), bull_why),
        ("Base", base, p_base, base_why),
        ("Bear", bear, round(p_bear, 2), bear_why),
    ]
    return [{"scenario": s, "price": p, "return": round(p / price - 1, 4),
             "probability": pr, "rationale": r} for s, p, pr, r in rows]


def _summary(asset: dict, analysis: dict, triggers: list[dict]) -> str:
    s = analysis["scores"]
    plan = analysis["plan"]
    val = analysis["agents"]["valuation"]
    trig = ", ".join(t["label"] for t in triggers) or "nessun trigger attivo"
    nd = lambda v: "n.d." if v is None else v  # noqa: E731
    return (
        f"{asset['name']} ({asset['ticker']}, {asset['asset_class']} - {asset['market']}) "
        f"quota {asset['tech']['price']} {asset['currency']} con un Opportunity Score di "
        f"{analysis['opportunity_score']}/100, classificato \"{analysis['classification']}\". "
        f"Il punteggio nasce da Fondamentale {nd(s['fundamental'])}, Tecnico "
        f"{nd(s['technical'])}, Valutazione AI {nd(s['valuation'])}, Sentiment "
        f"{nd(s['sentiment'])} e Rischio {nd(s['risk'])} "
        f"({analysis['risk_label']}). Valore stimato {val['fair_value']} "
        f"{asset['currency']} con metodo \"{val['method']}\" e confidenza "
        f"{val['confidence']}/100. Trigger rilevati: {trig}. "
        f"Scostamento dal valore {plan['upside_to_target'] * 100:+.1f}%, "
        f"rischio/rendimento {plan['risk_reward']:.2f} con stop a {plan['stop_loss']}. "
        f"Valutazione finale: {analysis['final_rating']}."
    )


def _llm_summary(asset: dict, analysis: dict, triggers: list[dict], llm) -> dict | None:
    if llm is None or not (llm.enabled or llm.use_cache):
        return None
    s = analysis["scores"]
    val = analysis["agents"]["valuation"]
    plan = analysis["plan"]
    prompt = (
        f"Scrivi la sintesi di un report di analisi per {asset['name']} ({asset['ticker']}), "
        f"{asset['asset_class']} del mercato {asset['market']}, settore {asset['sector']}.\n"
        f"Dati da usare, senza aggiungerne altri:\n"
        f"- prezzo {asset['tech']['price']} {asset['currency']}; performance 3 mesi "
        f"{asset['tech']['perf_3m'] * 100:+.1f}%\n"
        f"- punteggi: fondamentale {s['fundamental']}/100, tecnico {s['technical']}/100, "
        f"valutazione {s['valuation']}/100, notizie {s['sentiment']}/100, rischio "
        f"{s['risk']}/100 ({analysis['risk_label']})\n"
        f"- valore stimato {val['fair_value']} {asset['currency']} (metodo {val['method']}, "
        f"confidenza {val['confidence']}/100), scostamento dal prezzo "
        f"{plan['upside_to_target'] * 100:+.1f}%\n"
        f"- punteggio complessivo {analysis['opportunity_score']}/100 "
        f"({analysis['classification']}), giudizio {analysis['final_rating']}\n"
        f"- trigger attivi: {', '.join(t['label'] for t in triggers) or 'nessuno'}\n"
        f"- notizie: {analysis['agents']['sentiment']['note'] or 'nessuna rilevante'}\n\n"
        f"Restituisci:\n"
        f"- executive_summary: 4 o 5 frasi in italiano professionale, massimo 900 caratteri, "
        f"che dicano che cosa fa l'asset, perché il punteggio è quello e che cosa lo "
        f"metterebbe in discussione. Nessuna promessa di rendimento.\n"
        f"- key_risk: il rischio principale in una frase."
    )
    data = llm.generate_json(prompt, SUMMARY_SCHEMA,
                             cache_key=f"summary|{asset['ticker']}|"
                                       f"{analysis['opportunity_score']}|{val['fair_value']}",
                             max_output_tokens=700)
    if not data:
        return None
    body = llm_mod.text(data.get("executive_summary"), 1100)
    risk = llm_mod.text(data.get("key_risk"), 300)
    if len(body) < 80:
        return None
    return {"summary": body, "key_risk": risk, "engine": f"Gemini ({llm.model})"}


def _section_fundamental(asset: dict, analysis: dict) -> str:
    ag = analysis["agents"]["fundamental"]
    if ag["score"] is None:
        return ag["note"]
    top = [d for d in ag["drivers"] if d.get("score") is not None][:4]
    bits = ", ".join(f"{d['label']} {d['value']} (score {d['score']})" for d in top)
    return (f"Fundamental Score {ag['score']}/100 - base dati: {ag['basis']}. "
            f"Contributi principali: {bits}. {ag['note']}")


def _section_technical(asset: dict, analysis: dict) -> str:
    t, ag = asset["tech"], analysis["agents"]["technical"]
    return (f"Technical Score {ag['score']}/100. Prezzo {t['price']} "
            f"{'sopra' if t['above_ema50'] else 'sotto'} EMA50 ({t['ema50']}) e "
            f"{'sopra' if t['above_ema200'] else 'sotto'} EMA200 ({t['ema200']}); "
            f"RSI {t['rsi']}, ADX {t['adx']}, istogramma MACD "
            f"{'positivo' if t['macd_positive'] else 'negativo'}, posizione in Bollinger "
            f"{t['bb_position']:.2f}, volumi {t['volume_ratio']:.2f}x la media a 20 giorni. "
            f"Resistenza a 60 giorni {t['resistance_60d']}"
            f"{', superata' if t['breakout'] else ', non ancora superata'}. "
            f"Performance 1m {t['perf_1m'] * 100:+.1f}%, 3m {t['perf_3m'] * 100:+.1f}%, "
            f"6m {t['perf_6m'] * 100:+.1f}%. {ag['note']}").strip()


def _section_valuation(asset: dict, analysis: dict) -> str:
    ag = analysis["agents"]["valuation"]
    if ag["score"] is None:
        return ag["note"]
    drivers = ", ".join(f"{d['label']} {d['value']}" for d in ag["drivers"][:5])
    extra = f" Lettura del modello: {ag['ai_reasoning']}" if ag.get("ai_reasoning") else ""
    return (f"Valutazione AI {ag['score']}/100, prodotta da {ag['source']}. "
            f"Valore stimato {ag['fair_value']} {asset['currency']} contro un prezzo di "
            f"{asset['tech']['price']}: scostamento "
            f"{(ag['fair_value'] / asset['tech']['price'] - 1) * 100:+.1f}%. "
            f"Metodo: {ag['method']}; confidenza sui dati {ag['confidence']}/100. "
            f"Elementi della stima: {drivers}.{extra} "
            f"Nessun rating o target price di analisti esterni entra in questo calcolo.")


def _section_risks(asset: dict, analysis: dict) -> list[str]:
    ag = analysis["agents"]["risk"]
    out = [f"{d['label']}: {d['value']} (score {d['score']}/100)"
           for d in ag["drivers"][:4] if d.get("score") is not None]
    neg = [n for n in asset["news"] if (n.get("polarity") or 0) < -0.2][:2]
    out += [f"Notizia negativa recente: {n['headline']} ({n['source']}, {n['date']})" for n in neg]
    if asset["asset_class"] == "Crypto":
        out.append("Asset class ad alta volatilità e senza flussi di cassa da valutare: "
                   "dimensionare la posizione di conseguenza.")
    if analysis["agents"]["valuation"]["confidence"] < 50:
        out.append("Confidenza bassa sulla stima di valore: i dati disponibili non bastano "
                   "a fissare un prezzo obiettivo affidabile.")
    return out


def build_report(asset: dict, analysis: dict, triggers: list[dict],
                 requested_by: str | None = None, question: str | None = None,
                 llm=None) -> dict:
    closes = asset["series"]["close"]
    dates = asset["series"]["date"]
    n = 130
    e50, e200 = ema(closes, 50), ema(closes, 200)
    ai = _llm_summary(asset, analysis, triggers, llm)
    summary = ai["summary"] if ai else _summary(asset, analysis, triggers)
    risks = _section_risks(asset, analysis)
    if ai and ai["key_risk"]:
        risks = [ai["key_risk"]] + risks
    return {
        "report_id": f"RPT-{asset['ticker'].replace('.', '-')}-{TODAY.isoformat()}",
        "ticker": asset["ticker"],
        "name": asset["name"],
        "generated_on": TODAY.isoformat(),
        "requested_by": requested_by,
        "question": question,
        "narrative_engine": ai["engine"] if ai else TEMPLATE_ENGINE,
        "executive_summary": summary,
        "sections": [
            {"title": "Analisi fondamentale", "body": _section_fundamental(asset, analysis)},
            {"title": "Analisi tecnica", "body": _section_technical(asset, analysis)},
            {"title": "Valutazione: prezzo contro valore",
             "body": _section_valuation(asset, analysis)},
        ],
        "risks": risks,
        "scenarios": _scenarios(asset, analysis),
        "final_rating": analysis["final_rating"],
        "opportunity_score": analysis["opportunity_score"],
        "classification": analysis["classification"],
        "plan": analysis["plan"],
        "chart": {
            "dates": dates[-n:],
            "close": [round(c, 2) for c in closes[-n:]],
            "ema50": [round(x, 2) for x in e50[-n:]],
            "ema200": [round(x, 2) for x in e200[-n:]],
        },
    }
