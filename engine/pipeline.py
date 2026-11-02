"""Orchestrazione del ciclo giornaliero: i 10 step del workflow in 3.1.

In produzione gli step 2-7 sono task Celery schedulati da Cron (FDD 1.5); qui
sono chiamate in sequenza, con lo stesso confine tra gli step, così il
passaggio a Celery è una questione di decoratori.
"""

from __future__ import annotations

import time

from . import assistant
from . import channels
from . import identificativi
from . import llm2 as llm2_mod
from . import opportunita
from . import visti
from . import llm as llm_mod
from . import profile_file
from . import notifications as notif
from . import plain as pl
from . import portfolio as pf
from .agents import lin
from .reports import build_report
from .scoring import WEIGHTS, analyze_asset
from .triggers import detect
from .universe import PROVIDER_MAP, TODAY, load_universe
from .users import USERS, interactions, learned_preferences

DEEP_ANALYSIS_BATCH = 24      # DEMO-17: quanti asset passano all'analisi profonda


def prescreen(asset: dict) -> float:
    """Market Scanner Agent: ranking preliminare sui soli dati grezzi
    (DEMO-17). Serve a decidere su quali asset vale la pena spendere i cinque
    agenti specialistici, non a valutare l'asset."""
    t = asset["tech"]
    # scostamento dal valore stimato dal modello: nessun dato di analisti
    upside = asset.get("valuation", {}).get("upside", 0.08)
    parts = [
        (lin(t["perf_3m"], -0.20, 0.30), 0.30),
        (lin(upside, 0.0, 0.35), 0.30),
        (lin(t["adx"], 12, 40), 0.15),
        (lin(t["volume_ratio"], 0.7, 1.8), 0.10),
        (100.0 if t["above_ema200"] else 20.0, 0.15),
    ]
    return round(sum(v * w for v, w in parts), 1)


class RunLog:
    def __init__(self):
        self.entries: list[dict] = []
        self._t0 = time.perf_counter()

    def step(self, n: int, actor: str, action: str, detail: str, **extra):
        self.entries.append({
            "step": n, "actor": actor, "action": action, "detail": detail,
            "elapsed_ms": round((time.perf_counter() - self._t0) * 1000, 1),
            **extra,
        })


def load_assets(source: str, only: list[str] | None, log: "RunLog") -> tuple[dict, list[dict], dict]:
    """Carica l'universo dalla sorgente scelta. `real` scarica da Yahoo Finance
    (prezzi, bilanci, notizie); `synthetic` genera dati deterministici."""
    skipped: list[dict] = []
    if source == "real":
        from .providers import Yahoo
        from .real_universe import load_real_universe
        y = Yahoo()
        rows, skipped = load_real_universe(y)
        assets = {a["ticker"]: a for a in rows}
        # L'ultima seduta NON e' il massimo fra tutte le date: le cripto
        # trattano sette giorni su sette, quindi di domenica avevano una barra
        # piu' recente di tutti e il programma dichiarava "ultima seduta
        # domenica" mentre le borse erano chiuse da venerdi'. Due numeri
        # distinti, perche' sono due mondi con calendari diversi.
        CONTINUI = {"Crypto"}
        borse = [a["series"]["date"][-1] for a in rows
                 if a["asset_class"] not in CONTINUI]
        sempre = [a["series"]["date"][-1] for a in rows
                  if a["asset_class"] in CONTINUI]
        info = {"source": "Yahoo Finance (dati reali)", "http": y.stats["http"],
                "cache": y.stats["cache"], "errors": y.stats["errors"],
                "last_bar": max(borse, default="-"),
                "last_bar_continui": max(sempre, default=None),
                # Se l'ultima barra porta la data di oggi, la seduta non e'
                # finita: quel prezzo cambia ancora. Presentarlo come una
                # chiusura e' il modo piu' facile di far prendere una
                # decisione su un numero che fra un'ora e' diverso.
                "seduta_in_corso": max(borse, default="-") == TODAY.isoformat(),
                # A mercati aperti l'universo e' a cavallo di due sedute: le
                # borse europee hanno gia' la barra di oggi, quelle americane
                # ancora quella di venerdi'. Confrontare punteggi calcolati su
                # giorni diversi e' un paragone sbagliato, e va detto.
                "su_oggi": sum(1 for d in borse if d == TODAY.isoformat()),
                "su_seduta_precedente": sum(1 for d in borse
                                            if d != TODAY.isoformat()),
                "with_fundamentals": sum(1 for a in rows if a["valuable"]),
                "with_news": sum(1 for a in rows if a["news"]),
                "insider": False}
        log.step(3, "Data provider", "Scarico dei dati reali",
                 f"{len(assets)} strumenti da Yahoo Finance: {info['http']} chiamate, "
                 f"{info['cache']} dalla cache del giorno, "
                 + ("seduta di borsa del " if info["seduta_in_corso"]
                    else "ultima seduta di borsa ")
                 + f"{info['last_bar']}"
                 + (f" ANCORA IN CORSO: {info['su_oggi']} strumenti hanno gia' la "
                    f"barra di oggi, {info['su_seduta_precedente']} sono ancora alla "
                    f"chiusura precedente, quindi i punteggi non sono confrontabili "
                    f"fra loro come a mercati chiusi"
                    if info["seduta_in_corso"] else "")
                 + (f" (cripto al {info['last_bar_continui']}, trattano tutti i giorni)"
                    if info.get("last_bar_continui")
                    and info["last_bar_continui"] != info["last_bar"] else "") + "; "
                 f"{info['with_fundamentals']} con bilanci, {info['with_news']} con notizie; "
                 f"dati insider non disponibili senza contratto dati",
                 count=len(assets), skipped=len(skipped))
        if skipped:
            log.step(3, "Data provider", "Strumenti esclusi",
                     "; ".join(f"{s['ticker']}: {s['reason']}" for s in skipped[:6]))
    else:
        rows = load_universe()
        assets = {}
        for a in rows:
            if not a["series"]["close"] or a["tech"]["price"] <= 0:
                skipped.append({"ticker": a["ticker"], "reason": "serie prezzi non disponibile"})
                continue
            assets[a["ticker"]] = a
        info = {"source": "generatore deterministico (dati sintetici)",
                "with_fundamentals": len(assets), "with_news": len(assets), "insider": True,
                "last_bar": TODAY.isoformat()}
        log.step(3, "Market Scanner Agent", "Acquisizione dati",
                 f"{len(assets)} asset da {len(PROVIDER_MAP)} provider: " +
                 "; ".join(f"{p} ({', '.join(f[:2])})" for p, f in PROVIDER_MAP.items()),
                 count=len(assets), skipped=len(skipped))
    if only:
        keep = set(only)
        assets = {t: a for t, a in assets.items() if t in keep}
    return assets, skipped, info


def run_scan(live: bool = False, api_key: str | None = None, model: str | None = None,
             use_cache: bool = True, llm_limit: int | None = None,
             llm_pace_s: float = 0.0, source: str = "synthetic",
             only: list[str] | None = None, telegram: bool = False,
             threshold: int | None = None, llm_budget: int | None = None,
             notifica: bool = False) -> dict:
    """Esegue un ciclo completo e restituisce lo stato che alimenta dashboard,
    notifiche e archivio report.

    Con `live=True` e una chiave Gemini, valutazione, sentiment, revisione dei
    punteggi e testi passano dal modello; senza chiave il ciclo gira identico
    sul nucleo deterministico (OP-06: un modello che non risponde non ferma la
    scansione)."""
    log = RunLog()

    # Profili: se c'è profilo.json è il tuo, altrimenti i tre clienti demo.
    own, problems = profile_file.load()
    users = ([own] + USERS) if own else list(USERS)
    if own:
        log.step(1, "Profilo", f"Profilo personale caricato da {profile_file.PROFILE_PATH.name}",
                 f"{own['name']}: {own['profile']['risk_profile'].lower()}, capitale "
                 f"{own['profile']['capital']} {own['profile']['currency']}, "
                 f"{len(own['positions'])} posizioni, {len(own['watchlist'])} in watchlist")
    elif problems:
        log.step(1, "Profilo", "profilo.json ignorato", "; ".join(problems[:4]))

    if threshold is not None:
        # BR-06: la soglia è un parametro del servizio, non una costante
        notif.SCORE_THRESHOLD = int(threshold)

    tg = channels.Telegram(enabled=telegram)
    primo = llm_mod.Gemini(enabled=live, api_key=api_key, model=model,
                           use_cache=use_cache, pace_s=llm_pace_s, budget=llm_budget)
    # Il secondo modello (compatibile OpenAI: Groq, Cerebras, OpenRouter) entra
    # solo quando il primo non puo' rispondere. Se non e' configurato, la coppia
    # si comporta esattamente come il primo da solo.
    secondo = llm2_mod.Compatibile(enabled=live, use_cache=use_cache,
                                   pace_s=llm_pace_s)
    gem = llm2_mod.Coppia(primo, secondo) if secondo.enabled else primo
    log.step(2, "Provider LLM", "Stato dei modelli",
             f"Modalità {gem.mode}, modello {gem.model}; "
             f"analisi qualitative {'affidate al modello' if gem.enabled else 'sul nucleo deterministico'}"
             + (f"; secondo modello pronto a subentrare ({secondo.model})"
                if secondo.enabled else ""))

    # Step 2 - Scheduler
    log.step(2, "Scheduler (Celery / Cron)", "Avvio scansione giornaliera",
             f"Ciclo del {TODAY.isoformat()}, cadenza giornaliera (NFR-03)")

    # Step 3 - Market Scanner Agent: acquisizione dati (DEMO-18 / OP-06: un
    # asset con dati incompleti esce dal ciclo e resta nel log)
    assets, skipped, data_info = load_assets(source, only, log)

    ranking = sorted(((t, prescreen(a)) for t, a in assets.items()), key=lambda x: -x[1])
    batch = [t for t, _ in ranking[:DEEP_ANALYSIS_BATCH]]
    if source == "real":
        for u in users:
            if u.get("from_file"):
                continue
            u["positions"] = [{**p, "avg_price": None} for p in u["positions"]]

    held = {p["ticker"] for u in users for p in u["positions"] if p["ticker"] in assets}
    watched = {t for u in users for t in u["watchlist"] if t in assets}
    deep = list(dict.fromkeys(batch + sorted(held | watched)))
    log.step(3, "Market Scanner Agent", "Ranking preliminare",
             f"Top {DEEP_ANALYSIS_BATCH} per prescreening + {len(held)} posizioni in "
             f"portafoglio e {len(watched)} in watchlist: {len(deep)} asset all'analisi profonda",
             count=len(deep))

    # Step 4 - agenti specialistici + Step 5 - motore di scoring
    # `llm_limit` serve sui piani con pochi inviti al minuto: restringe l'uso
    # del modello ai primi asset del prescreening.
    llm_set = set(deep if llm_limit is None else deep[:max(0, llm_limit)])
    if llm_limit is not None:
        log.step(4, "Provider LLM (Gemini)", "Perimetro del modello",
                 f"Modello usato sui primi {len(llm_set)} asset del prescreening "
                 f"(limite richiesto: {llm_limit}); gli altri restano sul calcolo")

    analyses: dict[str, dict] = {}
    for ticker, a in assets.items():
        # Il modello si usa sugli asset dell'analisi profonda: sugli altri il
        # nucleo deterministico basta e tiene sotto controllo costi e tempi.
        analyses[ticker] = analyze_asset(a, gem if ticker in llm_set else None)
    log.step(4, "Fundamental / Technical / AI Valuation / Sentiment / Risk Agent",
             "Calcolo degli score",
             f"5 agenti x {len(analyses)} asset = {5 * len(analyses)} valutazioni "
             f"(gli asset oltre il batch alimentano la cache per l'analisi on demand)",
             count=len(analyses))

    triggers_by_ticker = {
        t: detect(assets[t], analyses[t]["scores"]["fundamental"],
                  analyses[t]["agents"]["valuation"])
        for t in assets}
    all_triggers = [tr for trs in triggers_by_ticker.values() for tr in trs]
    by_type: dict[str, int] = {}
    for tr in all_triggers:
        by_type[tr["label"]] = by_type.get(tr["label"], 0) + 1
    log.step(3, "Market Scanner Agent", "Rilevazione trigger",
             f"{len(all_triggers)} trigger su {sum(1 for t in triggers_by_ticker.values() if t)} "
             f"asset: " + ", ".join(f"{k} {v}" for k, v in sorted(by_type.items(), key=lambda kv: -kv[1])),
             count=len(all_triggers))

    scanned = [{"ticker": t, "prescreen": p, "in_batch": t in deep} for t, p in ranking]
    log.step(5, "Motore di scoring", "Opportunity Score e classificazione",
             f"Pesi F30/T20/A25/S15/R10 con rischio invertito (A-05). "
             f"Eccezionali: {sum(1 for a in analyses.values() if a['opportunity_score'] >= 90)}, "
             f"forti: {sum(1 for a in analyses.values() if 80 <= a['opportunity_score'] <= 89)}, "
             f"da monitorare: {sum(1 for a in analyses.values() if 70 <= a['opportunity_score'] <= 79)}")

    # Report "di cache": uno per ogni asset, è quello che il CIO Agent
    # produrrebbe su richiesta (step 9) e la base degli scenari in parole.
    reports_by_ticker = {
        t: build_report(assets[t], analyses[t], triggers_by_ticker[t],
                        question=f"Analizza {assets[t]['name']}",
                        llm=gem if t in llm_set else None)
        for t in assets}

    core_stats = {
        "assets": len(assets),
        "markets": sorted({a["market"] for a in assets.values()}),
        "asset_classes": sorted({a["asset_class"] for a in assets.values()}),
        "triggers": len(all_triggers),
        "trigger_counts": dict(sorted(by_type.items(), key=lambda kv: -kv[1])),
        "above_threshold": sum(1 for a in analyses.values()
                               if a["opportunity_score"] > notif.SCORE_THRESHOLD),
    }

    # Traduzione in italiano semplice per tutti gli asset (vista semplice e chat)
    plain_generic = {t: pl.asset_plain(assets[t], analyses[t], triggers_by_ticker[t],
                                       reports_by_ticker[t], None) for t in assets}

    # Step 6-7 - CIO Agent e invio notifiche
    user_states = []
    reports: list[dict] = []
    for user in users:
        decision = notif.evaluate_user(user, assets, analyses, triggers_by_ticker)
        log.step(6, "Chief Investment Officer Agent", f"Valutazione per {user['name']}",
                 f"{len(decision['eligible'])} opportunità idonee, "
                 f"{len(decision['notifications'])} notificate, "
                 f"{user['notifications_this_week']}/3 notifiche già inviate questa settimana",
                 user_id=user["id"])
        for n in decision["notifications"]:
            log.step(7, "Sistema di notifica", f"Invio a {user['name']}",
                     f"{n['ticker']} score {n['opportunity_score']} su "
                     f"{', '.join(n['channels'])}"
                     + (" (Telegram reale)" if tg.enabled else " (invio simulato)"),
                     user_id=user["id"])
            reports.append(build_report(assets[n["ticker"]], analyses[n["ticker"]],
                                        triggers_by_ticker[n["ticker"]],
                                        requested_by="Chief Investment Officer Agent",
                                        llm=gem))

        # Step 8 - Portfolio Agent
        portfolio = pf.evaluate(user, assets, analyses)
        log.step(8, "Portfolio Agent", f"Monitoraggio portafoglio di {user['name']}",
                 f"{len(portfolio['positions'])} posizioni, valore "
                 f"{portfolio['total_value']:,.0f}, P/L {portfolio['pl_pct'] * 100:+.1f}%, "
                 f"rischio {portfolio['risk_score']} (max profilo {portfolio['risk_ceiling']}), "
                 f"{len(portfolio['alerts'])} alert", user_id=user["id"])

        # Step 10 - aggiornamento preferenze apprese
        prefs = learned_preferences(user["id"])
        log.step(10, "Sistema", f"Preferenze apprese di {user['name']}",
                 "Settori con affinità positiva: " +
                 (", ".join(prefs["top_sectors"]) or "nessuno"), user_id=user["id"])

        state_u = {
            "id": user["id"], "name": user["name"], "email": user["email"],
            "profile": user["profile"], "channels": user["channels"],
            "watchlist": user["watchlist"],
            "notifications_this_week_before": user["notifications_this_week"],
            "learned": prefs, "interactions": interactions(user["id"]),
            "decision": decision, "portfolio": portfolio,
            # serve a build_web per escluderlo dal file pubblicabile
            "from_file": bool(user.get("from_file")),
            "weekly_limit": decision.get("weekly_limit"),
        }

        # Strato "linguaggio semplice": le stesse decisioni, raccontate a chi
        # non legge un bilancio (vista predefinita della dashboard).
        relevant = list(dict.fromkeys([n["ticker"] for n in decision["notifications"]] +
                                      [p["ticker"] for p in user["positions"]] +
                                      [t for t in user["watchlist"] if t in assets] +
                                      [c["ticker"] for c in decision["eligible"]]))
        state_u["plain_assets"] = {
            t: pl.asset_plain(assets[t], analyses[t], triggers_by_ticker[t],
                              reports_by_ticker[t], user) for t in relevant}
        state_u["plain_portfolio"] = pl.portfolio_plain(state_u)
        state_u["plain_rejected"] = pl.rejected_plain(decision, assets)
        state_u["plain_greeting"] = pl.greeting(state_u)
        user_limit = decision.get("weekly_limit", notif.WEEKLY_LIMIT)
        state_u["plain_story"] = pl.scan_story(core_stats, state_u, notif.SCORE_THRESHOLD,
                                               user_limit, {**data_info, "mode": source})
        state_u["plain_commitments"] = pl.commitments(state_u, assets, analyses,
                                                      len(assets), user_limit)
        state_u["chat_answers"] = assistant.user_answers(
            state_u, assets, analyses, plain_generic, core_stats,
            notif.SCORE_THRESHOLD, user_limit, PROVIDER_MAP)
        state_u["chat_chips"] = assistant.chips(state_u, assets)
        state_u["chat_fallback"] = assistant.fallback_blocks(state_u)

        # Invio per singolo profilo: DISATTIVATO quando il ciclo manda le
        # notifiche globali. Le opportunita' sono le stesse per tutti, quindi
        # l'annuncio e' uno solo: tenere accese entrambe le strade vorrebbe
        # dire due messaggi per la stessa cosa. Questo ramo resta per chi
        # riaccende i profili (BR-01) senza le notifiche globali.
        if (not notifica and tg.enabled and user.get("from_file")
                and "Telegram" in user.get("channels", [])):
            for n in decision["notifications"]:
                text = channels.opportunity_message(
                    user, n, state_u["plain_assets"][n["ticker"]])
                ok = tg.send(text)
                log.step(7, "Telegram", f"Messaggio a {user['name']}",
                         f"{n['ticker']}: {'inviato' if ok else 'non inviato'}",
                         user_id=user["id"])
            if not decision["notifications"]:
                ok = tg.send(channels.digest_message(state_u, {
                    "today": TODAY.isoformat(), "assets": assets,
                    "data": data_info}))
                log.step(7, "Telegram", f"Riepilogo a {user['name']}",
                         "nessuna opportunità sopra soglia: inviato il riepilogo"
                         if ok else "riepilogo non inviato", user_id=user["id"])
        log.step(9, "Assistente", f"Risposte pronte per {user['name']}",
                 f"{len(state_u['chat_answers'])} argomenti personali, "
                 f"{len(state_u['plain_assets'])} investimenti spiegati in parole semplici, "
                 f"{len(state_u['plain_commitments'])} impegni dichiarati", user_id=user["id"])
        user_states.append(state_u)

    # Step 9 - analisi on demand (esempi dell'FDD, BR-09)
    demo_questions = [("MSFT", "Analizza Microsoft", "u1"),
                      ("ASML.AS", "Conviene comprare ASML oggi?", "u1"),
                      ("BTC-USD", "Che rischio ha Bitcoin adesso?", "u2"),
                      ("IEAC.AS", "Il corporate IG europeo è ancora interessante?", "u3")]
    for ticker, question, uid in demo_questions:
        if ticker not in assets:
            continue
        reports.append(build_report(assets[ticker], analyses[ticker],
                                    triggers_by_ticker[ticker],
                                    requested_by=uid, question=question, llm=gem))
        log.step(9, "Chief Investment Officer Agent", "Analisi on demand",
                 f"\"{question}\" -> report {ticker}, valutazione "
                 f"{analyses[ticker]['final_rating']}", user_id=uid)

    if gem.budget is not None:
        log.step(4, "Provider LLM (Gemini)", "Tetto di chiamate",
                 f"Tetto di {gem.budget} chiamate per questo ciclo (quota giornaliera del "
                 f"piano): {gem._spent()} usate, {gem.stats['over_budget']} analisi lasciate "
                 f"al calcolo per restare dentro il tetto")
    log.step(4, "Provider LLM (Gemini)", "Consumo del modello",
             f"{gem.stats['live']} chiamate al modello, {gem.stats['cached']} risposte "
             f"riusate dalla cache, {gem.stats['skipped']} salti (modalità offline), "
             f"{gem.stats['errors']} errori, {gem.stats['retries']} nuovi tentativi"
             f"{', ' + str(gem.stats['circuit_opens']) + ' sospensioni per errori di fila (limite di frequenza)' if gem.stats['circuit_opens'] else ''}; token "
             f"{gem.stats['prompt_tokens'] + gem.stats['output_tokens']}")
    log.step(10, "Sistema", "Ciclo completato",
             f"{len(assets)} asset analizzati, {len(all_triggers)} trigger, "
             f"{sum(len(u['decision']['notifications']) for u in user_states)} notifiche, "
             f"{sum(len(u['portfolio']['alerts']) for u in user_states)} alert, "
             f"{len(reports)} report")

    # L'elenco globale delle opportunita': uguale per tutti, usato sia dalla
    # pagina sia dalle notifiche, cosi' non possono divergere.
    opp = opportunita.globali(assets, analyses, triggers_by_ticker,
                              notif.SCORE_THRESHOLD, plain_generic)
    log.step(6, "Opportunity Scanner", "Opportunita' sopra soglia",
             f"{len(opp['lista'])} strumenti sopra {notif.SCORE_THRESHOLD} punti su 100, "
             f"uguali per tutti (nessun filtro di profilo)")

    # Identificativi (FIGI da OpenFIGI, ISIN da isin.json se compilato): la
    # card li mostra, e un ISIN sbagliato farebbe comprare lo strumento
    # sbagliato, quindi se manca resta dichiarato mancante.
    if opp["lista"]:
        try:
            ident = identificativi.arricchisci(
                {o["ticker"]: assets[o["ticker"]] for o in opp["lista"]
                 if o["ticker"] in assets})
            for o in opp["lista"]:
                a_id = assets.get(o["ticker"]) or {}
                if a_id.get("identita"):
                    o["identita"] = a_id["identita"]
            log.step(6, "Identificativi", "Codici degli strumenti",
                     f"{ident.get('con_isin', 0)} con ISIN su {len(opp['lista'])}, "
                     f"{ident.get('con_figi', 0)} con FIGI; l'ISIN si compila a mano "
                     f"in isin.json e viene validato")
        except Exception as e:          # una fonte giu' non ferma il ciclo
            log.step(6, "Identificativi", "Non disponibili", f"{type(e).__name__}")

    # Novita': con un controllo ogni due ore, notificare tutto vorrebbe dire
    # dodici messaggi al giorno sulle stesse cose. Qui si separa quello che e'
    # davvero nuovo, e solo quello va in notifica.
    nuove = {"nuove": [], "cambiate": [], "rinviate": [], "uscite": []}
    if notifica:
        nuove = visti.novita(opp["lista"])
        log.step(7, "Notifiche", "Che cosa e' nuovo", visti.riassunto(nuove))
        canali = {
            "push": channels.Push(enabled=True),
            "email": channels.Email(enabled=True),
            "telegram": tg if tg.enabled else None,
        }
        inviati = 0
        for voce in list(nuove.get("nuove", [])) + list(nuove.get("cambiate", [])):
            messaggio = channels.messaggio_opportunita(
                voce.get("opportunita", voce), tipo=voce.get("tipo"),
                motivo=voce.get("motivo"))
            esito = channels.consegna(messaggio, canali)
            inviati += 1 if esito.get("consegnato") else 0
            log.step(7, "Notifiche", messaggio["titolo"],
                     "; ".join(f"{k}: {v}" for k, v in (esito.get("esiti") or {}).items()))
        if not inviati and (nuove.get("nuove") or nuove.get("cambiate")):
            log.step(7, "Notifiche", "Nessun canale acceso",
                     "c'erano novità da annunciare ma nessun canale è configurato: "
                     "imposta NTFY_TOPIC per la notifica sul telefono")
    else:
        log.step(7, "Notifiche", "Non richieste",
                 "questo ciclo non invia notifiche (serve --notifica)")

    state = {
        "today": TODAY.isoformat(),
        "opportunita": opp,
        "novita": {k: [v.get("ticker") for v in nuove.get(k, [])]
                   for k in ("nuove", "cambiate", "rinviate", "uscite")},
        "assets": assets,
        "analyses": analyses,
        "triggers": triggers_by_ticker,
        "scanned": scanned,
        "skipped": skipped,
        "data": data_info,
        "source": source,
        "users": user_states,
        "reports": reports,
        "reports_by_ticker": reports_by_ticker,
        "plain_generic": plain_generic,
        "core_stats": core_stats,
        "run_log": log.entries,
        "provider_map": PROVIDER_MAP,
        "telegram": {"mode": tg.mode, "sent": tg.sent, "errors": tg.errors[:3]},
        "threshold": notif.SCORE_THRESHOLD,
        "llm": {"mode": gem.mode, "model": gem.model, "enabled": gem.enabled,
                "stats": gem.stats, "last_error": gem.last_error,
                "quota_error": gem.quota_error, "calls": gem.log[-40:]},
    }
    state["knowledge"] = assistant.build_knowledge(state, plain_generic, core_stats,
                                                   notif.SCORE_THRESHOLD,
                                                   notif.WEEKLY_LIMIT, WEIGHTS)
    return state
