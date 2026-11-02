"""Controlla la regola delle opportunita' globali.

Questa e' la regola piu' importante del prodotto nuovo: decide che cosa viene
mostrato e che cosa viene notificato. Se sbaglia, l'utente riceve messaggi che
non doveva ricevere, o non riceve quelli che gli servivano.

    python tools/selftest_opportunita.py

Gira senza rete: gli asset e le analisi sono costruiti qui.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.opportunita import globali  # noqa: E402

VERDE, ROSSO, RESET = "\033[32m", "\033[31m", "\033[0m"
ok_totale = True


def check(label: str, condizione: bool, dettaglio: str = "") -> None:
    global ok_totale
    segno = f"{VERDE}ok {RESET}" if condizione else f"{ROSSO}KO {RESET}"
    print(f"  [{segno}] {label}" + (f" - {dettaglio}" if dettaglio else ""))
    if not condizione:
        ok_totale = False


def asset(ticker: str, nome: str, settore="Tecnologia", classe="Azioni",
          mercato="USA", prezzo=100.0) -> dict:
    return {
        "ticker": ticker, "name": nome, "sector": settore, "asset_class": classe,
        "market": mercato, "size": "Large cap", "currency": "USD",
        "tech": {"price": prezzo},
    }


def analisi(punteggio: int, valore: float | None = 120.0) -> dict:
    """Un'analisi finta. Con valore None lo strumento non ha stima di valore."""
    return {
        "opportunity_score": punteggio,
        "classification": "Opportunità forte" if punteggio >= 80 else "Da monitorare",
        "final_rating": "Buy",
        "risk_label": "Moderato",
        "scores": {"fundamental": 80, "technical": 70,
                   "valuation": None if valore is None else 75,
                   "sentiment": 60, "risk": 40},
        "plan": {"target": valore or 100.0, "stop_loss": 90.0, "entry_low": 99.0,
                 "entry_high": 101.0, "upside_to_target": 0.2,
                 "downside_to_stop": -0.1, "risk_reward": 2.0},
        "agents": {"valuation": {"fair_value": valore, "method": "utili x multiplo",
                                 "source": "modello quantitativo", "confidence": 80,
                                 "applicable": valore is not None}},
        "ai_sources": {"valuation": "modello quantitativo"},
    }


def main() -> int:
    print("1. La soglia: sopra entra, sotto no, e il pari non entra")
    assets = {"AAA": asset("AAA", "Alfa"), "BBB": asset("BBB", "Beta"),
              "CCC": asset("CCC", "Gamma")}
    an = {"AAA": analisi(90), "BBB": analisi(85), "CCC": analisi(70)}
    r = globali(assets, an, {}, 85)
    dentro = [o["ticker"] for o in r["lista"]]
    check("sopra soglia entra", dentro == ["AAA"], str(dentro))
    check("esattamente sulla soglia NON entra", "BBB" not in dentro,
          "la regola del motore e' 'maggiore di', non 'maggiore o uguale'")
    check("sotto soglia non entra", "CCC" not in dentro)
    scartati = {o["ticker"]: o["motivo"] for o in r["scartati"]}
    check("gli scartati portano il motivo", "BBB" in scartati and "85" in scartati["BBB"],
          scartati.get("BBB", "")[:60])
    # IL TESTO, non solo la regola. La regola era giusta da sempre, la frase
    # no: per uno strumento esattamente sulla soglia diceva "85 punti su 100,
    # sotto la soglia di 85", e quella frase si legge in pagina. E' venuta
    # fuori il giorno in cui due strumenti si sono fermati esattamente su 70.
    frase = scartati.get("BBB", "")
    check("e il motivo non si contraddice su chi sta esattamente sulla soglia",
          "sotto la soglia" not in frase, frase[:72])
    check("dice che la soglia va superata, non raggiunta",
          "superare" in frase, frase[:72])

    print("\n2. Senza stima di valore si monitora ma non si propone")
    assets = {"ETF": asset("ETF", "Un paniere", classe="ETF")}
    r = globali(assets, {"ETF": analisi(95, valore=None)}, {}, 85)
    check("non entra pur avendo 95 punti", not r["lista"])
    check("il motivo e' dichiarato, non muto",
          bool(r["scartati"]) and "conti" in r["scartati"][0]["motivo"],
          r["scartati"][0]["motivo"][:70] if r["scartati"] else "nessun motivo")

    print("\n3. L'ordine: prima il punteggio piu' alto")
    assets = {t: asset(t, t) for t in ("AAA", "BBB", "CCC")}
    an = {"AAA": analisi(87), "BBB": analisi(95), "CCC": analisi(90)}
    r = globali(assets, an, {}, 85)
    check("ordinate per punteggio decrescente",
          [o["ticker"] for o in r["lista"]] == ["BBB", "CCC", "AAA"],
          str([o["score"] for o in r["lista"]]))

    print("\n4. Uguali per tutti: nessun filtro di profilo")
    # stesso ingresso, due "profili" diversi: il risultato non deve cambiare,
    # perche' globali() non riceve nemmeno un profilo. E' la garanzia che la
    # specifica "uguali per tutti" sia strutturale e non una promessa.
    assets = {"ASIA": asset("ASIA", "Titolo asiatico", mercato="Asia",
                            settore="Energia", classe="Azioni"),
              "USA": asset("USA", "Titolo americano")}
    an = {"ASIA": analisi(92), "USA": analisi(88)}
    r = globali(assets, an, {}, 85)
    check("entra anche un mercato che un profilo avrebbe escluso",
          [o["ticker"] for o in r["lista"]] == ["ASIA", "USA"],
          str([o["ticker"] for o in r["lista"]]))
    import inspect
    firma = inspect.signature(globali)
    check("la funzione non accetta nemmeno un profilo",
          not any("profil" in p or "user" in p for p in firma.parameters),
          str(list(firma.parameters)))

    print("\n5. I dati che la card deve poter mostrare")
    r = globali({"AAA": asset("AAA", "Alfa")}, {"AAA": analisi(90)}, {}, 85)
    o = r["lista"][0]
    attesi = ["ticker", "name", "score", "classification", "sector", "asset_class",
              "market", "currency", "price", "target", "stop_loss", "entry_low",
              "entry_high", "upside", "downside", "risk_reward", "risk_label",
              "risk_score", "scores", "reasons", "valuation_method",
              "valuation_confidence"]
    mancanti = [k for k in attesi if k not in o]
    check("ci sono tutti i campi richiesti", not mancanti, ", ".join(mancanti) or "22 campi")
    check("i punteggi per componente ci sono",
          set(o["scores"]) == {"fundamental", "technical", "valuation", "sentiment", "risk"},
          str(sorted(o["scores"])))

    print("\n6. Un'analisi mancante non fa esplodere il ciclo")
    r = globali({"AAA": asset("AAA", "Alfa"), "ZZZ": asset("ZZZ", "Zeta")},
                {"AAA": analisi(90)}, {}, 85)
    check("lo strumento senza analisi viene saltato",
          [o["ticker"] for o in r["lista"]] == ["AAA"])

    print("\n7. L'ultima seduta di borsa non e' la data delle cripto")
    # Difetto vero, trovato di domenica: le cripto trattano sette giorni su
    # sette, quindi avevano una barra piu' recente di tutti e il programma
    # dichiarava "ultima seduta domenica" mentre le borse erano chiuse da
    # venerdi'. Qui si verifica che le due date restino distinte.
    import pathlib

    from engine import pipeline
    from engine import plain as pl
    sorgente = pathlib.Path(pipeline.__file__).read_text(encoding="utf-8")
    check("l'ultima seduta esclude gli strumenti continui",
          "CONTINUI" in sorgente and 'asset_class"] not in CONTINUI' in sorgente)
    check("le cripto hanno una data loro", '"last_bar_continui"' in sorgente)
    testo_plain = pathlib.Path(pl.__file__).read_text(encoding="utf-8")
    check("il racconto dice 'seduta di borsa', non 'seduta'",
          "ultima seduta di borsa" in testo_plain)
    check("e nomina le cripto a parte quando la data differisce",
          "cripto al" in testo_plain)
    # Secondo difetto della stessa famiglia, trovato di lunedi' a mercati
    # aperti: la barra di oggi non e' una chiusura, e mentre l'Europa tratta
    # l'America e' ferma a venerdi'. Un prezzo provvisorio presentato come
    # chiusura fa decidere su un numero che fra un'ora e' diverso.
    check("dichiara quando la seduta e' ancora in corso",
          '"seduta_in_corso"' in sorgente)
    check("conta quanti strumenti sono su oggi e quanti sulla chiusura prima",
          '"su_oggi"' in sorgente and '"su_seduta_precedente"' in sorgente)
    check("e lo dice anche al cliente, non solo nel log",
          "provvisori" in testo_plain)

    print("\n8. I motivi arrivano dai segnali del motore")
    trig = {"AAA": [{"label": "Sottovalutazione"}, {"label": "Insider buying"},
                    {"label": "Breakout tecnico"}, {"label": "Quarto segnale"}]}
    r = globali({"AAA": asset("AAA", "Alfa")}, {"AAA": analisi(90)}, trig, 85)
    check("i motivi ci sono", r["lista"][0]["reasons"][:2] ==
          ["Sottovalutazione", "Insider buying"], str(r["lista"][0]["reasons"]))
    check("al massimo tre, per non riempire la card",
          len(r["lista"][0]["reasons"]) == 3, str(len(r["lista"][0]["reasons"])))

    print("\n" + ("Tutti i controlli superati." if ok_totale
                  else "ALCUNI CONTROLLI FALLITI."))
    return 0 if ok_totale else 1


if __name__ == "__main__":
    raise SystemExit(main())
