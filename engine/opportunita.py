"""L'elenco delle opportunita', uguale per tutti.

Prima di questo modulo le opportunita' passavano dal filtro del profilo: ogni
utente vedeva un sottoinsieme diverso secondo mercati, settori, tetto di
rischio e limite settimanale. La specifica e' cambiata: le opportunita' sono le
stesse per chiunque, e l'unico criterio e' il punteggio sopra soglia.

Resta una sola esclusione, e non e' un filtro di gusto: gli strumenti di cui
non si riesce a stimare un valore (ETF, obbligazioni e cripto senza bilanci)
vengono monitorati ma non proposti, perche' dire "costa meno di quanto vale"
senza sapere quanto vale sarebbe una frase vuota. Il motivo viene dichiarato,
non nascosto.

Questo elenco e' la fonte unica: lo mostra la pagina e lo usano le notifiche.
Se un giorno divergessero, l'utente vedrebbe una cosa e ne riceverebbe un'altra.
"""

from __future__ import annotations

from .valuation import TETTO_ALTO, TETTO_BASSO


def _motivi(triggers: list[dict], limite: int = 3) -> list[str]:
    """Le etichette dei segnali, in ordine di come le ha prodotte il motore."""
    return [t["label"] for t in (triggers or [])][:limite]


def _pct(v: float, decimali: int = 1) -> str:
    return f"{v * 100:+.{decimali}f}%".replace(".", ",")


def _num(v: float, decimali: int = 2) -> str:
    """Numero all'italiana: virgola per i decimali. Un prezzo scritto 209.94 a
    un lettore italiano sembra duecentonove-virgola-novantaquattro solo se lo
    traduce da se', e non e' il suo mestiere."""
    return f"{v:,.{decimali}f}".replace(",", "@").replace(".", ",").replace("@", ".")


def visione(a: dict, an: dict, plain: dict | None) -> dict:
    """Il giudizio in parole: che cosa farei, dove penso che arrivi, in quanto
    tempo, che movimento e' invece soltanto rumore, e che cosa mi farebbe
    cambiare idea.

    SUL TEMPO, che e' la parte delicata. La tentazione sarebbe scrivere "fra
    due settimane +20%": sarebbe una bugia, e si vede facendo il conto. Con una
    volatilita' annua del 24% il movimento tipico di dieci sedute e' intorno al
    5%, non al 20%. Il tempo perche' un movimento di una certa ampiezza diventi
    probabile si stima dalla volatilita': servono circa (ampiezza/volatilita'
    giornaliera)^2 sedute. Per la maggior parte dei titoli questo da' mesi, non
    settimane, ed e' coerente con l'orizzonte a dodici mesi degli scenari.

    Quindi si dicono due cose diverse e si tengono separate:
      - dove penso che arrivi, e in quanto tempo (orizzonte onesto);
      - quanto si muove normalmente in due settimane, che serve a NON reagire
        al rumore. E' l'informazione che evita di vendere per uno scossone.
    """
    t = a["tech"]
    plan = an["plan"]
    prezzo = t["price"]
    salita = plan["upside_to_target"]
    # La stima ha toccato il tetto? Succede proprio sui casi piu' estremi, e
    # sono quelli in cui il numero vale meno: senza dirlo, il +60% al tetto
    # sembrerebbe un'occasione migliore di un +44% calcolato per davvero.
    rapporto = (plan["target"] / prezzo) if prezzo else 0
    al_tetto = (abs(rapporto - TETTO_ALTO) < 0.005
                or abs(rapporto - TETTO_BASSO) < 0.005)
    vol_annua = max(t.get("volatility") or 0.0, 0.02)
    vol_giorno = vol_annua / (252 ** 0.5)

    # sedute perche' il movimento verso il valore stimato diventi plausibile
    sedute = (abs(salita) / vol_giorno) ** 2 if vol_giorno else 0
    mesi = sedute / 21.0
    if mesi < 1:
        orizzonte = "qualche settimana"
    elif mesi < 3:
        orizzonte = f"{max(1, round(mesi))} mesi circa"
    elif mesi <= 18:
        orizzonte = f"{round(mesi)} mesi circa"
    else:
        orizzonte = "oltre un anno e mezzo"

    # movimento tipico di dieci sedute: due settimane di borsa
    rumore = vol_giorno * (10 ** 0.5)

    punteggio = an["opportunity_score"]
    if punteggio >= 90:
        azione = "La comprerei, e con convinzione."
    elif punteggio >= 80:
        azione = "La comprerei."
    elif punteggio >= 70:
        azione = "La terrei d'occhio, senza fretta di entrare."
    else:
        azione = "Non la comprerei adesso."

    attesa = (f"Oggi costa fra {_num(plan['entry_low'])} e {_num(plan['entry_high'])}, ed è "
              f"quella la fascia in cui entrerei. Secondo i miei conti vale "
              f"{_num(plan['target'])}: {_pct(salita)} da qui.")
    # L'orizzonte si scrive e basta: la spiegazione di come lo calcolo sta nel
    # foglio "come lavoro", non davanti agli occhi di chi deve solo decidere.
    tempo = ""  
    noto = (f"Nelle prossime due settimane un movimento fino al "
            f"{abs(rumore) * 100:.0f}% in su o in giù è normale per questo strumento: "
            f"non vuol dire niente, e io non ci reagirei.")
    cambio = (f"Cambio idea se scende a {_num(plan['stop_loss'])} "
              f"({_pct(plan['downside_to_stop'])}): a quel punto la tesi non regge più, e "
              f"preferisco uscire con una perdita piccola.")

    limite = ""
    if al_tetto:
        limite = (f"Attenzione a questo {_pct(salita, 0)}: è il tetto che mi sono dato, "
                  f"non un conto preciso. Quando il confronto con i simili di settore "
                  f"spinge oltre il "
                  f"{abs(TETTO_ALTO - 1) * 100:.0f}% dal prezzo lo fermo lì, perché più in "
                  f"là non so davvero. Lo legga come «molto sottovalutato», non come un "
                  f"numero.")

    scenari = (plain or {}).get("scenarios_plain") or []
    probabile = next((s for s in scenari if "probabile" in s.get("name", "").lower()), None)
    return {
        "azione": azione,
        "attesa": attesa,
        "tempo": tempo,
        "rumore": noto,
        "rumore_pct": round(rumore, 4),
        "cambio_idea": cambio,
        "limite": limite,
        "al_tetto": al_tetto,
        "orizzonte": orizzonte,
        "probabilita": probabile.get("probability") if probabile else None,
        "scenari": [s.get("text") for s in scenari if s.get("text")],
        "testo": " ".join(x for x in [azione, attesa, limite, tempo, noto, cambio] if x),
    }


def _voce_osservata(ticker: str, a: dict, an: dict, triggers_by_ticker: dict,
                    plain: dict | None) -> dict:
    """I campi di uno strumento osservato, cioe' senza stima di valore.

    Volutamente NON ha target, stop, fascia di ingresso, rischio/rendimento ne'
    "visione": tutte cose che si calcolano a partire dal valore stimato. Le
    chiavi ci sono comunque, a None, perche' la pagina usa lo stesso disegno di
    card e le righe vuote le salta da se'. Un None dichiarato e' meglio di una
    chiave che manca: la seconda si scopre con un errore, il primo no.
    """
    t = a["tech"]
    return {
        "classification": an["classification"],
        "final_rating": an["final_rating"],
        "risk_label": an["risk_label"],
        "risk_score": an["scores"]["risk"],
        "sector": a["sector"],
        "asset_class": a["asset_class"],
        "market": a["market"],
        "size": a.get("size"),
        "currency": a["currency"],
        "price": t["price"],
        "scores": dict(an["scores"]),
        "reasons": _motivi(triggers_by_ticker.get(ticker, [])),
        "analysis_sources": dict(an.get("ai_sources") or {}),
        "che_cos_e": ((plain or {}).get(ticker) or {}).get("what_is_it"),
        "senza_valore": True,
        "target": None, "stop_loss": None, "entry_low": None, "entry_high": None,
        "upside": None, "downside": None, "risk_reward": None,
        "fair_value": None, "valuation_method": None, "valuation_source": None,
        "valuation_confidence": None, "visione": None,
    }


def globali(assets: dict, analyses: dict, triggers_by_ticker: dict,
            threshold: int, plain: dict | None = None) -> dict:
    """Restituisce {"lista", "osservati", "scartati", "soglia"}.

    `lista` sono le opportunita' vere, ordinate per punteggio decrescente.
    `osservati` sono gli strumenti sopra soglia di cui NON si puo' stimare un
    valore (ETF, obbligazionari, materie prime): si mostrano a parte, senza
    prezzo obiettivo, e non generano notifiche. `scartati` serve a poter dire
    perche' qualcosa non c'e': un elenco vuoto senza spiegazione sembra un
    guasto.
    """
    lista, osservati, scartati = [], [], []
    for ticker, a in assets.items():
        an = analyses.get(ticker)
        if not an:
            continue
        punteggio = an["opportunity_score"]
        val = (an.get("agents") or {}).get("valuation") or {}
        senza_valore = (an.get("scores", {}).get("valuation") is None
                        or val.get("applicable") is False
                        or not val.get("fair_value"))
        if senza_valore:
            # ETF, obbligazionari, materie prime: non hanno bilanci, quindi non
            # si puo' stimare quanto valgono e non si puo' dire "costa meno di
            # quanto vale". Non sono opportunita' e non lo diventano.
            #
            # Ma buttarli fra gli scartati nascondeva un fatto: possono avere
            # punteggi alti. Un ETF a 75 punti era il secondo punteggio della
            # giornata e non arrivava in pagina, sepolto in un elenco di
            # esclusi. Quindi chi supera la soglia finisce in una lista a
            # parte - osservati - dichiarata per quello che e': punteggio si',
            # prezzo obiettivo no. Chi non la supera resta fra gli scartati,
            # perche' avrebbe due motivi per non esserci e uno basta.
            voce = {
                "ticker": ticker, "name": a["name"], "score": punteggio,
                "motivo": "Di questo strumento non ho i conti per stimare un valore: "
                          "lo tengo d'occhio ma non lo propongo.",
            }
            if punteggio > threshold:
                voce.update(_voce_osservata(ticker, a, an, triggers_by_ticker, plain))
                osservati.append(voce)
            else:
                scartati.append(voce)
            continue
        if punteggio <= threshold:
            scartati.append({
                "ticker": ticker, "name": a["name"], "score": punteggio,
                # La soglia e' STRETTA (il confronto qui sopra e' <=), quindi un
                # punteggio pari alla soglia non passa. Il testo precedente
                # diceva "70 punti, sotto la soglia di 70": una contraddizione
                # che si leggeva in pagina. Qui si dice la regola invece del
                # confronto, cosi' vale sia per 68 che per 70.
                "motivo": f"Ha preso {punteggio} punti su 100: per segnalarlo "
                          f"dovrebbe superare {threshold}.",
            })
            continue
        plan = an["plan"]
        t = a["tech"]
        lista.append({
            "ticker": ticker,
            "name": a["name"],
            "score": punteggio,
            "classification": an["classification"],
            "final_rating": an["final_rating"],
            "risk_label": an["risk_label"],
            "risk_score": an["scores"]["risk"],
            "sector": a["sector"],
            "asset_class": a["asset_class"],
            "market": a["market"],
            "size": a.get("size"),
            "currency": a["currency"],
            "price": t["price"],
            "target": plan["target"],
            "stop_loss": plan["stop_loss"],
            "entry_low": plan["entry_low"],
            "entry_high": plan["entry_high"],
            "upside": plan["upside_to_target"],
            "downside": plan["downside_to_stop"],
            "risk_reward": plan["risk_reward"],
            "fair_value": val.get("fair_value"),
            "valuation_method": val.get("method"),
            "valuation_source": val.get("source"),
            "valuation_confidence": val.get("confidence"),
            "scores": dict(an["scores"]),
            "reasons": _motivi(triggers_by_ticker.get(ticker, [])),
            "analysis_sources": dict(an.get("ai_sources") or {}),
            # che cos'e' lo strumento, in una frase, e il giudizio in parole
            "che_cos_e": ((plain or {}).get(ticker) or {}).get("what_is_it"),
            "visione": visione(a, an, (plain or {}).get(ticker)),
        })
    lista.sort(key=lambda o: -o["score"])
    osservati.sort(key=lambda o: -o["score"])
    scartati.sort(key=lambda o: -o["score"])
    return {"lista": lista, "osservati": osservati, "scartati": scartati[:8],
            "soglia": threshold}
