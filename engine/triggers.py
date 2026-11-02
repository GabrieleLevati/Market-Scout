"""Rilevazione dei trigger di opportunità (BR-05, step 3 del workflow).

L'FDD definisce le soglie solo per sottovalutazione (>20%, A-06) e correzione
(-15%/-30%). Le altre sono scelte di demo, tracciate come DEMO-06..DEMO-09
contro OP-11 e modificabili da un unico punto (THRESHOLDS).
"""

from __future__ import annotations

from .universe import TODAY

THRESHOLDS = {
    "undervaluation_min": 0.20,          # FDD / A-06
    "correction_min": 0.15,              # FDD
    "correction_max": 0.30,              # FDD
    "correction_window_days": 90,        # DEMO-06 (OP-11)
    "fundamentals_intact_min_score": 70, # DEMO-07 (OP-11): "fondamentali invariati"
    "insider_net_buy_usd": 1_000_000,    # DEMO-08 (OP-11): acquisto significativo
    "insider_roles": ("CEO", "CFO", "COO", "Direttore divisione"),
    "high_volume_ratio": 1.5,            # DEMO-09 (OP-11): volumi elevati
    "estimate_revision_min": 0.03,       # DEMO-22: stima di valore rialzata in 30 giorni
}

LABELS = {
    "undervaluation": "Sottovalutazione",
    "insider_buying": "Insider buying",
    "market_correction": "Correzione di mercato",
    "earnings_surprise": "Earnings positive surprise",
    # Al posto dell'"upgrade degli analisti" dell'FDD: la revisione al rialzo
    # della stima di valore del sistema, mossa dai dati pubblicati
    # dall'emittente (guidance, dati di rete, scorte).
    "estimate_raised": "Stima di valore rialzata",
    "technical_breakout": "Breakout tecnico",
}


def _drawdown_window(asset: dict, days: int) -> float:
    closes = asset["series"]["close"][-days:]
    peak = max(closes)
    return closes[-1] / peak - 1


def detect(asset: dict, fundamental_score: int, valuation: dict | None = None) -> list[dict]:
    """`valuation` è l'uscita dell'AI Valuation Agent: contiene la stima di
    valore su cui si misurano sottovalutazione e revisione."""
    t, f = asset["tech"], asset["fundamentals"]
    val = valuation or asset.get("valuation") or {}
    fair = val.get("fair_value", val.get("value"))
    th = THRESHOLDS
    out: list[dict] = []

    def add(kind, detail, **values):
        out.append({"type": kind, "label": LABELS[kind], "ticker": asset["ticker"],
                    "detected_on": TODAY.isoformat(), "detail": detail, "values": values})

    if fair:
        upside = fair / t["price"] - 1
        if upside > th["undervaluation_min"]:
            add("undervaluation",
                f"Valore stimato {fair} contro prezzo {t['price']}: "
                f"{upside * 100:+.1f}% di scostamento "
                f"(soglia {th['undervaluation_min'] * 100:.0f}%), stima prodotta da "
                f"{val.get('source', 'modello quantitativo')}",
                upside=round(upside, 4), target=fair,
                source=val.get("source", "modello quantitativo"))

    ins = asset["insider"]
    if ins.get("coverage") and ins["net_buy_usd"] >= th["insider_net_buy_usd"] \
            and ins["top_role"] in th["insider_roles"]:
        add("insider_buying",
            f"Acquisti netti insider {ins['net_buy_usd'] / 1e6:.1f}M$ in "
            f"{ins['window_days']} giorni, ruolo più alto: {ins['top_role']}",
            net_buy_usd=ins["net_buy_usd"], role=ins["top_role"])

    dd = _drawdown_window(asset, th["correction_window_days"])
    # senza punteggio fondamentale non si può dire "fondamentali invariati"
    if fundamental_score is not None and -th["correction_max"] <= dd <= -th["correction_min"] \
            and fundamental_score >= th["fundamentals_intact_min_score"]:
        add("market_correction",
            f"Calo {dd * 100:.1f}% dal massimo degli ultimi "
            f"{th['correction_window_days']} giorni con Fundamental Score "
            f"{fundamental_score} (>= {th['fundamentals_intact_min_score']})",
            drawdown=round(dd, 4), fundamental_score=fundamental_score)

    e = asset["earnings"]
    eps_s, rev_s = e.get("eps_surprise"), e.get("revenue_surprise")
    if e.get("coverage") and (eps_s or 0) > 0 and (rev_s or 0) > 0:
        if e.get("basis") == "crescita anno su anno":
            # senza previsioni di analisti la "sorpresa" è la crescita vera
            # rispetto allo stesso trimestre dell'anno prima
            add("earnings_surprise",
                f"Ultimo trimestre ({e.get('report_date')}): utile per azione "
                f"{eps_s * 100:+.1f}% e ricavi {rev_s * 100:+.1f}% rispetto allo stesso "
                f"trimestre dell'anno precedente",
                eps_surprise=eps_s, revenue_surprise=rev_s, basis=e["basis"])
        else:
            add("earnings_surprise",
                f"EPS {e.get('eps_actual')} vs stima {e.get('eps_estimate')} "
                f"({eps_s * 100:+.1f}%), ricavi {rev_s * 100:+.1f}% sopra le attese "
                f"({e.get('report_date')})",
                eps_surprise=eps_s, revenue_surprise=rev_s)

    revision = (asset.get("valuation") or {}).get("revision_30d") or 0.0
    guidance = (f.get("guidance_change_30d") if f.get("guidance_change_30d") is not None
                else f.get("eps_ttm_change") if f.get("eps_ttm_change") is not None
                else f.get("estimate_revision_30d") or 0.0)
    if revision >= th["estimate_revision_min"]:
        add("estimate_raised",
            f"Stima di valore rialzata del {revision * 100:+.1f}% in 30 giorni "
            f"(soglia {th['estimate_revision_min'] * 100:.0f}%); dato che l'ha mossa: "
            f"{'guidance aziendale' if f.get('guidance_change_30d') is not None else 'utile a dodici mesi dopo l ultimo trimestre'} "
            f"{guidance * 100:+.1f}%",
            revision=round(revision, 4), guidance=round(guidance, 4))

    if t["breakout"] and t["volume_ratio"] >= th["high_volume_ratio"]:
        add("technical_breakout",
            f"Prezzo {t['price']} sopra la resistenza a 60 giorni "
            f"({t['resistance_60d']}) con volumi {t['volume_ratio']:.2f}x la media 20g",
            resistance=t["resistance_60d"], volume_ratio=t["volume_ratio"])

    return out
