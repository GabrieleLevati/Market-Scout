"""L'assistente a domande della vista semplice.

L'FDD prevede che l'utente possa chiedere in linguaggio naturale (BR-09) e che a
rispondere sia il provider LLM (3.2, OP-07). Nella demo non c'è rete: il motore
prepara in anticipo le risposte come blocchi strutturati, e il browser
riconosce la domanda con un abbinamento su parole chiave e alias degli asset.

Il confine è lo stesso che avrebbe la versione con l'LLM: la domanda entra, il
contesto (questi stessi dati) viene recuperato, la risposta esce come blocchi
renderizzabili. Sostituire l'LLM significa cambiare chi produce `blocks`, non
cambiare la vista.
"""

from __future__ import annotations

from .plain import GLOSSARY, eur, pc

STOP_WORDS = {"il", "lo", "la", "i", "gli", "le", "un", "una", "di", "da", "del", "della",
              "e", "o", "a", "in", "su", "per", "con", "che", "cosa", "come", "mio", "mia",
              "miei", "mie", "sono", "è", "ho", "mi", "si", "non", "ma", "se", "al", "alla"}


def _txt(text: str) -> dict:
    return {"type": "text", "text": text}


def _list(items: list[str], title: str | None = None) -> dict:
    return {"type": "list", "title": title, "items": items}


# Come la gente chiama davvero le cose: "oro", "petrolio", "google", "fiat".
EXTRA_ALIASES = {
    "XAUUSD": ["oro"], "XAGUSD": ["argento"],
    "CL=F": ["petrolio", "greggio", "wti"], "HG=F": ["rame"],
    "BTC-USD": ["bitcoin", "btc"], "ETH-USD": ["ethereum", "ether"],
    "SOL-USD": ["solana"], "LINK-USD": ["chainlink"],
    "GOOGL": ["google", "alphabet"],
    "META": ["facebook", "instagram", "whatsapp", "meta"],
    "MC.PA": ["lvmh", "louis vuitton", "vuitton"],
    "NOVO-B.CO": ["novo", "nordisk"],
    "ISP.MI": ["intesa", "sanpaolo"], "ENEL.MI": ["enel"],
    "STLAM.MI": ["stellantis", "fiat"], "AIR.PA": ["airbus"],
    "SIE.DE": ["siemens"], "SAP.DE": ["sap"], "ASML.AS": ["asml"],
    "005930.KS": ["samsung"], "7203.T": ["toyota"], "9984.T": ["softbank"],
    "TSM": ["tsmc", "taiwan"], "AAPL": ["apple", "iphone"],
    "MSFT": ["microsoft", "windows"], "AMD": ["amd"], "NVDA": ["nvidia"],
    "SPY": ["s&p 500", "sp500", "cinquecento americane"],
    "QQQ": ["nasdaq"], "VWCE.DE": ["vwce", "mondo intero"],
    "SMH": ["semiconduttori", "microchip"], "EEM": ["emergenti"],
    "IEF": ["titoli di stato americani"], "TLT": ["treasury lunghi"],
    "LQD": ["corporate americane"], "IEAC.AS": ["corporate europee"],
    "EMB": ["bond emergenti"], "PLD": ["prologis", "magazzini"],
    "SPG": ["centri commerciali"], "VNA.DE": ["vonovia", "appartamenti"],
    "0823.HK": ["link reit", "hong kong"],
    "KO": ["coca cola", "coca-cola"], "JPM": ["jpmorgan", "banca americana"],
    "UNH": ["unitedhealth"], "LLY": ["eli lilly", "lilly"],
    "XOM": ["exxon"], "CAT": ["caterpillar"], "LLY2": [],
}


def aliases(assets: dict) -> list[dict]:
    """Alias con cui un cliente può nominare un asset: ticker, nome, parole
    significative del nome (Microsoft, Bitcoin, oro, Intesa...)."""
    out = []
    for ticker, a in assets.items():
        words = {ticker.lower(), a["name"].lower()}
        base = ticker.split(".")[0].split("-")[0].lower()
        words.add(base)
        for w in a["name"].replace("(", " ").replace(")", " ").split():
            w = w.strip(".,").lower()
            if len(w) >= 4 and w not in {"group", "holding", "spot", "platforms", "motor",
                                         "electronics", "property", "core", "trust", "ishares",
                                         "shares", "etf", "bond", "usd", "eur", "invesco",
                                         "vanguard", "spdr", "vaneck", "msci", "jpm"}:
                words.add(w)
        words.update(EXTRA_ALIASES.get(ticker, []))
        out.append({"ticker": ticker, "aliases": sorted(words)})
    return out


# ---------------------------------------------------------------- intenti
# keywords: parole che fanno riconoscere l'intento (minuscole, senza accenti
# gestite lato browser). `scope` dice dove sta la risposta.
INTENTS = [
    {"id": "portfolio_status", "scope": "user",
     "question": "Come vanno i miei investimenti?",
     "keywords": ["portafoglio", "investimenti", "guadagnato", "perso", "quanto valgono",
                  "situazione", "soldi", "patrimonio", "come va", "come vanno", "bilancio mio"]},
    {"id": "portfolio_risk", "scope": "user",
     "question": "Quanto rischio sto correndo?",
     "keywords": ["rischio", "rischioso", "pericolo", "sicuro", "tranquillo", "perdere tutto"]},
    {"id": "why_notified", "scope": "user",
     "question": "Perché mi ha segnalato queste opportunità?",
     "keywords": ["perche", "segnalato", "segnalazione", "avvisato", "notifica", "notifiche",
                  "consigli", "consigliato", "opportunita"]},
    {"id": "what_did_you_do", "scope": "user",
     "question": "Che cosa ha fatto oggi per me?",
     "keywords": ["cosa hai fatto", "cosa ha fatto", "oggi", "lavorato", "controllato",
                  "analizzato", "quanti", "come lavori", "come lavora"]},
    {"id": "commitments", "scope": "user",
     "question": "Di che cosa si occupa lei da qui in avanti?",
     "keywords": ["farai", "fara", "prossimi giorni", "ricordi", "avvisami", "tieni d'occhio",
                  "domani", "futuro", "impegni", "da fare"]},
    {"id": "my_profile", "scope": "user",
     "question": "Che profilo mi ha assegnato?",
     "keywords": ["profilo", "preferenze", "mi conosci", "cosa sai di me", "settori",
                  "mercati", "capitale", "conservativo", "bilanciato", "aggressivo"]},
    {"id": "how_score_works", "scope": "shared",
     "question": "Come fa a dare un voto a un investimento?",
     "keywords": ["voto", "punteggio", "score", "come decidi", "come decide", "calcoli",
                  "calcola", "criterio", "85"]},
    {"id": "are_you_advisor", "scope": "shared",
     "question": "Lei è un consulente finanziario?",
     "keywords": ["consulente", "promotore", "garantisci", "garantisce", "sicuro al 100",
                  "sei una persona", "chi sei", "chi è", "umano", "responsabilita"]},
    {"id": "data_sources", "scope": "shared",
     "question": "Da dove prende i dati?",
     "keywords": ["dati", "fonti", "dove prendi", "dove prende", "borsa", "attendibili",
                  "aggiornati", "provider"]},
    {"id": "what_now", "scope": "user",
     "question": "Che cosa dovrei fare adesso?",
     "keywords": ["cosa devo fare", "cosa faccio", "compro", "comprare", "vendo", "vendere",
                  "consiglio", "mi consiglia", "adesso"]},
]


def _plain_pack(user_state: dict, plain_assets: dict, generic: dict, ticker: str) -> dict:
    return (user_state.get("plain_assets") or plain_assets).get(ticker) or generic[ticker]


def user_answers(user_state: dict, assets: dict, analyses: dict, generic: dict,
                 stats: dict, score_threshold: int, weekly_limit: int,
                 provider_map: dict) -> dict:
    """Blocchi di risposta per gli intenti che dipendono dall'utente."""
    pf = user_state["plain_portfolio"]
    d = user_state["decision"]
    prof = user_state["profile"]
    notified = [n["ticker"] for n in d["notifications"]]
    answers: dict[str, list[dict]] = {}

    if pf.get("declared"):
        answers["portfolio_status"] = [
            _txt(pf["summary"]),
            {"type": "portfolio_items"},
            _txt(pf["concentration_sentence"]),
        ]
    else:
        answers["portfolio_status"] = [_txt(pf["summary"]), _txt(pf["risk_sentence"])]
    answers["portfolio_risk"] = [
        _txt(pf["risk_sentence"]),
        _txt(("Ecco come la vedo posizione per posizione: " + "; ".join(
            f"{r['ticker']} rischio {r['risk_label'].lower()}"
            for r in user_state["portfolio"]["positions"]) + ".")
             if user_state["portfolio"]["positions"] else
             "Sul rischio di quello che possiede non posso dirle niente: non me l'ha detto, "
             "e non è obbligatorio."),
        _txt("Il rischio non si elimina, si dosa: per questo le ricordo sempre di non mettere "
             "più del 5% dei suoi soldi su una singola idea e di tenere una vendita automatica "
             "di protezione."),
    ]
    if notified:
        blocks = [_txt(f"Le ho segnalato {len(notified)} "
                       f"{'opportunità' if len(notified) == 1 else 'opportunità'} perché "
                       f"{'ha' if len(notified) == 1 else 'hanno'} superato il voto di "
                       f"{score_threshold} su 100 e {'rientra' if len(notified) == 1 else 'rientrano'} "
                       f"nel suo profilo.")]
        for t in notified:
            blocks.append({"type": "asset_card", "ticker": t})
        postponed = [r for r in d["rejected"] if "rinviata" in r["reason"]]
        if postponed:
            blocks.append(_txt(
                f"Ne ho un'altra pronta ({', '.join(r['ticker'] for r in postponed)}) ma non le "
                f"scrivo più di {weekly_limit} volte a settimana: le arriverà la prossima."))
        answers["why_notified"] = blocks
    else:
        reasons = [f"{r['name']}: {r['text']}" for r in user_state["plain_rejected"]]
        answers["why_notified"] = [
            _txt("Oggi non le ho segnalato niente, e non è una dimenticanza: nessun investimento "
                 "ha superato la soglia che rientra anche nel suo profilo."),
            _list(reasons, "I casi più vicini, e perché li ho scartati"),
            _txt("Preferisco scriverle una volta al mese con qualcosa di solido che ogni giorno "
                 "con qualcosa di tiepido."),
        ]

    answers["what_did_you_do"] = [_list(user_state["plain_story"]),
                                  {"type": "pipeline_link"}]
    answers["commitments"] = [_txt("Da qui in avanti mi occupo io di queste cose:"),
                              _list(user_state["plain_commitments"])]
    capital_line = (f", capitale di riferimento {eur(prof['capital'])} {prof['currency']}"
                    if prof.get("capital") else
                    ", senza importi dichiarati (le percentuali le traduco ogni 1.000 euro)")
    answers["my_profile"] = [
        _txt(f"Lei ha un profilo {prof['risk_profile'].lower()}, orizzonte "
             f"{prof['horizon'].lower()}{capital_line}."),
        _list([f"Mercati che le interessano: {', '.join(prof['markets'])}",
               f"Settori preferiti: {', '.join(prof['sectors'])}",
               f"Tipi di investimento: {', '.join(prof['asset_classes'])}",
               f"Canali su cui le scrivo: {', '.join(user_state['channels'])}"]),
        _txt("Imparo anche dalle sue reazioni: " + (
            f"apre spesso i messaggi su {', '.join(user_state['learned']['top_sectors'])}, "
            f"quindi quelle opportunità le metto più in alto."
            if user_state["learned"]["top_sectors"] else
            "per ora non ho abbastanza reazioni sue per tarare le priorità.")),
    ]

    if notified:
        pack = _plain_pack(user_state, {}, generic, notified[0])
        answers["what_now"] = [
            _txt(f"Sull'unica cosa che le ho segnalato, {pack['name']}, farei così:"),
            _list(pack["what_to_do"]),
            _txt(pack["caveat"]),
        ]
    else:
        answers["what_now"] = [
            _txt("Oggi non farei nulla di nuovo. Tenga quello che ha e aspetti: le scrivo io "
                 "quando c'è un motivo."),
            _txt(pf["risk_sentence"]),
        ]
    return answers


def shared_answers(stats: dict, score_threshold: int, weekly_limit: int,
                   provider_map: dict, weights: dict) -> dict:
    return {
        "how_score_works": [
            _txt("Per ogni investimento faccio cinque controlli e li peso sempre allo stesso modo, "
                 "così i voti si possono confrontare tra loro:"),
            _list([f"I conti di chi lo emette (vendite, utili, debiti): {int(weights['fundamental'] * 100)}% del voto",
                   f"L'andamento del prezzo e degli scambi: {int(weights['technical'] * 100)}%",
                   f"Il confronto tra il prezzo e il valore che calcolo io: "
                   f"{int(weights['valuation'] * 100)}%",
                   f"Le notizie delle ultime due settimane: {int(weights['sentiment'] * 100)}%",
                   f"Quanto è rischioso, che abbassa il voto: {int(weights['risk'] * 100)}%"]),
            _txt(f"Ne esce un voto da 0 a 100. Sopra 85 le scrivo, e non più di {weekly_limit} "
                 f"volte a settimana. Tra 70 e 85 tengo d'occhio in silenzio. Sotto 70, per me "
                 f"non c'è niente da fare."),
        ],
        "are_you_advisor": [
            _txt("No. Sono un programma: leggo molti più dati di quanti ne possa leggere una "
                 "persona e le spiego cosa ho trovato, ma non sono un consulente finanziario e "
                 "non le garantisco nessun risultato."),
            _txt("Le decisioni restano sue. Per le scelte importanti, e per la sua situazione "
                 "fiscale e familiare, ne parli con il suo consulente: io le do i numeri e le "
                 "ragioni, non la firma."),
        ],
        "data_sources": [
            _txt("Prendo i dati dai fornitori di informazioni finanziarie usati dagli operatori "
                 "di mercato, ognuno per la sua parte. Sono dati di fatto: prezzi, bilanci, "
                 "comunicazioni delle aziende, notizie. Nessun parere di analisti esterni:"),
            _list([f"{p}: {', '.join(f[:2])}" for p, f in provider_map.items()]),
            _txt("Le analisi e i giudizi su questi dati li produco io con l'intelligenza "
                 "artificiale (il modello Gemini di Google): il valore di ogni investimento "
                 "lo calcolo dai conti, non lo copio dal parere di qualcun altro."),
            _txt("In questa dimostrazione i dati sono simulati, perché serve a far vedere come "
                 "ragiono, non a dare prezzi veri. Nella versione in produzione arrivano dalle "
                 "stesse fonti ogni giorno, prima dell'apertura dei mercati."),
        ],
    }


GLOSSARY_QUESTIONS = {
    "azione": ("Che cos'è un'azione?", ["azione", "azioni", "titolo", "titoli"]),
    "ETF": ("Che cos'è un ETF?", ["etf", "paniere", "fondo", "indice"]),
    "obbligazione": ("Che cos'è un'obbligazione?",
                     ["obbligazione", "obbligazioni", "bond", "titoli di stato", "cedola"]),
    "moneta digitale": ("Che cos'è una moneta digitale?",
                        ["moneta digitale", "criptovaluta", "cripto", "crypto"]),
    "materia prima": ("Che cos'è una materia prima?",
                      ["materia prima", "materie prime", "commodity"]),
    "stop loss": ("Che cos'è lo stop loss?",
                  ["stop loss", "stop", "protezione", "vendita automatica", "cintura"]),
    "target": ("Che cos'è il target?", ["target", "obiettivo", "prezzo obiettivo"]),
    "valore stimato": ("Come calcola il valore di un investimento?",
                       ["valore stimato", "valore", "quanto vale", "prezzo obiettivo",
                        "obiettivo", "target"]),
    "intelligenza artificiale": ("Chi fa queste analisi?",
                                 ["intelligenza artificiale", "ai", "gemini", "modello",
                                  "chi analizza", "chi fa le analisi", "algoritmo"]),
    "insider": ("Chi sono gli insider?",
                ["insider", "amministratore delegato", "dirigenti", "manager"]),
    "volatilità": ("Che cos'è la volatilità?",
                   ["volatilita", "oscilla", "oscillazione", "ballerino", "sbalzi"]),
    "drawdown": ("Che cos'è il drawdown?", ["drawdown", "massimo", "quanto e scesa"]),
    "diversificare": ("Che cosa vuol dire diversificare?",
                      ["diversificare", "diversificazione", "concentrazione", "uova nel cesto"]),
    "Opportunity Score": ("Che cos'è l'Opportunity Score?",
                          ["opportunity score", "voto da 0 a 100"]),
}


def glossary_entries() -> list[dict]:
    out = []
    for term, definition in GLOSSARY.items():
        question, keywords = GLOSSARY_QUESTIONS.get(term, (f"Che cosa vuol dire \"{term}\"?",
                                                           [term.lower()]))
        out.append({"id": f"glossario:{term}", "term": term, "question": question,
                    "keywords": keywords, "blocks": [_txt(definition)]})
    return out


def chips(user_state: dict, assets: dict) -> list[str]:
    """Domande suggerite: davanti a una casella vuota molte persone si bloccano."""
    out = ["Come vanno i miei investimenti?"]
    notified = user_state["decision"]["notifications"]
    if notified:
        out.append(f"Perché mi ha segnalato {notified[0]['name'].split()[0]}?")
        out.append("Che cosa dovrei fare adesso?")
    else:
        out.append("Perché oggi non mi ha segnalato niente?")
    out += ["Quanto rischio sto correndo?", "Che cosa ha fatto oggi per me?",
            "Che cos'è un ETF?", "Come fa a dare un voto a un investimento?",
            "Lei è un consulente finanziario?"]
    return out


def fallback_blocks(user_state: dict) -> list[dict]:
    return [
        _txt("Su questo non so risponderle con certezza, e preferisco dirglielo invece di "
             "inventare. Posso aiutarla su queste cose:"),
        _list(["Come vanno i suoi investimenti e quanto rischio sta correndo",
               "Perché le ho segnalato (o non le ho segnalato) qualcosa",
               "Che cos'è un singolo investimento e se oggi è interessante — mi scriva il nome, "
               "per esempio \"Microsoft\" o \"Bitcoin\"",
               "Il significato delle parole difficili: ETF, stop loss, volatilità",
               "Come lavoro e da dove prendo i dati"]),
    ]


def build_knowledge(state: dict, generic_plain: dict, stats: dict, score_threshold: int,
                    weekly_limit: int, weights: dict) -> dict:
    return {
        "aliases": aliases(state["assets"]),
        "intents": INTENTS,
        "shared_answers": shared_answers(stats, score_threshold, weekly_limit,
                                         state["provider_map"], weights),
        "glossary": glossary_entries(),
        "stop_words": sorted(STOP_WORDS),
    }
