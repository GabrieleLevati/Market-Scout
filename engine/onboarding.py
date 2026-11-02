"""Questionario iniziale (BR-01: profilazione in onboarding).

Il cliente non deve dichiarare quanto ha, né che cosa possiede. Risponde a poche
domande a scelta multipla e da quelle si ricava tutto ciò che il motore usa
davvero: profilo di rischio, orizzonte, mercati, settori, tipi di strumento,
canale e quante volte a settimana può essere disturbato.

Le regole vivono qui come **dati**, non come codice: ogni opzione porta gli
effetti che produce (`sets`) e un unico interprete li applica. Lo stesso blocco
viene esportato in `web/data.js`, dove la vista cliente lo interpreta con le
stesse regole (`web/onboarding.js`): una sola fonte di verità, due lettori.

Vocabolario degli effetti ammessi in `sets`:

| chiave | effetto |
|---|---|
| `risk_points` | somma punti di propensione al rischio (determina il profilo) |
| `experience_points` | somma punti di esperienza (può solo limitare il rischio) |
| `horizon` | imposta l'orizzonte temporale in parole |
| `markets_add` | aggiunge mercati (USA, Europa, Asia, Global) |
| `sectors_add` | aggiunge settori |
| `asset_classes_add` | aggiunge tipi di strumento (Azioni, ETF, Obbligazioni, Crypto) |
| `channels_add` | aggiunge canali di notifica |
| `weekly_limit` | quante segnalazioni a settimana al massimo |
| `currency`, `country` | valuta e paese di riferimento |
| `wants_portfolio` | l'utente vuole far controllare anche ciò che già possiede |
"""

from __future__ import annotations

# I sette settori del dominio documentato (BR-01) piu "Immobiliare": senza di
# esso le societa immobiliari del listino non sarebbero raggiungibili da nessun
# profilo (scostamento dall'FDD, vedi decisions.FDD_CHANGES).
ALL_SECTORS = ["Tecnologia", "AI", "Healthcare", "Finanza", "Energia", "Industriale",
               "Consumer", "Immobiliare"]

ADD_KEYS = ("markets", "sectors", "asset_classes", "channels")
SUM_KEYS = ("risk_points",)
# L'esperienza si misura sulla cosa più impegnativa già fatta, non su quante
# risposte si segnano: segnare cinque voci non rende nessuno più esperto.
MAX_KEYS = ("experience_points",)
# Un tetto non si compensa: vale sempre il più prudente tra quelli raccolti.
CAP_ORDER = ("Conservativo", "Bilanciato", "Aggressivo")

# Profilo di chi abbandona a metà o salta tutto: il più prudente utilizzabile.
DEFAULTS = {
    "risk_profile": "Conservativo",
    "horizon": "Medio (3-5 anni)",
    "currency": "EUR",
    "country": "Italia",
    # Mercati e mestieri aperti: restringere il perimetro a chi non ha risposto
    # lo lascerebbe senza nulla da vedere. La prudenza sta nel tetto di rischio,
    # non nel guardare meno cose.
    "markets": ["USA", "Europa", "Asia", "Global"],
    "sectors": ["Tecnologia", "AI", "Healthcare", "Finanza", "Energia", "Industriale",
                "Consumer", "Immobiliare"],
    "asset_classes": ["ETF", "Obbligazioni"],
    # Nessun recapito promesso a chi non l'ha scelto: meglio "solo a schermo"
    # che una email che non parte.
    "channels": ["Solo a schermo"],
    "weekly_limit": 1,
}

# Somma dei punti di rischio -> profilo. Le fasce sono tarate sul questionario:
# chi risponde "prudente" a tutto resta sotto 3, chi accetta le perdite supera 7.
RISK_BANDS = [
    {"min": -99, "max": 2, "label": "Conservativo"},
    {"min": 3, "max": 6, "label": "Bilanciato"},
    {"min": 7, "max": 99, "label": "Aggressivo"},
]

# Sotto questa soglia di esperienza il profilo non può essere Aggressivo:
# la propensione dichiarata non sostituisce il saper leggere un prezzo.
INEXPERIENCED_BELOW = 1

PRIVACY_NOTE = ("Non le chiedo quanto ha, né che cosa possiede: non mi serve per lavorare. "
                "Le risposte restano su questo computer e servono solo a decidere di che cosa "
                "vale la pena parlarle.")

CLOSING = {
    "title": "Ecco come l'ho capita",
    "body": "Se qualcosa non torna, può rifare le domande: da questo profilo dipende che cosa "
            "le segnalo e quante volte le scrivo.",
}

QUESTIONS: list[dict] = [
    {
        "id": "orizzonte",
        "text": "Fra quanto tempo pensa che le serviranno questi soldi?",
        "help": "Serve a capire quanto tempo ho per lavorare. Se il tempo è poco, le propongo "
                "solo cose che si muovono piano.",
        "kind": "single",
        "options": [
            {"id": "breve", "label": "Entro un anno o due: so già a cosa mi servono",
             "sets": {"horizon": "Breve (entro 2 anni)", "risk_points": 0,
                      "risk_cap": "Conservativo"}},
            {"id": "medio", "label": "Fra tre e cinque anni",
             "sets": {"horizon": "Medio (3-5 anni)", "risk_points": 1}},
            {"id": "lungo", "label": "Più avanti: oltre cinque anni, non ho una data",
             "sets": {"horizon": "Lungo (oltre 5 anni)", "risk_points": 3}},
            {"id": "nonso", "label": "Non lo so",
             "sets": {"horizon": "Medio (3-5 anni)", "risk_points": 1}},
        ],
    },
    {
        "id": "perdita",
        "text": "Immagini di aver investito. Dopo un mese, ogni 100 euro sono diventati 80. "
                "Lei che cosa fa?",
        "help": "È la domanda che conta più di tutte: non mi interessa quanto ha, mi interessa "
                "come dorme la notte.",
        "kind": "single",
        "options": [
            {"id": "vendo", "label": "Vendo tutto: su una cosa così non ci dormo",
             # Una risposta così non si compensa con le altre: resta il tetto più prudente.
             "sets": {"risk_points": 0, "risk_cap": "Conservativo"}},
            {"id": "chiedo", "label": "Mi preoccupo e chiedo un parere a qualcuno",
             "sets": {"risk_points": 1, "risk_cap": "Bilanciato"}},
            {"id": "aspetto", "label": "Non faccio niente e aspetto che passi",
             "sets": {"risk_points": 3}},
            {"id": "compro", "label": "Ne approfitto: a quel prezzo ne comprerei ancora",
             "sets": {"risk_points": 5}},
        ],
    },
    {
        "id": "esperienza",
        "text": "Quali di queste cose le è già capitato di avere, anche molti anni fa?",
        "help": "Non è un esame: mi dice solo quanto siamo liberi di muoverci. Di questa "
                "domanda conto la cosa più impegnativa che ha segnato, non quante ne segna.",
        "kind": "multi",
        "options": [
            {"id": "deposito", "label": "Un libretto, un conto deposito o i buoni postali",
             "sets": {"experience_points": 0}},
            {"id": "fondi", "label": "Fondi o polizze comprati in banca",
             "sets": {"experience_points": 1}},
            {"id": "prestiti", "label": "Prestiti a uno Stato o a un'azienda, con interessi",
             "sets": {"experience_points": 1, "asset_classes_add": ["Obbligazioni"]}},
            {"id": "panieri", "label": "Panieri che contengono tanti investimenti insieme",
             "sets": {"experience_points": 2, "asset_classes_add": ["ETF"]}},
            {"id": "azioni", "label": "Azioni di singole aziende",
             "sets": {"experience_points": 2, "asset_classes_add": ["Azioni"]}},
            {"id": "digitali", "label": "Monete digitali, tipo bitcoin",
             "sets": {"experience_points": 3}},
            {"id": "niente", "label": "Niente di tutto questo: comincio adesso",
             "sets": {"experience_points": 0, "risk_cap": "Bilanciato"}, "exclusive": True},
        ],
    },
    {
        "id": "strumenti",
        "text": "Di che cosa vuole che le parli, quando trovo qualcosa di interessante?",
        "help": "Può scegliere più di una risposta. Quello che non segna, non glielo propongo "
                "nemmeno.",
        "kind": "multi",
        "options": [
            {"id": "panieri",
             "label": "Panieri che contengono tante aziende insieme: ne compro uno e possiedo "
                      "un pezzetto di centinaia di società",
             "sets": {"asset_classes_add": ["ETF"]}},
            {"id": "azioni", "label": "Singole aziende, quelle di cui conosco il nome",
             "sets": {"asset_classes_add": ["Azioni"]}},
            {"id": "prestiti",
             "label": "Prestiti a Stati e grandi aziende, che pagano un interesse",
             "sets": {"asset_classes_add": ["Obbligazioni"]}},
            {"id": "digitali",
             "label": "Monete digitali tipo bitcoin, che possono salire e scendere molto",
             # Le monete digitali si scambiano sui mercati mondiali: senza "Global"
             # tra i mercati non ne passerebbe mai nessuna.
             "sets": {"asset_classes_add": ["Crypto"], "markets_add": ["Global"],
                      "risk_points": 1}},
            {"id": "sceglilei", "label": "Non lo so: scelga lei quello che ha senso",
             # Il perimetro piu prudente su cui il motore ha comunque qualcosa da
             # dire: le azioni singole entrano solo se le chiede la domanda dopo.
             "sets": {"asset_classes_add": ["ETF", "Obbligazioni"]}, "exclusive": True},
        ],
    },
    {
        "id": "mercati",
        "text": "In quali parti del mondo le fa piacere che guardi?",
        "help": "Può scegliere più di una risposta. Se non ne segna nessuna, guardo in Europa "
                "e nei panieri mondiali.",
        "kind": "multi",
        "options": [
            {"id": "europa", "label": "In Italia e in Europa, qui vicino a casa",
             "sets": {"markets_add": ["Europa"]}},
            {"id": "usa", "label": "Negli Stati Uniti, le grandi aziende che conosciamo tutti",
             "sets": {"markets_add": ["USA"]}},
            {"id": "asia", "label": "In Asia: Giappone, Corea, Taiwan",
             "sets": {"markets_add": ["Asia"]}},
            {"id": "mondo", "label": "Un po' in tutto il mondo, senza puntare su un paese solo",
             "sets": {"markets_add": ["Global"]}},
            {"id": "tutti", "label": "Non ho preferenze: guardi dove conviene",
             "sets": {"markets_add": ["USA", "Europa", "Asia", "Global"]}, "exclusive": True},
        ],
    },
    {
        "id": "settori",
        "text": "Delle singole aziende, di quali vuole sentir parlare?",
        "help": "Vale solo per le aziende singole. Può scegliere più di una risposta.",
        "kind": "multi",
        "options": [
            {"id": "tutti", "label": "Di tutte, scelga lei quelle che valgono",
             "sets": {"asset_classes_add": ["Azioni"], "sectors_add": ALL_SECTORS},
             "exclusive": True},
            {"id": "tech", "label": "Computer, telefoni, programmi",
             "sets": {"asset_classes_add": ["Azioni"], "sectors_add": ["Tecnologia"]}},
            {"id": "ai", "label": "Intelligenza artificiale e microchip",
             "sets": {"asset_classes_add": ["Azioni"], "sectors_add": ["AI"]}},
            {"id": "salute", "label": "Medicine, ospedali, salute",
             "sets": {"asset_classes_add": ["Azioni"], "sectors_add": ["Healthcare"]}},
            {"id": "banche", "label": "Banche e assicurazioni",
             "sets": {"asset_classes_add": ["Azioni"], "sectors_add": ["Finanza"]}},
            {"id": "energia", "label": "Luce, gas, benzina",
             "sets": {"asset_classes_add": ["Azioni"], "sectors_add": ["Energia"]}},
            {"id": "industria", "label": "Fabbriche, macchinari, treni e aerei",
             "sets": {"asset_classes_add": ["Azioni"], "sectors_add": ["Industriale"]}},
            {"id": "consumi", "label": "Negozi, cibo, marche che si usano ogni giorno",
             "sets": {"asset_classes_add": ["Azioni"], "sectors_add": ["Consumer"]}},
            # Senza questa voce le quattro societa immobiliari del listino non
            # sarebbero raggiungibili da nessun profilo: sono mappate sotto
            # "Azioni" ma con settore "Immobiliare".
            {"id": "immobili", "label": "Case, negozi e capannoni dati in affitto",
             "sets": {"asset_classes_add": ["Azioni"], "sectors_add": ["Immobiliare"]}},
            {"id": "nessuna", "label": "Le singole aziende non mi interessano",
             # I mestieri restano aperti ma inerti: senza "Azioni" non filtrano nulla.
             "sets": {"sectors_add": ALL_SECTORS}, "exclusive": True},
        ],
    },
    {
        "id": "frequenza",
        "text": "Al massimo, quante volte a settimana le fa piacere sentirmi?",
        "help": "Preferisco scriverle poco e a ragione. Quello che non le mando resta in "
                "attesa, non va perso.",
        "kind": "single",
        "options": [
            {"id": "una", "label": "Una volta, non di più: solo se è importante",
             "sets": {"weekly_limit": 1}},
            {"id": "due", "label": "Anche due volte a settimana", "sets": {"weekly_limit": 2}},
            {"id": "tre", "label": "Fino a tre volte, se ci sono cose buone",
             "sets": {"weekly_limit": 3}},
            {"id": "lei", "label": "Decida lei", "sets": {"weekly_limit": 2}},
        ],
    },
    {
        "id": "canale",
        "text": "Dove vuole che le scriva, quando trovo qualcosa?",
        "help": "Oggi so consegnare davvero solo su Telegram: gli altri canali sono previsti "
                "ma non ancora attivi, e nel frattempo trova tutto su questa pagina.",
        "kind": "multi",
        "options": [
            {"id": "telegram", "label": "Un messaggio sul telefono, con Telegram (già attivo)",
             "sets": {"channels_add": ["Telegram"]}},
            {"id": "email", "label": "Una email (non ancora attiva)",
             "sets": {"channels_add": ["Email"]}},
            {"id": "whatsapp", "label": "Un messaggio su WhatsApp (non ancora attivo)",
             "sets": {"channels_add": ["WhatsApp"]}},
            {"id": "push", "label": "Un avviso che compare sul telefono (non ancora attivo)",
             "sets": {"channels_add": ["Push"]}},
            {"id": "schermo", "label": "Da nessuna parte: guardo io questa pagina quando mi va",
             "sets": {"channels_add": ["Solo a schermo"]}, "exclusive": True},
        ],
    },
]


def _blank() -> dict:
    acc = {k: 0 for k in SUM_KEYS + MAX_KEYS}
    acc.update({k: [] for k in ADD_KEYS})
    acc.update({"horizon": None, "weekly_limit": None, "currency": None,
                "country": None, "wants_portfolio": False, "risk_cap": None})
    return acc


def _stricter(a: str | None, b: str | None) -> str | None:
    """Tra due tetti vince il più prudente."""
    if a is None:
        return b
    if b is None:
        return a
    return a if CAP_ORDER.index(a) <= CAP_ORDER.index(b) else b


def apply_effects(sets: dict, acc: dict) -> None:
    for key, value in (sets or {}).items():
        if key.endswith("_add"):
            target = key[:-4]
            for v in (value if isinstance(value, list) else [value]):
                if v not in acc[target]:
                    acc[target].append(v)
        elif key in SUM_KEYS:
            acc[key] += value
        elif key in MAX_KEYS:
            acc[key] = max(acc[key], value)
        elif key == "risk_cap":
            acc["risk_cap"] = _stricter(acc.get("risk_cap"), value)
        else:
            acc[key] = value


def risk_label(points: int) -> str:
    for band in RISK_BANDS:
        if band["min"] <= points <= band["max"]:
            return band["label"]
    return DEFAULTS["risk_profile"]


def profile_from_answers(answers: dict) -> dict:
    """Risposte -> utente completo, pronto per il motore. Deterministico: le
    stesse risposte danno sempre lo stesso profilo, e ogni passaggio è
    spiegabile all'utente."""
    acc = _blank()
    for q in QUESTIONS:
        given = answers.get(q["id"])
        if given is None:
            continue
        for oid in (given if isinstance(given, list) else [given]):
            opt = next((o for o in q["options"] if o["id"] == oid), None)
            if opt:
                apply_effects(opt.get("sets"), acc)

    profile = {
        "capital": None,                      # non lo chiediamo, non lo usiamo
        "horizon": acc["horizon"] or DEFAULTS["horizon"],
        "currency": acc["currency"] or DEFAULTS["currency"],
        "country": acc["country"] or DEFAULTS["country"],
        "risk_profile": risk_label(acc["risk_points"]),
        "markets": acc["markets"] or list(DEFAULTS["markets"]),
        "sectors": acc["sectors"] or list(DEFAULTS["sectors"]),
        "asset_classes": acc["asset_classes"] or list(DEFAULTS["asset_classes"]),
    }
    # Il tetto dichiarato (vendo tutto, comincio adesso, mi servono presto) vince
    # sempre sulla somma dei punti.
    cap = acc.get("risk_cap")
    if cap and CAP_ORDER.index(profile["risk_profile"]) > CAP_ORDER.index(cap):
        profile["risk_profile"] = cap
    # L'esperienza non amplia il rischio: può solo ridurlo.
    if acc["experience_points"] <= INEXPERIENCED_BELOW and profile["risk_profile"] == "Aggressivo":
        profile["risk_profile"] = "Bilanciato"
    if profile["risk_profile"] == "Conservativo":
        profile["asset_classes"] = [c for c in profile["asset_classes"] if c != "Crypto"]
    # Coerenza tra strumenti e mercati: le monete digitali si scambiano solo sui
    # mercati mondiali, senza i quali la scelta resterebbe senza effetto.
    if "Crypto" in profile["asset_classes"] and "Global" not in profile["markets"]:
        profile["markets"].append("Global")
    # "Solo a schermo" è una scelta, non un canale di invio.
    channels = acc["channels"] or list(DEFAULTS["channels"])

    return {
        "id": "me", "name": "Il mio profilo", "first_name": "",
        "profile": profile,
        "channels": channels,
        "weekly_limit": acc["weekly_limit"] or DEFAULTS["weekly_limit"],
        "wants_portfolio": bool(acc["wants_portfolio"]),
        "positions": [], "watchlist": [], "notifications_this_week": 0,
        "answers": dict(answers),
        "risk_points": acc["risk_points"],
        "from_questionnaire": True,
    }


def recap_rows(user: dict, risk_ceiling: dict) -> list[tuple[str, str]]:
    """Le righe del "ecco come l'ho capita", in parole."""
    p = user["profile"]
    return [
        ("Come la tratto", p["risk_profile"].lower()),
        ("Per quanto tempo", p["horizon"].lower()),
        ("Dove guardo", ", ".join(p["markets"])),
        ("Di che cosa le parlo", ", ".join(p["sectors"])),
        ("Che strumenti le propongo", ", ".join(p["asset_classes"])),
        ("Quanto la disturbo", f"al massimo {user['weekly_limit']} "
                               f"{'volta' if user['weekly_limit'] == 1 else 'volte'} a settimana"),
        ("Dove le scrivo", ", ".join(user["channels"])),
        ("Rischio massimo che le propongo",
         f"{risk_ceiling[p['risk_profile']]} su 100"),
    ]


def export() -> dict:
    """Il blocco che finisce in data.js per la vista cliente."""
    return {
        "questions": QUESTIONS,
        "defaults": DEFAULTS,
        "risk_bands": RISK_BANDS,
        "inexperienced_below": INEXPERIENCED_BELOW,
        "privacy_note": PRIVACY_NOTE,
        "closing": CLOSING,
    }
