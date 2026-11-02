"""Traduttore in italiano semplice.

Gli agenti producono punteggi, indicatori e soglie. Un cliente retail di 60 anni
non deve leggere "Technical Score 90, ADX 32, posizione in Bollinger 1,05": deve
leggere "il prezzo ha superato il massimo degli ultimi tre mesi e lo ha fatto con
molti scambi, cioè molti stanno comprando".

Questo modulo fa esattamente quella conversione, sempre a partire dai numeri del
motore: nessuna frase è scritta a mano per un singolo asset, e ogni affermazione
è ricostruibile dai dati che cita. Il registro è il "lei", formale ma caldo.

In produzione questa è la parte che passerebbe al provider LLM (OP-07): qui i
template sono deterministici, ma il contratto (che cosa va spiegato, in quale
ordine, con quali numeri) è già quello definitivo.
"""

from __future__ import annotations

from .scoring import classify
from .universe import CLASS_IN_WORDS

# DEMO-19 (OP-12): l'importo di esempio su cui mostriamo guadagno e perdita in
# euro è il 5% del capitale del profilo, arrotondato a 500. Serve a rendere
# concreto un upside percentuale, non è una raccomandazione di quanto investire.
EXAMPLE_SHARE_OF_CAPITAL = 0.05
BASE_AMOUNT = 1000

RATING_WORDS = {
    "Strong Buy": "comprare, con convinzione",
    "Buy": "comprare",
    "Hold": "tenere quello che ha, senza aggiungere",
    "Sell": "alleggerire la posizione",
    "Strong Sell": "uscire da questo investimento",
}

GLOSSARY = {
    "azione": "Una piccola parte di un'azienda. Se l'azienda vale di più, la sua parte vale di più; "
              "se va male, vale di meno.",
    "ETF": "Un paniere che contiene tanti investimenti insieme. Comprandone uno solo lei possiede "
           "un pezzetto di centinaia di aziende, quindi non dipende da una sola.",
    "obbligazione": "Un prestito. Lei presta i soldi a uno Stato o a un'azienda e in cambio incassa "
                    "degli interessi fino alla scadenza.",
    "moneta digitale": "Una valuta che esiste solo su internet, senza una banca centrale che la "
                       "governi. Può guadagnare o perdere molto in poco tempo.",
    "materia prima": "Oro, petrolio, rame: beni fisici il cui prezzo dipende da quanto se ne produce "
                     "e da quanto ne serve.",
    "stop loss": "Un ordine di vendita automatica a un prezzo deciso da lei. Se il prezzo scende "
                 "fino a quel punto, lei esce dall'investimento senza dover stare davanti al "
                 "computer: è la cintura di sicurezza.",
    "valore stimato": "Quanto vale secondo me quell'investimento, calcolato sui conti "
                      "dell'azienda e sui dati che pubblica: utili, crescita, debiti. "
                      "Non è il prezzo di oggi e non è una promessa: è il prezzo che "
                      "giustificherebbero i numeri.",
    "intelligenza artificiale": "Il programma che fa le analisi, in questo servizio il modello "
                                "Gemini di Google. Legge i dati e le notizie, li pesa sempre "
                                "con le stesse regole e scrive quello che ha trovato. Non si "
                                "stanca e non cambia idea per umore, ma può sbagliare: per "
                                "questo le mostro sempre i numeri su cui si è basato.",
    "insider": "Chi lavora al vertice dell'azienda: amministratore delegato, direttore finanziario. "
               "Quando comprano azioni della propria azienda con i loro soldi, di solito sono fiduciosi.",
    "volatilità": "Quanto il prezzo si muove su e giù. Alta volatilità vuol dire che oscilla tanto, "
                  "anche quando non succede nulla di grave.",
    "drawdown": "Quanto il prezzo è sceso dal suo punto più alto. Dice quanto male è andata nel "
                "momento peggiore.",
    "diversificare": "Non mettere tutti i soldi nello stesso posto, così un singolo incidente non "
                     "rovina tutto il resto.",
    "Opportunity Score": "Il voto da 0 a 100 che do a ogni investimento mettendo insieme cinque "
                         "controlli: i conti dell'azienda, l'andamento del prezzo, il "
                         "confronto tra prezzo e valore, le notizie e il rischio. "
                         "Le scrivo solo sopra 85.",
}
def join_it(items: list[str]) -> str:
    """Elenco in italiano: "USA, Europa ed Asia" con la congiunzione giusta."""
    items = [str(i) for i in items]
    if len(items) <= 1:
        return items[0] if items else ""
    last = items[-1]
    conj = "ed" if last[:1].lower() in "aeiou" else "e"
    return ", ".join(items[:-1]) + f" {conj} {last}"


def eur(v: float, decimals: int = 0) -> str:
    """Formato italiano: 12.345 (punto per le migliaia)."""
    s = f"{v:,.{decimals}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def pc(v: float, decimals: int = 1) -> str:
    return f"{v * 100:.{decimals}f}".replace(".", ",") + "%"


def signed_pc(v: float, decimals: int = 1) -> str:
    return ("+" if v >= 0 else "") + pc(v, decimals)


def dec(v: float, decimals: int = 1) -> str:
    """Numero decimale con la virgola, come si scrive in italiano."""
    return f"{v:.{decimals}f}".replace(".", ",")


def art_pc(v: float, decimals: int = 1) -> str:
    """L'articolo giusto davanti alla cifra: dell'1,6% / dello 0,8% / del 3,1%."""
    value = pc(v, decimals)
    first = value[0]
    art = "dell'" if first in "18" else "dello " if first == "0" else "del "
    return art + value


ROLE_WORDS = {
    "CEO": "l'amministratore delegato",
    "CFO": "il direttore finanziario",
    "COO": "il direttore operativo",
    "Direttore divisione": "un direttore di divisione",
    "Membro del board": "un membro del consiglio di amministrazione",
}


def example_amount(user: dict | None) -> int:
    """Importo con cui tradurre le percentuali in euro.

    Se l'utente non ha dichiarato il capitale — e non deve essere obbligato a
    farlo — si usa la base neutra di 1.000 euro: "ogni 1.000 euro investiti".
    Se il capitale c'è, si usa il 5% (DEMO-19)."""
    if not user:
        return BASE_AMOUNT
    capital = (user.get("profile") or {}).get("capital")
    if not capital:
        return BASE_AMOUNT
    raw = capital * EXAMPLE_SHARE_OF_CAPITAL
    return int(round(raw / 500.0) * 500) or BASE_AMOUNT


def amount_is_example(user: dict | None) -> bool:
    """True quando l'importo è la base neutra, non una quota del capitale."""
    return not ((user or {}).get("profile") or {}).get("capital")


# ---------------------------------------------------------------- asset
def _method_in_words(val: dict) -> str:
    """Il metodo di valutazione detto senza gergo, più chi l'ha prodotto."""
    how = {
        "utili x multiplo giusto":
            "Lo calcolo così: quanto guadagna per ogni azione, moltiplicato per quanto è "
            "giusto pagare un'azienda che cresce a questo ritmo.",
        "rendimento atteso a 12 mesi":
            "Lo calcolo dal rendimento che questo investimento può dare in un anno, con i "
            "dati di oggi.",
    }.get(val.get("method"), "")
    who = ("La stima l'ho fatta io con l'intelligenza artificiale."
           if str(val.get("source", "")).startswith("Gemini")
           else "La stima viene dal mio modello di calcolo.")
    conf = val.get("confidence")
    sure = ""
    if isinstance(conf, int):
        sure = (" Su questa stima sono molto sicuro." if conf >= 75
                else " Su questa stima sono abbastanza sicuro." if conf >= 50
                else " Su questa stima ho poca sicurezza, i dati non bastano.")
    return f"{how} {who}{sure}".strip()


def _what_is_it(asset: dict) -> str:
    where = {"USA": "quotata negli Stati Uniti", "Europa": "quotata in Europa",
             "Asia": "quotata in Asia", "Global": "scambiata in tutto il mondo"}[asset["market"]]
    desc = asset["description"] or f"{asset['name']}, {asset['sector'].lower()}."
    clause = CLASS_IN_WORDS.get(asset["asset_class"], asset["asset_class"])
    # se la descrizione dice già di che cosa si tratta, non ripeterlo
    noun = clause.split(",")[0].replace("un'", "").replace("un ", "").replace("una ", "")
    if noun.lower() in desc.lower():
        where = where.replace("quotata", "si scambia").replace("scambiata", "si scambia")
        return f"{desc} {where[0].upper() + where[1:]}."
    return f"{desc} È {clause}, {where}."


def _why_now(asset: dict, analysis: dict, triggers: list[dict]) -> list[dict]:
    """Le ragioni, in ordine di forza: prima i trigger (fatti accaduti), poi i
    punti forti emersi dagli agenti."""
    out: list[dict] = []
    t, f = asset["tech"], asset["fundamentals"]
    val = analysis["agents"]["valuation"]
    plan = analysis["plan"]

    for tr in triggers:
        k = tr["type"]
        if k == "undervaluation":
            out.append({"title": "Costa meno di quanto vale",
                        "text": f"Dai conti di {asset['name']} la mia analisi ricava un valore di "
                                f"{eur(plan['target'], 2)} {asset['currency']}, contro i "
                                f"{eur(t['price'], 2)} che costa oggi: il "
                                f"{pc(plan['upside_to_target'])} in più. "
                                f"{_method_in_words(val)}"})
        elif k == "insider_buying":
            v = tr["values"]["net_buy_usd"] / 1e6
            who = ROLE_WORDS.get(tr["values"]["role"], "un dirigente")
            out.append({"title": "Chi dirige l'azienda sta comprando",
                        "text": f"Negli ultimi tre mesi i vertici hanno comprato azioni della "
                                f"propria azienda con i loro soldi, per circa {dec(v)} milioni "
                                f"di dollari: tra loro {who}. Di solito lo fanno quando sono "
                                f"fiduciosi su quello che vedono dall'interno."})
        elif k == "market_correction":
            out.append({"title": "Il prezzo è sceso, ma l'azienda sta bene",
                        "text": f"Negli ultimi mesi il prezzo ha perso il "
                                f"{pc(abs(tr['values']['drawdown']))}, mentre i conti dell'azienda "
                                f"sono rimasti solidi. Capita quando si vende per paura, non per "
                                f"problemi reali."})
        elif k == "earnings_surprise":
            out.append({"title": "L'ultimo bilancio è andato meglio del previsto",
                        "text": f"L'azienda ha guadagnato il "
                                f"{pc(tr['values']['eps_surprise'])} in più di quanto si "
                                f"era previsto, e ha venduto più del previsto."})
        elif k == "estimate_raised":
            out.append({"title": "Ho alzato la mia stima di valore",
                        "text": f"Negli ultimi 30 giorni l'azienda ha migliorato le proprie "
                                f"previsioni del {pc(tr['values']['guidance'])} e io ho alzato "
                                f"di conseguenza il valore che le attribuisco, del "
                                f"{pc(tr['values']['revision'])}."})
        elif k == "technical_breakout":
            out.append({"title": "Il prezzo ha rotto al rialzo",
                        "text": f"Ha superato il massimo degli ultimi tre mesi "
                                f"({eur(tr['values']['resistance'], 2)}) e lo ha fatto con "
                                f"{dec(tr['values']['volume_ratio'])} volte gli scambi abituali: "
                                f"vuol dire che in molti stanno comprando."})

    if len(out) < 3:
        s = {k: (v if v is not None else -1) for k, v in analysis["scores"].items()}
        if s["fundamental"] >= 75 and str(asset["fundamentals"]["basis"]).startswith("bilancio"):
            out.append({"title": "I conti dell'azienda sono in ordine",
                        "text": f"Le vendite crescono del {pc(f['revenue_growth'])} all'anno e "
                                f"di ogni 100 euro incassati ne restano "
                                f"{eur(f['net_margin'] * 100)} di utile. Il debito è "
                                f"{'contenuto' if f['debt_to_equity'] < 1 else 'significativo ma gestibile'}."})
        if s["technical"] >= 75:
            out.append({"title": "Il prezzo è in salita stabile",
                        "text": f"Negli ultimi tre mesi ha fatto il "
                                f"{signed_pc(t['perf_3m'])} e resta sopra le sue medie di "
                                f"riferimento: la tendenza di fondo è al rialzo."})
        if s["sentiment"] >= 75:
            out.append({"title": "Le notizie recenti sono buone",
                        "text": "Nelle ultime due settimane le notizie su questa società sono "
                                "state in prevalenza positive."})
        if s["valuation"] >= 75:
            out.append({"title": "Il prezzo è sotto il valore che calcolo",
                        "text": f"Il mio valore stimato è {eur(val['fair_value'], 2)} "
                                f"{asset['currency']} contro {eur(t['price'], 2)} di prezzo. "
                                f"{_method_in_words(val)}"})
    return out[:4]


def _not_now_reason(asset: dict, analysis: dict, user: dict | None) -> str:
    s = analysis["scores"]
    bits = []
    if s.get("valuation") is None:
        bits.append("di questo strumento non ho i conti, quindi non so dire se vale di più")
    if s.get("sentiment") is None and asset["news"]:
        bits.append("le notizie ci sono ma non sono state lette dal modello")
    if (s.get("technical") or 100) < 55:
        bits.append("il prezzo è in discesa e non ha ancora girato")
    if (s.get("fundamental") or 100) < 55:
        bits.append("i conti della società non sono abbastanza solidi")
    if (s.get("valuation") or 100) < 60:
        bits.append("il prezzo non è sotto il valore che calcolo")
    if (s.get("sentiment") or 100) < 45:
        bits.append("le notizie recenti sono negative")
    if user:
        from .users import RISK_CEILING
        if s["risk"] > RISK_CEILING[user["profile"]["risk_profile"]]:
            bits.append(f"è più rischioso di quanto prevede il suo profilo "
                        f"{user['profile']['risk_profile'].lower()}")
    if not bits:
        bits.append("nessun segnale abbastanza forte da giustificare una mossa")
    return "Oggi " + ", ".join(bits[:3]) + "."


def _risk_plain(asset: dict, analysis: dict) -> str:
    t = asset["tech"]
    daily = t["volatility"] / (252 ** 0.5)
    head = {
        "Basso": "Rischio basso: è un investimento che si muove piano.",
        "Moderato": "Rischio medio: oscilla, ma senza strappi fuori dall'ordinario.",
        "Alto": "Rischio alto: può muoversi molto in pochi giorni.",
        "Molto alto": "Rischio molto alto: sono normali variazioni che altrove sarebbero allarmanti.",
    }[analysis["risk_label"]]
    return (f"{head} In media il prezzo si muove {art_pc(daily)} al giorno. "
            f"Nel momento peggiore degli ultimi quindici mesi chi era entrato sui massimi si è "
            f"trovato con il {pc(abs(t['max_drawdown']))} in meno: è la misura di quanto può "
            f"andare storto senza che nulla sia davvero rotto.")


def _money(analysis: dict, amount: int, is_base: bool = False) -> dict:
    """Traduce le percentuali del piano in euro.

    Attenzione al caso in cui il valore stimato stia SOTTO il prezzo: il
    guadagno viene negativo e la frase "circa -500 euro di guadagno" non vuol
    dire niente. In quel caso si dice la cosa come sta — costa più di quanto
    vale — invece di far finta che ci sia un guadagno negativo.
    """
    plan = analysis["plan"]
    gain = amount * plan["upside_to_target"]
    loss = amount * abs(plan["downside_to_stop"])
    opening = (f"Ogni {eur(amount)} euro investiti" if is_base
               else f"Su {eur(amount)} euro investiti")
    if gain > 0:
        frase = (f"{opening}: circa {eur(gain)} euro di guadagno se arriva al valore che gli "
                 f"attribuisco, circa {eur(loss)} euro di perdita se scatta la vendita "
                 f"automatica di protezione.")
    else:
        frase = (f"Oggi costa più di quanto vale secondo i miei conti: circa "
                 f"{eur(abs(gain))} euro in più ogni {eur(amount)} euro investiti. "
                 f"Non è da comprare adesso, è da tenere d'occhio.")
    return {
        "amount": amount,
        "is_base_amount": is_base,
        "gain_target": round(gain),
        "loss_stop": round(loss),
        "sentence": frase,
    }


def _what_to_do(asset: dict, analysis: dict, amount: int, actionable: bool,
                amount_is_base: bool = False) -> list[str]:
    plan = analysis["plan"]
    cur = asset["currency"]
    if not actionable:
        return [f"Non faccia nulla su questo investimento: la tengo d'occhio io e le scrivo "
                f"soltanto se diventa interessante.",
                f"Il valore che gli attribuisco è {eur(plan['target'], 2)} {cur}; oggi il "
                f"prezzo è {eur(asset['tech']['price'], 2)}."]
    return [
        f"Se decide di entrare, compri tra {eur(plan['entry_low'], 2)} e "
        f"{eur(plan['entry_high'], 2)} {cur}: è la fascia in cui il prezzo si trova adesso.",
        f"Imposti subito una vendita automatica a {eur(plan['stop_loss'], 2)} {cur}. Se il prezzo "
        f"scende lì, lei esce con una perdita intorno al {pc(abs(plan['downside_to_stop']))} "
        f"invece di restare a guardare.",
        f"L'obiettivo è {eur(plan['target'], 2)} {cur}, il {pc(plan['upside_to_target'])} in più "
        f"di oggi: è il valore che calcolo io dai conti dell'azienda, non il parere di "
        f"qualcun altro.",
        (f"Qualunque cifra decida, non la concentri tutta qui: una sola idea non dovrebbe "
         f"pesare più del 5% di quello che ha. Se questa va male, il resto non ne soffre."
         if amount_is_base else
         f"Non ci metta più di {eur(amount)} euro, cioè il 5% dei suoi soldi: se questa va "
         f"male, il resto del suo patrimonio non ne soffre."),
    ]


def _scenarios_plain(report: dict, amount: int, is_base: bool = False) -> list[dict]:
    names = {"Bull": "Se va bene", "Base": "Lo scenario più probabile", "Bear": "Se va male"}
    out = []
    for s in report["scenarios"]:
        euros = amount * s["return"]
        out.append({
            "name": names[s["scenario"]],
            "probability": s["probability"],
            "text": (f"{names[s['scenario']]} ({pc(s['probability'], 0)} di probabilità): il prezzo "
                     f"arriva a {eur(s['price'], 2)}, cioè "
                     f"{'un guadagno' if euros >= 0 else 'una perdita'} di circa "
                     f"{eur(abs(euros))} euro {'ogni' if is_base else 'su'} {eur(amount)}."),
        })
    return out


def _jargon_used(asset: dict, actionable: bool) -> list[dict]:
    terms = ["Opportunity Score"]
    cls = {"Azioni": "azione", "ETF": "ETF", "Obbligazioni": "obbligazione",
           "Crypto": "moneta digitale", "Commodities": "materia prima", "REIT": "azione"}
    terms.append(cls.get(asset["asset_class"], "azione"))
    if actionable:
        terms += ["stop loss", "valore stimato"]
    terms.append("intelligenza artificiale")
    terms.append("volatilità")
    seen, out = set(), []
    for t in terms:
        if t in GLOSSARY and t not in seen:
            seen.add(t)
            out.append({"term": t, "definition": GLOSSARY[t]})
    return out


def asset_plain(asset: dict, analysis: dict, triggers: list[dict], report: dict,
                user: dict | None = None) -> dict:
    score = analysis["opportunity_score"]
    from .notifications import SCORE_THRESHOLD
    actionable = score > SCORE_THRESHOLD
    light = "verde" if actionable else "giallo" if score >= 70 else "grigio"
    light_label = {"verde": "Da guardare adesso",
                   "giallo": "Interessante, ma non ancora",
                   "grigio": "Niente da fare oggi"}[light]
    amount = example_amount(user)
    why = _why_now(asset, analysis, triggers)
    sources = analysis.get("ai_sources", {})
    by_ai = [k for k, v in sources.items() if str(v).startswith("Gemini")]
    if by_ai:
        analysis_by = ("Questa analisi l'ho fatta con l'intelligenza artificiale: il modello ha "
                       "letto le notizie, calcolato quanto vale e rivisto i punteggi.")
    else:
        analysis_by = ("Questa analisi l'ho fatta con il mio modello di calcolo, sempre con le "
                       "stesse regole per tutti gli investimenti.")
    return {
        "ticker": asset["ticker"], "name": asset["name"],
        "what_is_it": _what_is_it(asset),
        "light": light, "light_label": light_label,
        "headline": (f"Momento interessante su {asset['name']}" if light == "verde"
                     else f"{asset['name']}: la tengo d'occhio" if light == "giallo"
                     else f"{asset['name']}: nulla da segnalare"),
        "verdict": (f"Il mio giudizio oggi: {RATING_WORDS[analysis['final_rating']]}. "
                    f"Voto complessivo {score} su 100 ({classify(score).lower()})."),
        "price_sentence": (f"Oggi un'unità costa {eur(asset['tech']['price'], 2)} "
                           f"{asset['currency']}. Negli ultimi tre mesi ha fatto il "
                           f"{signed_pc(asset['tech']['perf_3m'])}, nell'ultimo mese il "
                           f"{signed_pc(asset['tech']['perf_1m'])}."),
        "why_now": why,
        "not_now_reason": None if actionable else _not_now_reason(asset, analysis, user),
        "risk_plain": _risk_plain(asset, analysis),
        "risk_label": analysis["risk_label"],
        "money": _money(analysis, amount, amount_is_example(user)),
        "what_to_do": _what_to_do(asset, analysis, amount, actionable,
                                  amount_is_example(user)),
        "scenarios_plain": _scenarios_plain(report, amount, amount_is_example(user)),
        "jargon": _jargon_used(asset, actionable),
        "analysis_by": analysis_by,
        "caveat": ("Questa è un'analisi fatta da un programma su dati di mercato, non un consiglio "
                   "personalizzato: la decisione resta sua e, per le scelte importanti, ne parli "
                   "con il suo consulente."),
    }


MARKET_WORDS = {"USA": "gli Stati Uniti", "Europa": "l'Europa", "Asia": "l'Asia",
                "Global": "i mercati globali"}
CLASS_WORDS_SHORT = {"Azioni": "le azioni singole", "ETF": "gli ETF",
                     "Obbligazioni": "le obbligazioni", "Crypto": "le monete digitali",
                     "Commodities": "le materie prime", "REIT": "le società immobiliari"}


def rejected_plain(decision: dict, assets: dict, limit: int = 3) -> list[dict]:
    """I motivi di scarto, detti come li direbbe una persona. Il cliente ha
    diritto di sapere perché NON è stato avvisato, senza leggere \"Opportunity
    Score 84 non superiore a 85\"."""
    out = []
    for r in decision["rejected"][:limit]:
        a = assets.get(r["ticker"], {})
        name = a.get("name", r["ticker"])
        v, kind = r.get("values", {}), r.get("kind")
        if kind == "score":
            text = (f"Ha preso {r['score']} punti su 100: interessante, ma sotto la soglia "
                    f"di {v.get('threshold', 85)} che ho con lei per scriverle.")
        elif kind == "market":
            text = (f"Si compra su un mercato che non ha messo nel suo profilo: "
                    f"{MARKET_WORDS.get(v.get('market'), v.get('market'))}.")
        elif kind == "sector":
            text = f"È di un settore che non le interessa: {str(v.get('sector', '')).lower()}."
        elif kind == "asset_class":
            text = (f"È un tipo di investimento che lei non ha scelto: "
                    f"{CLASS_WORDS_SHORT.get(v.get('asset_class'), v.get('asset_class'))}.")
        elif kind == "no_valuation":
            text = ("Di questo strumento non ho i conti: senza quelli non so dire se costa "
                    "meno di quanto vale, quindi lo tengo d'occhio ma non glielo propongo.")
        elif kind == "asset_class_domain":
            text = ("Le materie prime non sono ancora tra i tipi di investimento che posso "
                    "proporle: è un punto da sistemare nel suo profilo.")
        elif kind == "risk":
            text = (f"È più rischioso di quanto prevede il suo profilo "
                    f"{str(v.get('profile', '')).lower()}: rischio "
                    f"{str(v.get('risk_label', '')).lower()}.")
        elif kind == "weekly_limit":
            text = (f"Questa è interessante, ma questa settimana le ho già scritto "
                    f"{v.get('sent')} volte su un massimo di {v.get('limit')}: glielo "
                    f"segnalo la settimana prossima.")
        else:
            text = r["reason"]
        out.append({"ticker": r["ticker"], "name": name, "text": text, "score": r["score"]})
    return out


# ------------------------------------------------------------ portafoglio
def portfolio_plain(user_state: dict) -> dict:
    p = user_state["portfolio"]
    cur = user_state["profile"]["currency"]
    money = "euro" if cur == "EUR" else cur

    if not p["positions"]:
        # Il portafoglio è facoltativo: chi non vuole dire che cosa ha, non deve.
        return {
            "declared": False,
            "summary": "Non mi ha detto che cosa ha già, e va benissimo così: guardo il "
                       "mercato per lei e le scrivo quando trovo qualcosa che vale la pena.",
            "risk_sentence": "Se un giorno vuole, può dirmi che cosa possiede: da quel momento "
                             "tengo d'occhio anche quello e la avviso se cambia qualcosa di "
                             "importante.",
            "concentration_sentence": "",
            "items": [], "alerts_plain": [],
        }
    verb = "guadagno" if p["pl"] >= 0 else "perdita"
    summary = (f"I suoi {len(p['positions'])} investimenti valgono oggi "
               f"{eur(p['total_value'])} {money}. Li ha pagati {eur(p['total_cost'])}, quindi è in "
               f"{verb} di {eur(abs(p['pl']))} {money}, il {pc(abs(p['pl_pct']))} "
               f"{'in più' if p['pl'] >= 0 else 'in meno'}."
               + (f" Le restano {eur(p['cash'])} {money} non investiti."
                  if p.get("cash") else ""))

    if p["risk_score"] > p["risk_ceiling"]:
        risk_sentence = (f"Il rischio complessivo è più alto di quanto prevede il suo profilo "
                         f"{user_state['profile']['risk_profile'].lower()}: pesano soprattutto le "
                         f"posizioni più ballerine.")
    else:
        risk_sentence = (f"Il rischio complessivo è in linea con il suo profilo "
                         f"{user_state['profile']['risk_profile'].lower()}.")

    from .portfolio import ALERT_RULES, CONCENTRATION_EXCLUDED_SECTORS
    real = [(s, w) for s, w in p["allocation_by_sector"].items()
            if s not in CONCENTRATION_EXCLUDED_SECTORS] or \
        list(p["allocation_by_sector"].items())
    top_sector, top_w = real[0]
    if top_w >= ALERT_RULES["sector_weight"]:
        conc = (f"Attenzione a una cosa: il {pc(top_w)} dei suoi soldi è concentrato su "
                f"{top_sector.lower()}. Se quel settore va male, va male tutto insieme.")
    else:
        conc = (f"I suoi soldi sono distribuiti su più settori: il più grande è "
                f"{top_sector.lower()} con il {pc(top_w)}. Va bene così.")

    items = []
    for r in p["positions"]:
        verb_i = "in più" if r["pl"] >= 0 else "in meno"
        items.append({
            "ticker": r["ticker"], "name": r["name"],
            "light": "verde" if r["pl_pct"] >= 0 else "giallo" if r["pl_pct"] > -0.15 else "rosso",
            "sentence": (f"Vale {eur(r['value'])} {money}: {eur(abs(r['pl']))} {verb_i} di quanto "
                         f"l'ha pagata ({signed_pc(r['pl_pct'])}). Il mio giudizio oggi: "
                         f"{RATING_WORDS[r['rating']]}."),
            "value": r["value"], "pl": r["pl"], "pl_pct": r["pl_pct"],
            "weight": r["weight"], "rating": r["rating"],
        })

    alerts = []
    for a in p["alerts"]:
        pa = _alert_plain(a, cur)
        alerts.append({"level": a["level"], "ticker": a.get("ticker"),
                       "title": pa["title"], "text": pa["text"]})
    return {"declared": True, "summary": summary, "risk_sentence": risk_sentence,
            "concentration_sentence": conc, "items": items, "alerts_plain": alerts}


def _alert_plain(a: dict, cur: str) -> dict:
    """Riscrive l'alert in italiano corrente partendo dai valori strutturati,
    non dal testo tecnico (che resta nella vista analista)."""
    v, kind = a["values"], a.get("kind")
    money = "euro" if cur == "EUR" else cur
    if kind == "loss":
        return {"title": f"{v['name']} è in perdita",
                "text": (f"Vale il {pc(abs(v['pl_pct']))} in meno di quanto l'ha pagata: "
                         f"{eur(abs(v['pl']))} {money}. Il mio giudizio oggi è "
                         f"{RATING_WORDS[v['rating']].split(',')[0]}. Non è per forza un "
                         f"problema, ma è la posizione che guardo con più attenzione.")}
    if kind == "gain":
        return {"title": f"{v['name']} è in buon guadagno",
                "text": (f"Vale il {pc(v['pl_pct'])} in più di quanto l'ha pagata: "
                         f"{eur(v['pl'])} {money} di guadagno. Ora pesa il "
                         f"{pc(v['weight'])} dei suoi investimenti: se vuole, può incassarne "
                         f"una parte.")}
    if kind == "drawdown":
        return {"title": f"{v['name']} è scesa dal suo massimo",
                "text": (f"Dal punto più alto raggiunto dopo il suo acquisto ha restituito il "
                         f"{pc(abs(v['drawdown']))}. Può essere normale e non cambia il mio "
                         f"giudizio, ma è giusto che lo sappia.")}
    if kind == "weight":
        return {"title": f"{v['name']} è diventata una fetta grande",
                "text": (f"Da sola vale il {pc(v['weight'])} dei suoi investimenti. Quando una "
                         f"posizione diventa così grande, il suo patrimonio dipende da "
                         f"un'unica società.")}
    if kind == "sector":
        return {"title": "Troppi soldi sullo stesso settore",
                "text": (f"Il {pc(v['weight'])} dei suoi investimenti è su "
                         f"{v['sector'].lower()}. Se quel settore va male, va male tutto "
                         f"insieme: è il caso di distribuire meglio.")}
    if kind == "portfolio_risk":
        return {"title": "Rischio complessivo sopra il suo profilo",
                "text": (f"Messi insieme, i suoi investimenti sono più mossi di quanto prevede "
                         f"un profilo {v['profile'].lower()}. Pesano soprattutto le posizioni "
                         f"più ballerine.")}
    return {"title": a["title"], "text": a["detail"]}


# ------------------------------------------- racconto del lavoro dell'agente
def scan_story(stats: dict, user_state: dict, score_threshold: int, weekly_limit: int,
               data: dict | None = None) -> list[str]:
    u = user_state
    d = u["decision"]
    sent = len(d["notifications"])
    eligible = len(d["eligible"])
    if data and data.get("mode") == "real":
        # "ultima seduta di borsa", non "ultima seduta": le cripto trattano
        # anche il sabato e la domenica, e dire una data sola per tutti faceva
        # sembrare aperta una borsa che era chiusa.
        cripto = data.get("last_bar_continui")
        if data.get("seduta_in_corso"):
            # i mercati sono ancora aperti: dirlo, perche' il prezzo di adesso
            # non e' il prezzo di stasera, e perche' mentre l'Europa tratta
            # l'America e' chiusa: non tutti gli strumenti sono allo stesso
            # giorno
            quando = (f"mercati ancora aperti: {data.get('su_oggi', 0)} strumenti "
                      f"sono al prezzo di oggi, {data.get('su_seduta_precedente', 0)} "
                      f"all'ultima chiusura, quindi i numeri sono provvisori")
        else:
            quando = f"ultima seduta di borsa {data.get('last_bar')}"
        if cripto and cripto != data.get("last_bar"):
            quando += f", cripto al {cripto}"
        first = (f"Ho preso i prezzi veri di {stats['assets']} strumenti ({quando}), "
                 f"i bilanci di {data.get('with_fundamentals')} "
                 f"e le notizie di {data.get('with_news')}.")
    else:
        first = (f"Ho letto prezzi, bilanci e notizie di {stats['assets']} investimenti su "
                 f"{len(stats['markets'])} aree del mondo.")
    story = [
        first,
        "Per ognuno ho controllato cinque cose: i conti di chi lo emette, l'andamento del prezzo, "
        "il confronto tra il prezzo e il valore che calcolo, le notizie delle ultime due "
        "settimane e quanto è rischioso.",
        f"Ho trovato {stats['triggers']} segnali degni di nota e ho dato un voto da 0 a 100 a "
        f"ciascun investimento.",
        f"Solo {stats['above_threshold']} hanno superato {score_threshold} su 100, la soglia sotto "
        f"la quale ho deciso di non disturbarla.",
    ]
    if eligible:
        story.append(f"Di quelli, {eligible} rientrano nel suo profilo "
                     f"({u['profile']['risk_profile'].lower()}, mercati "
                     f"{join_it(u['profile']['markets'])}).")
    else:
        story.append(f"Nessuno di quelli rientra nel suo profilo: mercati "
                     f"{join_it(u['profile']['markets'])}, settori "
                     f"{join_it(u['profile']['sectors'])}.")
    if sent:
        story.append(f"Le ho segnalato {sent} "
                     f"{'opportunità' if sent == 1 else 'opportunità diverse'}: non più di "
                     f"{weekly_limit} a settimana, perché preferisco scriverle poco e a ragione.")
    else:
        story.append("Non le ho mandato nessuna segnalazione: quando non c'è niente di solido, "
                     "il silenzio è la risposta giusta.")
    return story


def greeting(user_state: dict) -> dict:
    n = len(user_state["decision"]["notifications"])
    # il nome proprio solo se c'è davvero: "Buongiorno Il mio profilo" no
    parts = user_state["name"].split()
    first = user_state.get("first_name") or (parts[0] if len(parts) == 2 else "")
    hello = f"Buongiorno {first}." if first else "Buongiorno."
    if n == 1:
        line = f"{hello} Ho una cosa da farle vedere."
    elif n > 1:
        line = f"{hello} Ho {n} cose da farle vedere."
    else:
        line = f"{hello} Oggi non ho niente di urgente per lei."
    return {"line": line,
            "sub": ("Ho lavorato stanotte sui mercati. Qui sotto trova tutto in ordine di "
                    "importanza, e sotto ancora può chiedermi quello che vuole.")}


def commitments(user_state: dict, assets: dict, analyses: dict,
                total_assets: int, weekly_limit: int) -> list[str]:
    """Che cosa l'agente farà da solo, senza che l'utente chieda nulla.
    DEMO-20 (OP-02): perimetro dell'autonomia nella demo — osserva, avvisa e
    ricorda; non compra e non vende."""
    out = []
    d = user_state["decision"]
    for n in d["notifications"]:
        out.append(f"Seguo {n['name']} ogni giorno e la avviso subito se scende sotto "
                   f"{eur(n['plan']['stop_loss'], 2)} o se arriva a "
                   f"{eur(n['plan']['target'], 2)}.")
    for n in d["notifications"]:
        out.append(f"Se non mi dice nulla su {n['ticker']}, glielo ricordo una volta sola fra "
                   f"sette giorni, poi smetto.")
        break
    n_pos = len(user_state["portfolio"]["positions"])
    if n_pos:
        out.append(f"Controllo i suoi {n_pos} investimenti ogni giorno e le scrivo solo se "
                   f"cambia qualcosa di davvero importante.")
    else:
        out.append("Se un giorno mi dice che cosa possiede, da quel momento controllo anche "
                   "quello ogni giorno: per ora non le serve dirmelo.")
    out.append(f"Domani mattina ripasso tutti i {total_assets} investimenti che tengo d'occhio, "
               f"uno per uno.")
    postponed = [r for r in d["rejected"] if "rinviata" in r["reason"]]
    if postponed:
        out.append(f"Ho {len(postponed)} segnalazione in attesa: le arriverà la settimana prossima, "
                   f"perché questa settimana ha già ricevuto il massimo di {weekly_limit} messaggi.")
    out.append("Non compro e non vendo niente al suo posto: decide sempre lei.")
    return out
