"""Interfaccia a riga di comando della demo AI Market Scout.

    python cli.py scan                 # ciclo giornaliero completo (step 2-10)
    python cli.py opportunities        # classifica Opportunity Score
    python cli.py analyze AMD          # analisi on demand (BR-09)
    python cli.py notify               # decisioni di notifica per utente (BR-06)
    python cli.py portfolio u1         # monitoraggio portafoglio (BR-08)
    python cli.py triggers             # trigger rilevati (BR-05)
    python cli.py decisions            # scelte di demo vs punti aperti FDD
    python cli.py build-web            # rigenera web/data.js per la dashboard
    python cli.py llm-check            # prova la connessione a Gemini

Analisi fatte dall'AI: con `--live` e la variabile GEMINI_API_KEY impostata,
valutazione, lettura delle notizie, revisione dei punteggi e testi passano da
Gemini; senza chiave il ciclo gira sul nucleo deterministico e lo dichiara.

Solo libreria standard: nessuna installazione, nessuna chiamata di rete.
"""

from __future__ import annotations

import argparse
import sys

from engine.decisions import DEMO_DECISIONS, OPEN_POINTS_LEFT
from engine.llm import DEFAULT_MODEL
from engine.pipeline import run_scan
from engine.scoring import WEIGHTS

RESET, BOLD, DIM = "\033[0m", "\033[1m", "\033[2m"
GREEN, YELLOW, RED, BLUE = "\033[32m", "\033[33m", "\033[31m", "\033[36m"


def h1(text: str) -> None:
    print(f"\n{BOLD}{text}{RESET}\n" + "-" * min(len(text), 78))


def color_score(s) -> str:
    if s is None:
        return f"{DIM}n.d.{RESET}"
    c = GREEN if s >= 80 else YELLOW if s >= 70 else DIM
    return f"{c}{s:>3}{RESET}"


def cmd_scan(state, args) -> None:
    h1("Ciclo di scansione - workflow FDD 3.1")
    for e in state["run_log"]:
        print(f"{DIM}{e['elapsed_ms']:>8.1f}ms{RESET}  "
              f"{BLUE}step {e['step']}{RESET}  {BOLD}{e['actor']}{RESET}: "
              f"{e['action']}\n            {e['detail']}")
    cmd_opportunities(state, args)
    cmd_notify(state, args)


def cmd_opportunities(state, args) -> None:
    h1("Opportunity Center - classifica per Opportunity Score (BR-04)")
    rows = sorted(state["analyses"].values(), key=lambda a: -a["opportunity_score"])
    limit = getattr(args, "limit", 15) or 15
    print(f"{'Ticker':<11}{'Score':>6} {'Classe':<24}{'F':>4}{'T':>4}{'V':>4}{'S':>4}{'R':>4}"
          f"  {'Rischio':<11}{'Target':>10}{'Upside':>8}  Rating")
    for a in rows[:limit]:
        asset = state["assets"][a["ticker"]]
        s, p = a["scores"], a["plan"]
        print(f"{a['ticker']:<11}{a['opportunity_score']:>6} {a['classification']:<24}"
              f"{color_score(s['fundamental'])} {color_score(s['technical'])} "
              f"{color_score(s['valuation'])} {color_score(s['sentiment'])} "
              f"{color_score(s['risk'])}  {a['risk_label']:<11}"
              f"{p['target']:>10.2f}{p['upside_to_target'] * 100:>7.1f}%  {a['final_rating']}")
    print(f"\n{DIM}Pesi: " + ", ".join(f"{k} {int(v * 100)}%" for k, v in WEIGHTS.items()) +
          f"; il rischio entra come (100 - Risk Score){RESET}")


def cmd_triggers(state, args) -> None:
    h1("Trigger di opportunità rilevati (BR-05)")
    for ticker, trs in sorted(state["triggers"].items()):
        for tr in trs:
            print(f"{ticker:<11}{tr['label']:<30}{tr['detail']}")


def cmd_analyze(state, args) -> None:
    ticker = args.ticker.upper()
    if ticker not in state["assets"]:
        near = [t for t in state["assets"] if ticker in t or
                ticker.lower() in state["assets"][t]["name"].lower()]
        if not near:
            sys.exit(f"Ticker {ticker} non presente nell'universo demo.")
        ticker = near[0]
    from engine.reports import build_report
    r = build_report(state["assets"][ticker], state["analyses"][ticker],
                     state["triggers"][ticker], requested_by="CLI",
                     question=f"Analizza {ticker}")
    h1(f"Report {r['report_id']} - {r['name']}")
    print(f"{BOLD}Executive Summary{RESET}\n{r['executive_summary']}\n")
    for s in r["sections"]:
        print(f"{BOLD}{s['title']}{RESET}\n{s['body']}\n")
    print(f"{BOLD}Principali rischi{RESET}")
    for x in r["risks"]:
        print(f"  - {x}")
    print(f"\n{BOLD}Scenari 12 mesi{RESET}")
    for s in r["scenarios"]:
        print(f"  {s['scenario']:<6}{s['price']:>12.2f}  {s['return'] * 100:>+7.1f}%  "
              f"p={s['probability']:.0%}  {DIM}{s['rationale']}{RESET}")
    p = r["plan"]
    print(f"\n{BOLD}Piano operativo{RESET} (DEMO-05, OP-12)\n"
          f"  ingresso {p['entry_low']}-{p['entry_high']}  stop {p['stop_loss']} "
          f"({p['downside_to_stop'] * 100:+.1f}%)  target {p['target']} "
          f"({p['upside_to_target'] * 100:+.1f}%)  R/R {p['risk_reward']:.2f}")
    print(f"\n{BOLD}Valutazione finale: {r['final_rating']}{RESET}  "
          f"(Opportunity Score {r['opportunity_score']}, {r['classification']})")
    print(f"{DIM}Narrativa: {r['narrative_engine']}{RESET}")


def cmd_notify(state, args) -> None:
    h1("Decisioni di notifica (BR-06, BR-07, A-07)")
    for u in state["users"]:
        d = u["decision"]
        print(f"\n{BOLD}{u['name']}{RESET} - {u['profile']['risk_profile']}, "
              f"mercati {'/'.join(u['profile']['markets'])}, "
              f"settori {'/'.join(u['profile']['sectors'])}, "
              f"canali {', '.join(u['channels'])}")
        print(f"{DIM}Notifiche già inviate questa settimana: "
              f"{u['notifications_this_week_before']}/3 -> slot disponibili "
              f"{d['slots_remaining_before']}{RESET}")
        if not d["notifications"]:
            print(f"  {YELLOW}nessuna notifica inviata{RESET}")
        for n in d["notifications"]:
            print(f"  {GREEN}>{RESET} {BOLD}{n['ticker']}{RESET} score "
                  f"{n['opportunity_score']} ({n['classification']}) - "
                  f"prezzo {n['price']} target {n['target_price']} "
                  f"upside {n['upside'] * 100:+.0f}% - rischio {n['risk_label']}")
            print(f"    motivi: {'; '.join(n['reasons'])}")
            print(f"    piano: ingresso {n['plan']['entry_low']}-{n['plan']['entry_high']}, "
                  f"stop {n['plan']['stop_loss']}, target {n['plan']['target']}, "
                  f"R/R {n['plan']['risk_reward']}")
            print(f"    canali: {', '.join(n['channels'])}  "
                  f"{DIM}priorità {n['priority']} (boost preferenze {n['priority_boost']}x){RESET}")
        for r in d["rejected"][:5]:
            print(f"  {DIM}x {r['ticker']:<10} score {r['score']:>3}  {r['reason']}{RESET}")


def cmd_portfolio(state, args) -> None:
    u = next((x for x in state["users"] if x["id"] == args.user or
              x["name"].lower().startswith(args.user.lower())), None)
    if not u:
        sys.exit("Utente non trovato: usa u1, u2 o u3.")
    p = u["portfolio"]
    h1(f"Portafoglio di {u['name']} (BR-08)")
    print(f"{'Ticker':<11}{'Qta':>10}{'Carico':>11}{'Prezzo':>11}{'Valore':>12}"
          f"{'P/L':>12}{'P/L %':>8}{'Peso':>7}{'DD':>8}  Rischio")
    for r in p["positions"]:
        c = GREEN if r["pl"] >= 0 else RED
        print(f"{r['ticker']:<11}{r['quantity']:>10.4g}{r['avg_price']:>11.2f}"
              f"{r['price']:>11.2f}{r['value']:>12,.0f}{c}{r['pl']:>12,.0f}"
              f"{r['pl_pct'] * 100:>7.1f}%{RESET}{r['weight'] * 100:>6.1f}%"
              f"{r['drawdown'] * 100:>7.1f}%  {r['risk_label']}")
    print(f"\nValore {p['total_value']:,.0f} - costo {p['total_cost']:,.0f} - "
          f"P/L {p['pl']:,.0f} ({p['pl_pct'] * 100:+.1f}%) - liquidità {p['cash']:,.0f}")
    print(f"Rischio di portafoglio {p['risk_score']} (max profilo {p['risk_ceiling']}), "
          f"HHI {p['hhi']}")
    print("\nAllocazione per asset class: " +
          ", ".join(f"{k} {v * 100:.1f}%" for k, v in p["allocation_by_class"].items()))
    print("Allocazione per settore:     " +
          ", ".join(f"{k} {v * 100:.1f}%" for k, v in p["allocation_by_sector"].items()))
    print(f"\n{BOLD}Alert (DEMO-13, OP-05){RESET}")
    for al in p["alerts"]:
        c = {"critical": RED, "serious": RED, "warning": YELLOW, "good": GREEN}[al["level"]]
        print(f"  {c}[{al['level']}]{RESET} {al['title']}\n      {DIM}{al['detail']}{RESET}")
    if not p["alerts"]:
        print("  nessun alert attivo")


def _wrap(text: str, width: int = 88, indent: str = "  ", bullet: bool = False) -> str:
    import textwrap
    first = indent + "- " if bullet else indent
    rest = indent + "  " if bullet else indent
    return "\n".join(textwrap.fill(p, width, initial_indent=first, subsequent_indent=rest)
                     for p in text.split("\n"))


def _user_or_exit(state, key):
    u = next((x for x in state["users"] if x["id"] == key or
              x["name"].lower().startswith(str(key).lower())), None)
    if not u:
        sys.exit("Utente non trovato: usa u1, u2 o u3.")
    return u


def cmd_explain(state, args) -> None:
    """Come l'agente spiega un investimento a un cliente (vista semplice)."""
    u = _user_or_exit(state, args.user)
    ticker = args.ticker.upper()
    if ticker not in state["assets"]:
        near = [t for t, a in state["assets"].items()
                if ticker in t or args.ticker.lower() in a["name"].lower()]
        if not near:
            sys.exit(f"Ticker {ticker} non presente nell'universo demo.")
        ticker = near[0]
    p = u["plain_assets"].get(ticker) or state["plain_generic"][ticker]
    lights = {"verde": GREEN, "giallo": YELLOW, "grigio": DIM}
    h1(f"{p['name']} spiegato a {u['name']}")
    print(f"{lights[p['light']]}* {p['light_label']}{RESET}\n")
    print(f"{BOLD}{p['headline']}{RESET}")
    print(_wrap(p["what_is_it"]))
    print(_wrap(p["price_sentence"]))
    print(_wrap(p["verdict"]))
    if p["why_now"]:
        print(f"\n{BOLD}Perché adesso{RESET}")
        for w in p["why_now"]:
            print(f"  - {BOLD}{w['title']}{RESET}\n{_wrap(w['text'], indent='    ')}")
    if p["not_now_reason"]:
        print(f"\n{BOLD}Perché non adesso{RESET}\n{_wrap(p['not_now_reason'])}")
    print(f"\n{BOLD}Quanto rischia{RESET}\n{_wrap(p['risk_plain'])}")
    print(f"\n{BOLD}In euro{RESET}")
    if not p["not_now_reason"]:
        print(_wrap(p["money"]["sentence"]))
    for s in p["scenarios_plain"]:
        print(_wrap(s["text"]))
    print(f"\n{BOLD}Che cosa fare{RESET}")
    for s in p["what_to_do"]:
        print(_wrap(s, bullet=True))
    print(f"\n{DIM}{_wrap(p['caveat'])}{RESET}")


def cmd_agent(state, args) -> None:
    """La vista semplice, in terminale: tutto quello che l'agente dice oggi."""
    u = _user_or_exit(state, args.user)
    g = u["plain_greeting"]
    h1(f"{g['line']}")
    print(_wrap(g["sub"]) + "\n")
    print(f"{BOLD}Che cosa ho fatto{RESET}")
    for s in u["plain_story"]:
        print(_wrap(s, bullet=True))
    notified = u["decision"]["notifications"]
    print(f"\n{BOLD}Che cosa le segnalo oggi{RESET}")
    if not notified:
        print(_wrap("Niente. Qui sotto trova comunque la situazione dei suoi investimenti."))
    for n in notified:
        p = u["plain_assets"][n["ticker"]]
        print(f"\n  {GREEN}* {p['light_label']}{RESET} - {BOLD}{p['name']}{RESET}")
        print(_wrap(p["what_is_it"], indent="    "))
        print(_wrap(p["money"]["sentence"], indent="    "))
        for w in p["why_now"][:3]:
            print(_wrap(f"{w['title']}: {w['text']}", indent="    ", bullet=True))
    pf = u["plain_portfolio"]
    print(f"\n{BOLD}I suoi investimenti{RESET}")
    print(_wrap(pf["summary"]))
    print(_wrap(pf["risk_sentence"]))
    print(_wrap(pf["concentration_sentence"]))
    for a in pf["alerts_plain"][:4]:
        print(_wrap(f"{a['title']}: {a['text']}", bullet=True))
    print(f"\n{BOLD}Di che cosa mi occupo io{RESET}")
    for c in u["plain_commitments"]:
        print(_wrap(c, bullet=True))
    print(f"\n{BOLD}Mi può chiedere, per esempio{RESET}")
    for c in u["chat_chips"][:6]:
        print(f"  \"{c}\"")


def cmd_decisions(state, args) -> None:
    h1("Scelte di demo sui punti aperti dell'FDD")
    for code, op, text, where in DEMO_DECISIONS:
        print(f"{BOLD}{code}{RESET} ({op})  {text}\n    {DIM}{where}{RESET}")
    h1("Punti aperti non risolti dalla demo")
    for code, text in OPEN_POINTS_LEFT:
        print(f"{BOLD}{code}{RESET}  {text}")


def cmd_build_web(state, args) -> None:
    from build_web import write_data
    path = write_data(state)
    print(f"Scritto {path}")
    print("Apri web/index.html nel browser (nessun server necessario).")


def cmd_llm_check(state, args) -> None:
    from engine.llm import Gemini
    g = Gemini(enabled=True)
    h1("Connessione a Gemini")
    res = g.check()
    if res["ok"]:
        print(f"{GREEN}OK{RESET} modello {res['model']}: {res['detail']} "
              f"({res.get('tokens', 0)} token)")
    else:
        print(f"{RED}Non riesco a usare Gemini{RESET}: {res['detail']}")
        if res.get("suggested"):
            print(f"\n{GREEN}La chiave funziona{RESET}: è il nome del modello a non andare "
                  f"bene. Esegui questi comandi e riapri il terminale:")
            print(f'  {BOLD}setx GEMINI_MODEL "{res["suggested"]}"{RESET}')
            print(f"  {BOLD}python cli.py llm-check{RESET}")
        else:
            print(DIM + "Imposta la chiave con:  $env:GEMINI_API_KEY = \"...\"  (PowerShell)\n"
                        "Modello diverso:        $env:GEMINI_MODEL = \"...\"" + RESET)

    # Il secondo modello: quello che regge il volume quando la quota del primo
    # finisce. Si controlla qui perche' il posto dove si guarda "funziona l'AI?"
    # deve essere uno solo.
    from engine.llm2 import PRONTI, Compatibile
    due = Compatibile(enabled=True)
    print()
    h1("Secondo modello (compatibile OpenAI)")
    if not due.api_key:
        print(f"{DIM}Non configurato: il ciclo usa solo il primo modello.{RESET}")
        print(f"{DIM}Per aggiungerlo, uno fra:{RESET}")
        for nome, (base, modello) in PRONTI.items():
            print(f'  {BOLD}setx LLM2_FORNITORE "{nome}"{RESET}  '
                  f'{DIM}+ setx LLM2_KEY "la-chiave"   ({modello}){RESET}')
        return
    res2 = due.check()
    if res2["ok"]:
        print(f"{GREEN}OK{RESET} {res2['base']} · modello {res2['model']}: "
              f"{res2['detail']} ({res2.get('tokens', 0)} token)")
        print(f"{DIM}Entra in gioco solo quando il primo non puo' rispondere: "
              f"quota esaurita, tetto di chiamate, o circuito aperto.{RESET}")
    else:
        print(f"{RED}Non riesco a usare il secondo modello{RESET}: {res2['detail'][:200]}")
        print(f"{DIM}base {res2.get('base')} · modello {res2.get('model')}{RESET}")


def cmd_onboarding(args) -> None:
    """Il questionario iniziale in terminale: nessun importo da dichiarare."""
    import json
    from engine import onboarding, profile_file
    from engine.users import RISK_CEILING

    h1("Qualche domanda, poi lavoro io")
    print(_wrap(onboarding.PRIVACY_NOTE) + chr(10))
    answers = {}
    for i, q in enumerate(onboarding.QUESTIONS, 1):
        print(f"{BOLD}{i}. {q['text']}{RESET}")
        print(_wrap(q["help"], indent="   "))
        for j, o in enumerate(q["options"], 1):
            print(f"   {BOLD}{j}{RESET}) {o['label']}")
        multi = q["kind"] == "multi"
        prompt = ("   Numeri separati da virgola (Invio per saltare): " if multi
                  else "   Numero (Invio per saltare): ")
        while True:
            raw = input(prompt).strip()
            if not raw:
                break
            try:
                picks = [int(x) for x in raw.replace(" ", "").split(",") if x]
                if not picks or any(p < 1 or p > len(q["options"]) for p in picks):
                    raise ValueError
                if not multi and len(picks) > 1:
                    raise ValueError
            except ValueError:
                print(f"   {YELLOW}Scelga tra 1 e {len(q['options'])}" +
                      (", anche più di uno separato da virgola." if multi else ".") + RESET)
                continue
            ids = [q["options"][p - 1]["id"] for p in picks]
            answers[q["id"]] = ids if multi else ids[0]
            break
        print()

    user = onboarding.profile_from_answers(answers)
    h1(onboarding.CLOSING["title"])
    for k, v in onboarding.recap_rows(user, RISK_CEILING):
        print(f"  {k:34s}{BOLD}{v}{RESET}")
    print(chr(10) + _wrap(onboarding.CLOSING["body"]))

    if input(chr(10) + "Salvo questo profilo? [s/N] ").strip().lower() not in ("s", "si", "sì", "y"):
        print(f"{DIM}Niente salvato.{RESET}")
        return
    payload = {
        "id": "me", "name": user["name"], "first_name": user["first_name"],
        "profile": user["profile"], "channels": user["channels"],
        "weekly_limit": user["weekly_limit"],
        "positions": [], "watchlist": [], "notifications_this_week": 0,
        "_creato_da": "questionario (cli.py onboarding)", "_risposte": answers,
    }
    profile_file.PROFILE_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{GREEN}Salvato in {profile_file.PROFILE_PATH.name}{RESET}")
    print(f"Ora provi:  {BOLD}python cli.py agent me --real{RESET}")


def cmd_profilo_nuovo(args) -> None:
    from engine import profile_file
    if profile_file.PROFILE_PATH.exists():
        h1("Profilo già presente")
        user, problems = profile_file.load()
        if user:
            p = user["profile"]
            soldi = (f"capitale {p['capital']} {p['currency']}" if p.get("capital")
                     else "nessun importo dichiarato")
            print(f"{GREEN}OK{RESET} {user['name']}: {p['risk_profile'].lower()}, {soldi}, "
                  f"{len(user['positions'])} posizioni, {len(user['watchlist'])} in watchlist")
            print(f"{DIM}File: {profile_file.PROFILE_PATH}{RESET}")
        else:
            print(f"{RED}Il file c'è ma non è utilizzabile:{RESET}")
            for pr in problems:
                print(f"  - {pr}")
        return
    path = profile_file.write_template()
    h1("Profilo creato")
    print(f"Ho scritto {path}.")
    print("Aprilo, metti i tuoi dati e le tue posizioni, poi lancia:")
    print(f"  {BOLD}python cli.py agent me --real{RESET}")


def cmd_telegram_id(args) -> None:
    from engine.channels import Telegram
    tg = Telegram(enabled=True)
    h1("Telegram")
    res = tg.whoami()
    if not res["ok"]:
        print(f"{RED}Non riesco a parlare col bot{RESET}: {res['detail']}")
        print(DIM + 'PowerShell:  $env:TELEGRAM_TOKEN = "il-token-di-BotFather"' + RESET)
        return
    print(f"{GREEN}Bot raggiunto{RESET}: @{res['bot']}")
    if not res["chats"]:
        print("Nessun messaggio ricevuto: scrivi un messaggio qualsiasi al bot, poi riprova.")
        return
    for c in res["chats"]:
        print(f"  chat id {BOLD}{c['id']}{RESET}  ({c['type']}, {c['name']})")
    print(DIM + '$env:TELEGRAM_CHAT_ID = "<il numero qui sopra>"' + RESET)


def cmd_data_check(args) -> None:
    from engine.providers import Yahoo
    from engine.real_universe import REAL_SPECS, load_real_universe
    h1("Dati reali disponibili")
    y = Yahoo()
    only = getattr(args, "only", None)
    tickers = [t.strip() for t in only.split(",")] if only else None
    def progress(i, n, sym):
        print(f"  scarico {i}/{n}: {sym}".ljust(46), end="\r", flush=True)

    assets, skipped = load_real_universe(y, only=tickers, on_progress=progress)
    print(" ".ljust(46))
    print(f"{'Ticker':12s}{'Sedute':>7}{'Ultima':>12}{'Bilanci':>9}{'News':>6}  Valutabile")
    for a in sorted(assets, key=lambda x: x["ticker"]):
        q = a["data_quality"]
        ok = f"{GREEN}sì{RESET}" if a["valuable"] else f"{DIM}no — {a.get('valuation_note') or 'dati assenti'}{RESET}"
        print(f"{a['ticker']:12s}{q['bars']:>7}{q['last_bar']:>12}"
              f"{q['fundamental_fields']:>9}{q['news']:>6}  {ok}")
    for s in skipped:
        print(f"{s['ticker']:12s}{RED}escluso{RESET}: {s['reason']}")
    print(f"\n{len(assets)} strumenti, {sum(1 for a in assets if a['valuable'])} valutabili, "
          f"{len(skipped)} esclusi. Chiamate: {y.stats['http']} in rete, "
          f"{y.stats['cache']} dalla cache ancora valida, "
          f"{y.stats.get('scaduti', 0)} riscaricate perche' scadute.")
    print(f"{DIM}Non disponibili senza contratto dati: operazioni degli insider, "
          f"bilanci di ETF e obbligazioni, metriche on-chain delle crypto.{RESET}")


def main() -> None:
    # Le opzioni del modello valgono sia prima sia dopo il comando
    # (`cli.py --live scan` e `cli.py scan --live` fanno la stessa cosa):
    # default SUPPRESS, così il sottocomando non sovrascrive il valore globale.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--live", action="store_true", default=argparse.SUPPRESS,
                        help="usa Gemini per le analisi qualitative (richiede GEMINI_API_KEY)")
    common.add_argument("--model", default=argparse.SUPPRESS,
                        help=f"modello Gemini da usare (default {DEFAULT_MODEL})")
    common.add_argument("--no-cache", action="store_true", default=argparse.SUPPRESS,
                        help="ignora la cache delle risposte del modello")
    common.add_argument("--llm-limit", type=int, default=argparse.SUPPRESS,
                        help="usa il modello solo sui primi N asset (utile sul piano gratuito)")
    common.add_argument("--llm-pace", type=float, default=argparse.SUPPRESS,
                        help="secondi di attesa tra due chiamate al modello (piano gratuito)")
    common.add_argument("--notifica", action="store_true", default=argparse.SUPPRESS,
                        help="invia le notifiche delle novita' (push ntfy, email, "
                             "Telegram secondo le variabili impostate)")
    common.add_argument("--llm-budget", type=int, default=argparse.SUPPRESS,
                        help="tetto di chiamate al modello per questo ciclo: serve a "
                             "dividere la quota giornaliera tra piu' cicli")
    common.add_argument("--real", action="store_true", default=argparse.SUPPRESS,
                        help="usa i dati di mercato veri (Yahoo Finance) invece dei sintetici")
    common.add_argument("--only", default=argparse.SUPPRESS,
                        help="limita l'universo a questi ticker, separati da virgola")
    common.add_argument("--threshold", type=int, default=argparse.SUPPRESS,
                        help="soglia di notifica sull'Opportunity Score (BR-06, default 85)")
    common.add_argument("--telegram", action="store_true", default=argparse.SUPPRESS,
                        help="invia davvero le notifiche del tuo profilo su Telegram")

    ap = argparse.ArgumentParser(description="Demo AI Market Scout & Investment Copilot",
                                 parents=[common])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan", help="ciclo giornaliero completo", parents=[common])
    op = sub.add_parser("opportunities", help="classifica Opportunity Score", parents=[common])
    op.add_argument("--limit", type=int, default=15)
    sub.add_parser("triggers", help="trigger rilevati", parents=[common])
    an = sub.add_parser("analyze", help="analisi on demand di un asset", parents=[common])
    an.add_argument("ticker")
    sub.add_parser("notify", help="decisioni di notifica per utente", parents=[common])
    po = sub.add_parser("portfolio", help="monitoraggio portafoglio", parents=[common])
    po.add_argument("user", nargs="?", default="u1")
    ex = sub.add_parser("explain", help="un investimento spiegato in parole semplici",
                        parents=[common])
    ex.add_argument("ticker")
    ex.add_argument("--user", default="u1")
    ag = sub.add_parser("agent", help="la vista semplice in terminale: cosa dice l'agente oggi",
                        parents=[common])
    ag.add_argument("user", nargs="?", default="u1")
    sub.add_parser("decisions", help="scelte di demo vs punti aperti", parents=[common])
    sub.add_parser("build-web", help="rigenera web/data.js", parents=[common])
    sub.add_parser("llm-check", help="prova la connessione a Gemini", parents=[common])
    sub.add_parser("onboarding", help="il questionario iniziale: niente importi da dichiarare",
                   parents=[common])
    sub.add_parser("profilo-nuovo", help="crea profilo.json da compilare", parents=[common])
    sub.add_parser("telegram-id", help="trova il tuo chat id di Telegram", parents=[common])
    sub.add_parser("data-check", help="verifica i dati reali disponibili", parents=[common])
    args = ap.parse_args()

    if args.cmd == "llm-check":
        return cmd_llm_check(None, args)
    if args.cmd == "onboarding":
        return cmd_onboarding(args)
    if args.cmd == "profilo-nuovo":
        return cmd_profilo_nuovo(args)
    if args.cmd == "telegram-id":
        return cmd_telegram_id(args)
    if args.cmd == "data-check":
        return cmd_data_check(args)

    only = getattr(args, "only", None)
    state = run_scan(live=getattr(args, "live", False),
                     model=getattr(args, "model", None),
                     use_cache=not getattr(args, "no_cache", False),
                     llm_limit=getattr(args, "llm_limit", None),
                     llm_pace_s=getattr(args, "llm_pace", 0.0),
                     source="real" if getattr(args, "real", False) else "synthetic",
                     only=[t.strip() for t in only.split(",")] if only else None,
                     telegram=getattr(args, "telegram", False),
                     # --telegram implica --notifica: chi lo usava prima non
                     # deve scoprire che da oggi non riceve piu' niente
                     notifica=(getattr(args, "notifica", False)
                               or getattr(args, "telegram", False)),
                     threshold=getattr(args, "threshold", None),
                     llm_budget=getattr(args, "llm_budget", None))
    d = state["data"]
    print(f"{DIM}Dati: {d['source']}" +
          (f" · ultima seduta {d.get('last_bar')}" if d.get("last_bar") else "") +
          (f" · {d.get('with_fundamentals')} con bilanci, {d.get('with_news')} con notizie"
           if state["source"] == "real" else "") +
          f" · soglia di notifica {state['threshold']}{RESET}")
    if state["telegram"]["mode"] == "attivo":
        print(f"{GREEN}Telegram attivo: {state['telegram']['sent']} messaggi inviati{RESET}")
    for err in state["telegram"]["errors"]:
        print(f"{YELLOW}Telegram: {err}{RESET}")
    llm = state["llm"]
    if getattr(args, "live", False) and not llm["enabled"]:
        print(f"{YELLOW}Hai chiesto --live ma la chiave non c'è in questa sessione: "
              f"il ciclo gira sul nucleo deterministico.{RESET}\n"
              f"{DIM}PowerShell:  $env:GEMINI_API_KEY = \"...\"  "
              f"(poi verifica con: python cli.py llm-check){RESET}")
    print(f"{DIM}Analisi qualitative: {llm['mode']} · modello {llm['model']} · "
          f"{llm['stats']['live']} chiamate, {llm['stats']['cached']} dalla cache, "
          f"{llm['stats']['errors']} errori{RESET}")
    if llm.get("quota_error"):
        # la quota del piano gratuito è bassa e cambia nel tempo: se l'API la
        # dichiara, va detto subito e tradotto in un comando da usare domani
        fatte = llm["stats"]["live"]
        print(f"{YELLOW}Quota del piano esaurita dopo {fatte} chiamate{RESET} "
              f"({llm['quota_error']}).")
        print(f"{DIM}Il resto del ciclo è stato fatto dal calcolo, ed è dichiarato "
              f"a schermo. Per starci dentro riduci il perimetro, per esempio "
              f"--llm-limit 2, oppure attendi il rinnovo della quota.{RESET}")
    elif llm["last_error"]:
        print(f"{YELLOW}Ultimo errore del modello: {llm['last_error']}{RESET}")
    {"scan": cmd_scan, "opportunities": cmd_opportunities, "triggers": cmd_triggers,
     "analyze": cmd_analyze, "notify": cmd_notify, "portfolio": cmd_portfolio,
     "explain": cmd_explain, "agent": cmd_agent,
     "decisions": cmd_decisions, "build-web": cmd_build_web}[args.cmd](state, args)


if __name__ == "__main__":
    main()
