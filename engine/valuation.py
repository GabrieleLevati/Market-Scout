"""Modello di valutazione proprietario: il prezzo obiettivo lo calcola il
sistema, non il consensus degli analisti.

Scelta di prodotto (scostamento dall'FDD, vedi decisions.FDD_CHANGES): l'Analyst
Consensus Agent di BR-03 è sostituito dall'**AI Valuation Agent**. Il sistema non
consuma rating e target price di analisti umani: stima il valore da sé, partendo
dai fatti pubblicati dall'emittente (bilanci, guidance, dati di rete, scorte) e
lasciando a Gemini il giudizio qualitativo sulla stima.

Lo stesso modello serve a due scopi, e deve essere uno solo per non raccontare
due verità diverse:

* il generatore di dati (`universe.py`) lo usa per fissare il prezzo di mercato
  rispetto al valore, cioè quanto l'asset è sopra o sotto il suo valore;
* l'agente di valutazione (`agents.py`) lo usa per stimare quel valore.
"""

from __future__ import annotations

EQUITY_LIKE = {"Azioni", "REIT"}


# Il tetto della stima di valore, in multipli del prezzo (DEMO-26). Serve
# perche' il confronto con i simili di settore, spinto oltre, dice cose che non
# puo' sapere. Hanno un nome perche' chi mostra la stima deve poter dire
# "questa ha toccato il tetto" invece di presentare il numero come un altro.
TETTO_BASSO = 0.50
TETTO_ALTO = 1.60


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def val(f: dict, key: str, default: float = 0.0) -> float:
    """Legge una voce di bilancio tollerando l'assenza del dato."""
    v = f.get(key)
    return default if v is None else float(v)


def fair_multiple(f: dict, raw: bool = False) -> float:
    """Multiplo giusto sugli utili per un'azione: parte da 9 volte e paga la
    crescita, la redditività del capitale e i margini, scontando il debito.
    Nessun dato di analisti: solo voci di bilancio."""
    # Una voce mancante non dà premio: un dato assente non diventa un dato
    # inventato. La crescita è tagliata al 60% annuo, oltre non è ripetibile.
    base = 9.0
    base += 100.0 * clamp(val(f, "revenue_growth"), 0.0, 0.60) * 1.05
    base += 28.0 * clamp(val(f, "roic"), 0.0, 0.60)
    base += 14.0 * clamp(val(f, "net_margin"), 0.0, 0.60)
    base -= 3.2 * max(val(f, "debt_to_equity") - 0.5, 0.0)
    # `raw` serve a misurare la revisione della stima anche quando il multiplo
    # è già al tetto: altrimenti il limite si mangia il segnale
    return base if raw else clamp(base, 7.0, 46.0)


def peer_stats(assets: list[dict]) -> dict:
    """Mediane di settore su cui tarare il multiplo (DEMO-26).

    Sui dati reali un multiplo assoluto non funziona: nel 2026 metà del listino
    tecnologico cresce oltre il 40% e la formula a premi direbbe "sottovalutato"
    per tutti. Il riferimento diventa quindi il settore stesso: quanto paga il
    mercato le aziende simili, e quanto questa cresce rispetto a loro."""
    by_sector: dict[str, list[tuple[float, float]]] = {}
    everything: list[tuple[float, float]] = []
    for a in assets:
        if a["asset_class"] not in EQUITY_LIKE:
            continue
        f = a["fundamentals"]
        pe, g = f.get("pe"), f.get("revenue_growth")
        if not pe or pe <= 0 or pe > 200:
            continue
        pair = (float(pe), float(g) if g is not None else 0.0)
        by_sector.setdefault(a["sector"], []).append(pair)
        everything.append(pair)

    def med(values: list[float]) -> float | None:
        if not values:
            return None
        v = sorted(values)
        n = len(v)
        return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2

    out = {"sectors": {}, "all": None}
    if everything:
        out["all"] = {"pe": med([p for p, _ in everything]),
                      "growth": med([g for _, g in everything]),
                      "n": len(everything)}
    for sector, pairs in by_sector.items():
        if len(pairs) >= 3:        # con meno di tre nomi la mediana non dice nulla
            out["sectors"][sector] = {"pe": med([p for p, _ in pairs]),
                                      "growth": med([g for _, g in pairs]),
                                      "n": len(pairs)}
    return out


def peer_for(asset: dict, peers: dict | None) -> dict | None:
    if not peers:
        return None
    return peers.get("sectors", {}).get(asset["sector"]) or peers.get("all")


def relative_multiple(f: dict, peer: dict) -> tuple[float, list[str]]:
    """Multiplo giusto in rapporto ai simili: parte dalla mediana del settore e
    la corregge per crescita, redditività e debito, entro limiti stretti."""
    base = peer["pe"]
    notes = [f"il settore paga in mediana {base:.0f} volte gli utili"]
    growth_gap = clamp(val(f, "revenue_growth") - peer.get("growth", 0.0), -0.35, 0.35)
    adj = 1 + 1.1 * growth_gap
    if abs(growth_gap) > 0.02:
        notes.append(f"cresce {growth_gap * 100:+.0f} punti rispetto ai simili")
    roic, margin = val(f, "roic"), val(f, "net_margin")
    quality = 0.10 * (1 if roic > 0.18 else -1 if 0 < roic < 0.07 else 0) + \
              0.08 * (1 if margin > 0.20 else -1 if 0 < margin < 0.05 else 0)
    if quality:
        adj *= 1 + quality
        notes.append("redditività " + ("sopra" if quality > 0 else "sotto") + " la media")
    d_e = val(f, "debt_to_equity")
    if d_e > 1.5:
        adj *= 0.9
        notes.append(f"debito elevato ({d_e:.1f} volte il patrimonio)")
    return clamp(base * clamp(adj, 0.55, 1.9), 5.0, 70.0), notes


def expected_return(asset: dict) -> tuple[float, list[dict]]:
    """Rendimento atteso a 12 mesi per le asset class senza utili, con i
    componenti che lo compongono (serviranno a spiegarlo al cliente)."""
    f, acls = asset["fundamentals"], asset["asset_class"]
    parts: list[dict] = []

    def add(label, value, text):
        parts.append({"label": label, "value": round(value, 4), "text": text})

    if acls == "ETF":
        g = f["index_earnings_growth"]
        add("Crescita utili dell'indice", g,
            f"le aziende dentro il paniere crescono del {g * 100:.1f}% all'anno")
        add("Costo del prodotto", -f["expense_ratio"],
            f"il paniere costa {f['expense_ratio'] * 100:.2f}% all'anno")
        add("Scostamento dal valore", f["valuation_gap"],
            "quanto il paniere è sopra o sotto il valore delle aziende che contiene")
        total = g - f["expense_ratio"] + f["valuation_gap"]
    elif acls == "Obbligazioni":
        carry = f["yield_to_maturity"]
        rate_effect = -f["duration"] * f["expected_rate_change_1y"]
        add("Interessi incassati", carry, f"rende il {carry * 100:.2f}% all'anno")
        add("Effetto dei tassi", rate_effect,
            f"con {f['duration']:.1f} anni di durata, un movimento dei tassi di "
            f"{f['expected_rate_change_1y'] * 100:+.2f}% sposta il prezzo di "
            f"{rate_effect * 100:+.1f}%")
        total = carry + rate_effect
    elif acls == "Crypto":
        net = 0.45 * f["active_addresses_growth_90d"] + 0.30 * f["fees_growth_90d"]
        add("Uso della rete", net, "quante persone la usano e quante commissioni genera")
        add("Nuove unità emesse", -f["supply_inflation"],
            f"ogni anno la quantità in circolazione cresce del "
            f"{f['supply_inflation'] * 100:.1f}%")
        add("Scostamento dal valore", f["valuation_gap"],
            "quanto il prezzo è sopra o sotto quello che giustifica l'uso della rete")
        total = net - f["supply_inflation"] + f["valuation_gap"]
    else:  # Commodities
        dem = 0.45 * f["demand_proxy_growth"]
        inv = -0.55 * f["inventory_trend_90d"]
        add("Domanda", dem, "quanto se ne consuma rispetto a un anno prima")
        add("Scorte", inv, "scorte in calo spingono il prezzo, scorte in crescita lo frenano")
        add("Dollaro e tassi reali",
            -0.30 * f["dollar_index_trend_90d"] - 0.20 * f["real_yield_context"],
            "un dollaro forte e tassi reali alti pesano sulle materie prime")
        add("Scostamento dal valore", f["valuation_gap"], "sopra o sotto il valore di scambio")
        total = (dem + inv - 0.30 * f["dollar_index_trend_90d"]
                 - 0.20 * f["real_yield_context"] + f["valuation_gap"])

    return clamp(total, -0.45, 0.80), parts


def _valuable(asset: dict) -> bool:
    """Si può stimare un valore? Serve almeno un bilancio o il set proxy."""
    if asset.get("valuable") is False:
        return False
    f = asset["fundamentals"]
    if str(f.get("basis", "")).startswith("solo prezzo"):
        return False
    if asset["asset_class"] in EQUITY_LIKE:
        return (f.get("eps_ttm") or 0) > 0 or (f.get("pe") or 0) > 0
    return True


def fair_value(asset: dict, peers: dict | None = None) -> dict:
    """Stima del valore e come ci si arriva. È il numero che sostituisce il
    'target medio degli analisti' dell'FDD."""
    f, acls = asset["fundamentals"], asset["asset_class"]
    price = asset["tech"]["price"]

    # Senza bilanci non si stima un valore: lo si dice, e si usa il massimo a
    # 12 mesi come semplice riferimento di prezzo (ETF, obbligazioni, crypto e
    # materie prime sui dati reali, dove i fondamentali richiedono un contratto).
    if not _valuable(asset):
        # Nessun valore stimato significa nessuno scostamento da dichiarare:
        # il riferimento al massimo a 12 mesi resta come informazione.
        note = asset.get("valuation_note") or "dati di bilancio non disponibili"
        return {
            "value": round(price, 2), "previous_value": round(price, 2),
            "upside": 0.0, "revision_30d": 0.0,
            "method": f"nessuna stima di valore ({note})",
            "drivers": [{"label": "Massimo degli ultimi 12 mesi",
                         "value": round(asset["tech"]["high_52w"], 2),
                         "text": f"non calcolo un valore perché {note}; come riferimento, "
                                 f"il massimo degli ultimi dodici mesi è "
                                 f"{asset['tech']['high_52w']:.2f}"}],
            "confidence": 15, "valuable": False,
        }

    if acls in EQUITY_LIKE:
        peer = peer_for(asset, peers)
        if peer:
            multiple, peer_notes = relative_multiple(f, peer)
            method = "confronto con i simili di settore"
        else:
            multiple, peer_notes = fair_multiple(f), []
            method = "utili x multiplo giusto"
        eps = f.get("eps_ttm")
        if eps is None:
            eps = price / max(val(f, "pe", 1.0), 1e-6)
        # La revisione della stima: sui dati reali la muove l'utile a dodici
        # mesi quando esce un trimestre nuovo; sui dati sintetici la guidance.
        guidance = f.get("guidance_change_30d")
        eps_change = f.get("eps_ttm_change")
        value = eps * multiple
        if guidance is not None:
            prev_f = {**f, "revenue_growth": val(f, "revenue_growth") - 0.5 * guidance}
            raw_now, raw_prev = fair_multiple(f, raw=True), fair_multiple(prev_f, raw=True)
            prev = value / max(raw_now / max(raw_prev, 1e-6), 1e-6)
            del prev_f
            moved_by = ("Guidance dell'azienda", guidance,
                        f"l'azienda ha {'alzato' if guidance > 0 else 'abbassato'} le proprie "
                        f"previsioni del {abs(guidance) * 100:.1f}% negli ultimi 30 giorni")
        elif eps_change:
            prev = value / (1 + eps_change)
            moved_by = ("Utile a dodici mesi", eps_change,
                        f"con l'ultimo trimestre pubblicato l'utile a dodici mesi è "
                        f"{'salito' if eps_change > 0 else 'sceso'} del "
                        f"{abs(eps_change) * 100:.1f}%")
        else:
            prev, moved_by = value, None
        growth, roic = val(f, "revenue_growth"), val(f, "roic")
        drivers = [
            {"label": "Utile per azione", "value": round(eps, 2),
             "text": f"guadagna {eps:.2f} {asset['currency']} per ogni azione, "
                     f"negli ultimi dodici mesi"},
            {"label": "Multiplo giusto", "value": round(multiple, 1),
             "text": (f"pago {multiple:.0f} volte gli utili: " + "; ".join(peer_notes))
             if peer_notes else
             (f"per una società che cresce del {growth * 100:.1f}% con un ritorno sul "
              f"capitale del {roic * 100:.1f}% pago {multiple:.0f} volte gli utili")},
        ]
        if f.get("pe"):
            drivers.append({"label": "Multiplo pagato oggi dal mercato",
                            "value": round(f["pe"], 1),
                            "text": f"oggi il mercato paga {f['pe']:.0f} volte gli utili"})
        if moved_by:
            drivers.append({"label": moved_by[0], "value": round(moved_by[1], 4),
                            "text": moved_by[2]})
    else:
        exp, parts = expected_return(asset)
        value = price * (1 + exp)
        prev = price * (1 + exp - f.get("estimate_revision_30d", 0.0))
        drivers = [{"label": p["label"], "value": p["value"], "text": p["text"]} for p in parts]
        method = "rendimento atteso a 12 mesi"

    # Un confronto con i simili non può giustificare da solo scostamenti
    # enormi: oltre questi limiti il numero direbbe più di quanto il metodo sa.
    # Spesso dietro un multiplo bassissimo c'è un utile gonfiato da partite
    # straordinarie (holding, rivalutazioni immobiliari): si limita la stima e
    # si abbassa la confidenza, invece di pubblicare un +200%.
    capped = False
    lo_cap, hi_cap = price * TETTO_BASSO, price * TETTO_ALTO
    if acls in EQUITY_LIKE and (value > hi_cap or value < lo_cap):
        value = clamp(value, lo_cap, hi_cap)
        capped = True
    value = max(value, price * 0.2)
    prev = max(prev, price * 0.2)
    return {
        "value": round(value, 2),
        "previous_value": round(prev, 2),
        "upside": round(value / price - 1, 4),
        "revision_30d": round(value / prev - 1, 4),
        "method": method,
        "drivers": drivers,
        "confidence": max(15, confidence(asset) - (20 if capped else 0)),
        "capped": capped,
        "valuable": True,
    }


def confidence(asset: dict) -> int:
    """Quanta fiducia merita la stima: dipende da quanti dati solidi abbiamo,
    non da quanto ci piace il titolo. Un numero basso abbassa il punteggio."""
    f, acls = asset["fundamentals"], asset["asset_class"]
    score = 60.0
    if not _valuable(asset):
        return 15
    if acls in EQUITY_LIKE:
        score += 20 if str(f.get("basis", "")).startswith("bilancio") else 0
        score += 10 if asset["earnings"].get("coverage") else 0
        score -= 10 if val(f, "debt_to_equity") > 1.5 else 0
        score += 8 if abs(val(f, "guidance_change_30d")) > 0.005 else 0
        # sui dati reali una voce di bilancio mancante toglie fiducia
        missing = sum(1 for k in ("revenue_growth", "net_margin", "roe", "roic",
                                  "fcf_margin", "debt_to_equity", "eps_ttm")
                      if f.get(k) is None)
        score -= 4 * missing
    elif acls == "ETF":
        score += 18
    elif acls == "Obbligazioni":
        score += 22          # cedola e scadenza sono contrattuali
    elif acls == "Crypto":
        score -= 18          # nessun flusso di cassa da attualizzare
    else:
        score -= 8
    vol = asset["tech"]["volatility"]
    score -= 12 if vol > 0.55 else 6 if vol > 0.35 else 0
    return int(clamp(score, 15, 95))
