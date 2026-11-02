"""Genera web/data.js: lo stato del ciclo serializzato per la dashboard.

La dashboard è un file statico aperto da disco (file://), dove `fetch` non
funziona: i dati vengono quindi scritti come assegnazione a `window.DEMO_DATA`
e caricati con un tag <script>. Nessun server, nessuna dipendenza.
"""

from __future__ import annotations

import json
import hashlib
import re as _re
import os

from engine import __version__, onboarding
from engine.decisions import DEMO_DECISIONS, FDD_CHANGES, OPEN_POINTS_LEFT
from engine.indicators import ema
from engine.notifications import SCORE_THRESHOLD, WEEKLY_LIMIT
from engine.pipeline import DEEP_ANALYSIS_BATCH, run_scan
from engine.portfolio import ALERT_RULES
from engine.plain import EXAMPLE_SHARE_OF_CAPITAL, GLOSSARY
from engine.reports import TEMPLATE_ENGINE
from engine.scoring import BANDS, COMPONENT_LABELS, WEIGHTS
from engine.triggers import THRESHOLDS
from engine.universe import FX_TO_EUR, HISTORY_DAYS
from engine.users import RISK_CEILING

CHART_POINTS = 130

TRACEABILITY = [
    ("BR-01", "Profilazione utente", "engine/users.py", "Profilo"),
    ("BR-02", "Ricerca automatica delle opportunità", "engine/pipeline.py", "Pipeline"),
    ("BR-03", "Analisi multi-agente (AI Valuation al posto del consensus analisti)",
     "engine/agents.py, engine/valuation.py", "Opportunity Center"),
    ("BR-04", "Opportunity Score e classificazione", "engine/scoring.py", "Opportunity Center"),
    ("BR-05", "Trigger di opportunità", "engine/triggers.py", "Opportunity Center"),
    ("BR-06", "Notifiche selettive (>85, max 3/settimana)", "engine/notifications.py", "Notifiche"),
    ("BR-07", "Notifiche multicanale", "engine/notifications.py", "Notifiche"),
    ("BR-08", "Monitoraggio del portafoglio", "engine/portfolio.py", "Portfolio"),
    ("BR-09", "Analisi on demand", "engine/reports.py", "Research"),
    ("BR-10", "Dashboard", "web/app.js", "tutte le aree"),
    ("BR-11", "Archivio dei report", "engine/reports.py", "Reports"),
    ("BR-12", "Apprendimento delle preferenze", "engine/users.py", "Profilo"),
    ("BR-13", "Copertura delle asset class", "engine/universe.py", "Opportunity Center"),
    ("BR-14", "Copertura multi-mercato", "engine/universe.py", "Opportunity Center"),
    ("BR-15", "Portfolio optimization", "-", "non implementato nella demo"),
    ("BR-16", "Backtesting", "-", "non implementato nella demo"),
    ("BR-17", "Simulazioni Monte Carlo", "-", "non implementato nella demo"),
    ("BR-18", "Agente completamente autonomo", "-", "non implementato nella demo (OP-02)"),
]

TECH_KEYS = ["price", "rsi", "macd_line_pct", "macd_positive", "ema50", "ema200",
             "above_ema50", "above_ema200", "golden_cross", "bb_position", "bb_upper",
             "bb_lower", "adx", "volume_ratio", "atr", "volatility", "max_drawdown",
             "high_52w", "low_52w", "from_high_52w", "resistance_60d", "breakout",
             "perf_1m", "perf_3m", "perf_6m"]


def _asset_payload(state: dict) -> list[dict]:
    out = []
    prescreen = {s["ticker"]: s for s in state["scanned"]}
    for ticker, a in state["assets"].items():
        an = state["analyses"][ticker]
        closes = a["series"]["close"]
        e50, e200 = ema(closes, 50), ema(closes, 200)
        out.append({
            "ticker": ticker, "name": a["name"], "asset_class": a["asset_class"],
            "market": a["market"], "sector": a["sector"], "size": a["size"],
            "currency": a["currency"], "fx_to_eur": a["fx_to_eur"],
            "price": a["tech"]["price"],
            "opportunity_score": an["opportunity_score"],
            "classification": an["classification"],
            "risk_label": an["risk_label"], "final_rating": an["final_rating"],
            "scores": an["scores"], "contributions": an["contributions"],
            "valuation": {"fair_value": an["agents"]["valuation"]["fair_value"],
                          "method": an["agents"]["valuation"]["method"],
                          "confidence": an["agents"]["valuation"]["confidence"],
                          "source": an["agents"]["valuation"]["source"],
                          "model_value": an["agents"]["valuation"].get("model_value"),
                          "reasoning": an["agents"]["valuation"].get("ai_reasoning", "")},
            "ai_sources": an["ai_sources"], "ai_review": an["ai_review"],
            "weights_redistributed": an["weights_redistributed"],
            "plan": an["plan"],
            "agents": {k: {"agent": v["agent"], "score": v["score"],
                           "drivers": v["drivers"], "note": v["note"]}
                       for k, v in an["agents"].items()},
            "tech": {k: a["tech"][k] for k in TECH_KEYS},
            "fundamentals": a["fundamentals"],
            "mispricing": a.get("mispricing"),
            "data_quality": a.get("data_quality"),
            "valuable": a.get("valuable", True),
            "news": a["news"], "insider": a["insider"], "earnings": a["earnings"],
            "triggers": state["triggers"][ticker],
            "prescreen": prescreen[ticker]["prescreen"],
            "in_batch": prescreen[ticker]["in_batch"],
            "chart": {
                # le date sono condivise (meta.chart_dates): stesso calendario
                "close": [round(c, 2) for c in closes[-CHART_POINTS:]],
                "ema50": [round(x, 2) for x in e50[-CHART_POINTS:]],
                "ema200": [round(x, 2) for x in e200[-CHART_POINTS:]],
                "volume": [round(v / 1000) for v in a["series"]["volume"][-CHART_POINTS:]],
            },
        })
    return sorted(out, key=lambda x: -x["opportunity_score"])


def build_payload(state: dict, public: bool = False) -> dict:
    """Con `public=True` il profilo personale (profilo.json) e il suo portafoglio
    NON entrano nel file: serve a pubblicare la pagina online senza pubblicare
    anche le proprie posizioni. Le analisi sono le stesse per tutti."""
    assets = _asset_payload(state)
    band_counts = []
    for lo, hi, label in BANDS:
        band_counts.append({"label": label, "range": f"{lo}-{hi}",
                            "count": sum(1 for a in assets
                                         if lo <= a["opportunity_score"] <= hi)})
    users = [u for u in state["users"] if not (public and u.get("from_file"))]
    kept_ids = {u["id"] for u in users}
    hidden = [u for u in state["users"] if u["id"] not in kept_ids]
    hidden_ids = {u["id"] for u in hidden}
    hidden_names = {u["name"] for u in hidden}

    def public_log(entries: list[dict]) -> list[dict]:
        """Il log del ciclo nomina gli utenti, i loro portafogli e gli invii: in
        modalità pubblica le righe del profilo personale vanno tolte, non basta
        togliere l'utente dall'elenco."""
        if not public:
            return entries
        out = []
        for e in entries:
            if e.get("user_id") in hidden_ids:
                continue
            testo = f"{e.get('action', '')} {e.get('detail', '')}"
            if any(n and n in testo for n in hidden_names):
                continue
            if "profilo.json" in testo or "Profilo personale" in testo:
                continue
            out.append(e)
        return out
    reports = []
    known = {u["id"] for u in users}
    for r in state["reports"]:
        r = dict(r)
        r.pop("chart", None)          # il grafico arriva da assets[ticker].chart
        if public and r.get("requested_by") and r["requested_by"] not in known                 and r["requested_by"] != "Chief Investment Officer Agent":
            continue                  # richiesta partita dal profilo personale
        reports.append(r)

    # Cache dei report on demand: l'area Research deve poter rispondere su
    # qualsiasi asset dell'universo senza ricalcolare nel browser. In produzione
    # il report è generato al momento dal CIO Agent (step 9).
    reports_cache = {}
    for ticker, r in state["reports_by_ticker"].items():
        r = dict(r)
        r.pop("chart", None)
        reports_cache[ticker] = r

    trigger_counts: dict[str, int] = {}
    for trs in state["triggers"].values():
        for t in trs:
            trigger_counts[t["label"]] = trigger_counts.get(t["label"], 0) + 1

    return {
        "meta": {
            "project_code": "AI-MARKET-SCOUT",
            "title": "AI Market Scout & Investment Copilot",
            "fdd_version": "1.0 - 30/10/2026",
            "engine_version": __version__,
            "today": state["today"],
            "history_days": HISTORY_DAYS,
            "chart_dates": next(iter(state["assets"].values()))["series"]["date"][-CHART_POINTS:],
            "narrative_engine": (f"Gemini ({state['llm']['model']})" if state["llm"]["enabled"] else TEMPLATE_ENGINE),
            "weights": WEIGHTS,
            "bands": [{"min": lo, "max": hi, "label": label} for lo, hi, label in BANDS],
            "score_threshold": SCORE_THRESHOLD,
            # questionario spento: le opportunita' sono uguali per tutti.
            # Interruttore e non cancellazione, BR-01 resta nel motore.
            "questionario": False,
            "weekly_limit": WEEKLY_LIMIT,
            "deep_batch": DEEP_ANALYSIS_BATCH,
            "trigger_thresholds": {k: v for k, v in THRESHOLDS.items()},
            "alert_rules": ALERT_RULES,
            "risk_ceiling": RISK_CEILING,
            "example_share_of_capital": EXAMPLE_SHARE_OF_CAPITAL,
            "fx_to_eur": FX_TO_EUR,
            "provider_map": state["provider_map"],
            "data_source": state["data"]["source"],
            "data_mode": state["source"],
            "channels": ["Email", "Telegram", "WhatsApp", "Push notification"],
            "demo_decisions": [{"code": c, "op": o, "text": t, "where": w}
                               for c, o, t, w in DEMO_DECISIONS],
            "fdd_changes": [{"ref": r, "text": t} for r, t in FDD_CHANGES],
            "component_labels": COMPONENT_LABELS,
            "open_points_left": [{"code": c, "text": t} for c, t in OPEN_POINTS_LEFT],
            "traceability": [{"br": b, "name": n, "module": m, "area": a}
                             for b, n, m, a in TRACEABILITY],
        },
        # elenco globale delle opportunita': la pagina lo mostra e le
        # notifiche lo usano, cosi' non possono divergere
        "opportunita": state.get("opportunita",
                                 {"lista": [], "osservati": [], "scartati": [],
                                  "soglia": 0}),
        "llm": state["llm"],
        "data": {**state["data"], "mode": state["source"]},
        "stats": {
            **state["core_stats"],
            "trigger_counts": trigger_counts,
            "notifications": sum(len(u["decision"]["notifications"]) for u in users),
            "alerts": sum(len(u["portfolio"]["alerts"]) for u in users),
            "reports": len(reports),
            "band_counts": band_counts,
            "skipped": state["skipped"],
        },
        "run_log": public_log(state["run_log"]),
        "scanned": state["scanned"],
        "assets": assets,
        "users": users,
        "public": public,
        "reports": reports,
        "reports_cache": reports_cache,
        # strato "linguaggio semplice" e assistente (vista predefinita)
        "plain": state["plain_generic"],
        "knowledge": state["knowledge"],
        "glossary": [{"term": t, "definition": d} for t, d in GLOSSARY.items()],
        # Questionario iniziale: domande e regole, interpretate anche dal browser
        # (engine/onboarding.py è l'unica fonte di verità).
        "onboarding": onboarding.export(),
    }


# Campi di un asset che la pagina legge SOLO per le card che disegna: sono
# anche i piu' pesanti (la serie storica da sola e' 3,5 KB per strumento).
PESANTI = ("chart", "news", "fundamentals", "valuation", "tech", "plan",
           "contributions", "triggers", "data_quality", "prescreen",
           "mispricing", "ai_review", "ai_sources", "earnings", "insider",
           "scores", "weights_redistributed", "in_batch", "description")

# Sezioni del payload che il browser non apre mai. Verificato cercandole in
# web/app.js: zero riferimenti a reports_cache, reports e knowledge.
MAI_LETTE = ("reports_cache", "reports", "knowledge")


def alleggerisci(payload: dict) -> dict:
    """Toglie dal file quello che la pagina non legge.

    PERCHE'. Con 48 strumenti il file era 1 MB e nessuno se ne accorgeva. Con
    224 e' arrivato a 4 MB, e quel file lo scarica il telefono a ogni visita:
    su una rete lenta sono secondi di attesa e dati consumati per niente,
    perche' in pagina ci sono una trentina di card, non duecento.

    Che cosa resta. TUTTI gli strumenti restano nell'elenco, con nome, prezzo,
    punteggio e classificazione: servono a chi segue uno strumento che oggi non
    e' fra le proposte, e togliere l'elenco sarebbe togliere contenuto invece
    che peso. Spariscono solo i campi grossi degli strumenti che non si
    disegnano - la serie storica, le notizie, il dettaglio degli agenti - e le
    tre sezioni che il browser non apre.

    `agents` resta come oggetto vuoto e non sparisce: la pagina scrive
    `a.agents.fundamental || {}`, e su un campo assente quella riga
    solleverebbe un errore invece di ricadere sul valore vuoto.
    """
    opp = payload.get("opportunita") or {}
    mostrati = {o["ticker"] for o in (opp.get("lista") or [])}
    mostrati |= {o["ticker"] for o in (opp.get("osservati") or [])}

    leggeri = []
    for a in payload.get("assets") or []:
        if a.get("ticker") in mostrati:
            leggeri.append(a)
            continue
        snello = {k: v for k, v in a.items() if k not in PESANTI}
        snello["agents"] = {}
        leggeri.append(snello)
    payload["assets"] = leggeri

    plain = payload.get("plain") or {}
    payload["plain"] = {k: v for k, v in plain.items() if k in mostrati}

    for k in MAI_LETTE:
        payload.pop(k, None)
    return payload


def _opportunita_pubblicate(path: str) -> dict:
    """I ticker e i punteggi che stanno nel data.js che sta per essere
    sostituito.

    Serve a dire "questa e' nuova": il riferimento giusto non e' il ciclo
    precedente ma QUELLO CHE L'UTENTE HA VISTO FINORA, cioe' il file
    pubblicato. Cosi' la segnalazione non si consuma per conto suo quando il
    ciclo gira due volte, e vuol dire quello che sembra.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            testo = fh.read()
        inizio, fine = testo.index("{"), testo.rindex("}") + 1
        vecchio = json.loads(testo[inizio:fine])
    except Exception:
        return {}
    lista = ((vecchio.get("opportunita") or {}).get("lista")) or []
    return {o.get("ticker"): o.get("score") for o in lista if o.get("ticker")}


def write_data(state: dict, path: str | None = None, public: bool = False) -> str:
    path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "data.js")
    prima = _opportunita_pubblicate(path)
    # L'alleggerimento sta QUI e non in build_payload perche' i controlli
    # automatici confrontano il payload completo con lo stato del motore: la
    # verifica della privacy deve vedere tutto quello che il motore produce,
    # non la versione ridotta.
    payload = alleggerisci(build_payload(state, public=public))
    adesso = {o["ticker"]: o["score"]
              for o in ((payload.get("opportunita") or {}).get("lista") or [])}
    payload["novita"] = {
        "nuove": [t for t in adesso if t not in prima],
        "uscite": [t for t in prima if t not in adesso],
        "salite": [t for t in adesso if t in prima and adesso[t] > prima[t]],
        "scese": [t for t in adesso if t in prima and adesso[t] < prima[t]],
        "confronto_con": "l'ultima versione pubblicata",
        "primo_giro": not prima,
    }
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("/* Generato da build_web.py - non modificare a mano. */\n")
        fh.write("window.DEMO_DATA = ")
        fh.write(body)
        fh.write(";\n")
    return path


# riga da riscrivere nel service worker pubblicato (vedi _timbra_sw)
_re_sw = _re.compile(r"const VERSIONE = '[^']*';")

STATIC_FILES = ("index.html", "styles.css", "stili-cliente.css",
                "charts.js", "onboarding.js", "app.js",
                # installazione sul telefono e funzionamento senza rete
                "manifest.webmanifest", "sw.js", "icona-192.png", "icona-512.png",
                # scadenze HTTP: senza questo file le decide l'hosting, e per
                # data.js sceglierebbe una scadenza da codice invece che da
                # dati. Cloudflare Pages lo legge e non lo serve.
                "_headers")


def _timbra_sw(dst: str) -> str:
    """Mette nel service worker un nome di cache che cambia quando cambia la
    pagina.

    Serve a un problema concreto: il service worker serve i file della pagina
    "prima dalla cache". Se il nome della cache resta lo stesso, chi ha già
    aperto il sito continua a vedere la versione vecchia anche dopo una nuova
    pubblicazione - e non c'è modo di spiegarglielo a distanza. Il nome è
    l'impronta dei file del guscio: cambia solo quando cambia davvero qualcosa,
    quindi non invalida la cache a ogni ciclo per nulla.
    """
    impronta = hashlib.sha1()
    for name in STATIC_FILES:
        if name == "sw.js":          # altrimenti l'impronta dipende da sé stessa
            continue
        with open(os.path.join(dst, name), "rb") as f:
            impronta.update(f.read())
    versione = "ams-" + impronta.hexdigest()[:10]
    percorso = os.path.join(dst, "sw.js")
    with open(percorso, encoding="utf-8") as f:
        testo = f.read()
    nuovo = _re_sw.sub(f"const VERSIONE = '{versione}';", testo, count=1)
    if nuovo == testo:
        # il file è cambiato di forma: meglio dirlo che pubblicare una cache
        # che non si invalida mai
        print("Attenzione: non ho trovato la riga VERSIONE in sw.js; "
              "la cache del telefono potrebbe non aggiornarsi.")
    else:
        with open(percorso, "w", encoding="utf-8") as f:
            f.write(nuovo)
    return versione


def publish(state: dict, folder: str, public: bool = True) -> str:
    """Prepara una cartella autonoma da mettere online: i file statici della
    pagina più il data.js del ciclo. La cartella web/ resta quella privata, così
    pubblicare non cancella il proprio profilo dalla dashboard di casa."""
    import shutil
    src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
    dst = os.path.abspath(folder)
    os.makedirs(dst, exist_ok=True)
    for name in STATIC_FILES:
        shutil.copy2(os.path.join(src, name), os.path.join(dst, name))
    _timbra_sw(dst)
    write_data(state, os.path.join(dst, "data.js"), public=public)
    total = sum(os.path.getsize(os.path.join(dst, f))
                for f in STATIC_FILES + ("data.js",))
    print(f"{len(STATIC_FILES) + 1} file, {total / 1024:.0f} KB in totale "
          f"(pagina installabile sul telefono)")
    return dst


def main(argv: list[str] | None = None) -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Genera web/data.js per la dashboard")
    ap.add_argument("--real", action="store_true", help="usa i dati di mercato veri")
    ap.add_argument("--live", action="store_true", help="usa Gemini per le analisi")
    ap.add_argument("--llm-limit", type=int, default=None)
    ap.add_argument("--llm-pace", type=float, default=0.0)
    ap.add_argument("--llm-budget", type=int, default=None,
                    help="tetto di chiamate al modello per questo ciclo")
    ap.add_argument("--threshold", type=int, default=None)
    ap.add_argument("--pubblico", action="store_true",
                    help="esclude dal file il profilo personale e il suo portafoglio: "
                         "da usare quando la pagina va messa online")
    ap.add_argument("--cartella", default=None,
                    help="scrive la pagina completa (file statici + data.js) in questa "
                         "cartella, pronta da pubblicare, senza toccare web/")
    args = ap.parse_args(argv)
    state = run_scan(live=args.live, source="real" if args.real else "synthetic",
                     llm_limit=args.llm_limit, llm_pace_s=args.llm_pace,
                     threshold=args.threshold, llm_budget=args.llm_budget)
    if args.cartella:
        p = publish(state, args.cartella, public=args.pubblico)
        print(f"Cartella pronta da pubblicare: {p}")
    else:
        p = write_data(state, public=args.pubblico)
        print(f"Scritto {p} ({os.path.getsize(p) / 1024:.0f} KB)")
    if args.pubblico:
        print("Modalità pubblica: profilo personale e portafoglio NON inclusi nel file.")
    else:
        print("Attenzione: il file contiene il profilo personale e le sue posizioni, se "
              "dichiarate. Per metterlo online usa --pubblico.")
    print(f"Dati: {state['data']['source']} · analisi: {state['llm']['mode']} · "
          f"soglia {state['threshold']}")


if __name__ == "__main__":
    main()