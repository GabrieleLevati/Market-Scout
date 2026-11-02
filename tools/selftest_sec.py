"""Verifica del modulo SEC senza chiamare la SEC.

Serve a provare la parte che non si puo' provare con la rete: che cosa succede
quando l'intestazione obbligatoria manca, quando due societa' usano tag diversi
per i ricavi, quando lo stesso deposito contiene due periodi, quando il ticker non
e' statunitense, e come finisce il confronto fra le due fonti nei quattro esiti.

    python tools/selftest_sec.py

Non chiama la rete: sostituisce `urlopen` con un finto EDGAR che risponde nel
formato vero degli endpoint della SEC (`company_tickers.json`, `companyfacts`,
`submissions`, ricerca full-text) e che, come la SEC, rifiuta con 403 chi non
dichiara il traffico.

I numeri dei dati finti sono quelli veri di NVIDIA e Apple, cosi' chi legge il
test riconosce i casi: sono loro ad avere messo in luce le trappole.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import sec as S                           # noqa: E402

RICHIESTE: list[dict] = []           # registro di tutto quello che e' stato chiesto


# ----------------------------------------------------------------- dati finti
def _p(end, val, filed, form="10-K", fp="FY", fy=2026, start=None, accn="x"):
    """Un punto XBRL come lo scrive la SEC: il valore non e' mai solo, porta
    sempre il periodo (`start`/`end`), il modulo che l'ha pubblicato e la data di
    deposito. Sono i tre campi su cui si inciampa."""
    p = {"end": end, "val": val, "filed": filed, "form": form, "fp": fp, "fy": fy,
         "accn": accn}
    if start:
        p["start"] = start
    return p


def _tag(unita, punti, label=""):
    return {"label": label, "units": {unita: punti}}


# ALFA e' modellata su NVIDIA: usa `Revenues` ed e' quella che mostra le trappole
# del periodo comparativo e della relazione per l'assemblea depositata dopo il 10-K.
FATTI_ALFA = {
    "cik": 1045810, "entityName": "ALFA CORP",
    "facts": {"dei": {}, "us-gaap": {
        "Revenues": _tag("USD", [
            # due esercizi, piu' una riesposizione dell'esercizio vecchio
            _p("2025-01-26", 130497000000, "2025-02-26", start="2024-01-29", fy=2025),
            _p("2025-01-26", 130500000000, "2026-02-25", start="2024-01-29", fy=2025),
            _p("2026-01-25", 215938000000, "2026-02-25", start="2025-01-27", fy=2026),
            # TRAPPOLA: questi due trimestri hanno LO STESSO `filed`. Il primo della
            # lista e' quello di un anno prima: un'implementazione che prende il
            # massimo per `filed` si porta a casa 46,7 miliardi invece di 96,2.
            _p("2025-07-27", 46743000000, "2026-08-26", form="10-Q", fp="Q2",
               fy=2027, start="2025-04-28"),
            _p("2026-07-26", 96221000000, "2026-08-26", form="10-Q", fp="Q2",
               fy=2027, start="2026-04-27"),
        ], label="Revenues"),
        # tag alternativo presente ma FERMO al 2018: non deve vincere
        "RevenueFromContractWithCustomerExcludingAssessedTax": _tag("USD", [
            _p("2018-01-28", 9714000000, "2018-02-28", start="2017-01-30", fy=2018),
        ]),
        "NetIncomeLoss": _tag("USD", [
            _p("2026-01-25", 120067000000, "2026-02-25", start="2025-01-27"),
            # la relazione per l'assemblea ripubblica lo stesso esercizio mesi dopo,
            # con un numero diverso e senza `fp`: non deve battere il bilancio
            _p("2026-01-25", 999000000000, "2026-05-12", form="DEF 14A", fp=None,
               start="2025-01-27"),
        ]),
        "EarningsPerShareDiluted": _tag("USD/shares", [
            _p("2026-01-25", 4.90, "2026-02-25", start="2025-01-27"),
        ]),
        "StockholdersEquity": _tag("USD", [
            _p("2026-01-25", 157293000000, "2026-02-25"),
        ]),
        "DebtCurrent": _tag("USD", [_p("2026-01-25", 999000000, "2026-02-25")]),
        "LongTermDebtNoncurrent": _tag("USD", [
            _p("2026-01-25", 7469000000, "2026-02-25")]),
        "OperatingLeaseLiabilityNoncurrent": _tag("USD", [
            _p("2026-01-25", 2572000000, "2026-02-25")]),
        "NetCashProvidedByUsedInOperatingActivities": _tag("USD", [
            _p("2026-01-25", 102718000000, "2026-02-25", start="2025-01-27")]),
        "PaymentsToAcquirePropertyPlantAndEquipment": _tag("USD", [
            _p("2026-01-25", 6042000000, "2026-02-25", start="2025-01-27")]),
    }},
}

# BETA e' modellata su Apple: `Revenues` esiste ma e' fermo al 2018, i ricavi veri
# stanno in un altro tag. E' il caso che smonta la scelta "primo tag presente".
FATTI_BETA = {
    "cik": 320193, "entityName": "BETA INC",
    "facts": {"dei": {}, "us-gaap": {
        "Revenues": _tag("USD", [
            _p("2018-09-29", 265595000000, "2018-11-05", start="2017-10-01", fy=2018),
        ]),
        "RevenueFromContractWithCustomerExcludingAssessedTax": _tag("USD", [
            _p("2025-09-27", 416161000000, "2025-10-31", start="2024-09-29", fy=2025),
        ]),
        "NetIncomeLoss": _tag("USD", [
            _p("2025-09-27", 112010000000, "2025-10-31", start="2024-09-29")]),
        "StockholdersEquity": _tag("USD", [_p("2025-09-27", 73733000000, "2025-10-31")]),
        # niente DebtCurrent: la parte a breve va ricomposta sommando le voci
        "LongTermDebtCurrent": _tag("USD", [_p("2025-09-27", 12350000000, "2025-10-31")]),
        "CommercialPaper": _tag("USD", [_p("2025-09-27", 7979000000, "2025-10-31")]),
        "LongTermDebtNoncurrent": _tag("USD", [
            _p("2025-09-27", 78328000000, "2025-10-31")]),
    }},
}

# GAMMA deposita il 20-F e pubblica in IFRS: nessun tag us-gaap.
FATTI_GAMMA = {"cik": 1046179, "entityName": "GAMMA LTD",
               "facts": {"dei": {}, "ifrs-full": {
                   "Revenue": _tag("TWD", [_p("2024-12-31", 2894308000000,
                                              "2025-04-16", form="20-F")])}}}

MAPPA = {"0": {"cik_str": 1045810, "ticker": "ALFA", "title": "ALFA CORP"},
         "1": {"cik_str": 320193, "ticker": "BETA", "title": "BETA INC"},
         "2": {"cik_str": 1046179, "ticker": "GAMMA", "title": "GAMMA LTD"}}

ANAGRAFICHE = {
    1045810: {"cik": "0001045810", "name": "ALFA CORP", "sic": "3674",
              "sicDescription": "Semiconductors & Related Devices",
              "exchanges": ["Nasdaq"], "tickers": ["ALFA"], "fiscalYearEnd": "0131",
              "entityType": "operating", "category": "Large accelerated filer",
              "filings": {"recent": {"form": ["10-K"] * 50}}},
    320193: {"cik": "0000320193", "name": "BETA INC", "sic": "3571",
             "sicDescription": "Electronic Computers", "exchanges": ["Nasdaq"],
             "tickers": ["BETA"], "fiscalYearEnd": "0926", "entityType": "operating",
             "category": "Large accelerated filer"},
    1046179: {"cik": "0001046179", "name": "GAMMA LTD", "sic": "3674",
              "sicDescription": "Semiconductors & Related Devices",
              "exchanges": ["NYSE"], "tickers": ["GAMMA"], "fiscalYearEnd": "1231",
              "entityType": "operating", "category": "Large accelerated filer"},
}

FATTI = {1045810: FATTI_ALFA, 320193: FATTI_BETA, 1046179: FATTI_GAMMA}

# Il testo con cui la SEC rifiuta chi non si dichiara, parola per parola.
TESTO_403 = (b"<html><title>SEC.gov | Request Rate Threshold Exceeded</title>"
             b"<body>Please declare your traffic by updating your user agent to "
             b"include company specific information.</body></html>")

UA_GENERICI = ("", "python-urllib/3.11", "Python-urllib/3.15", "curl/8.0")


# ------------------------------------------------------------- finto endpoint
class Ctx:
    """Il minimo che serve per stare in un `with urlopen(...) as r`."""

    def __init__(self, dati):
        self.dati = dati

    def __enter__(self):
        return self.dati

    def __exit__(self, *a):
        return False


def _risposta(oggetto) -> Ctx:
    return Ctx(io.BytesIO(json.dumps(oggetto).encode("utf-8")))


def installa_finto_edgar(mappa_ko: bool = False, modo: str = "ok"):
    """modo: ok | json_rotto | rete_giu | 500"""

    def finto_urlopen(req, timeout=None, context=None):
        ua = req.get_header("User-agent") or ""
        url = req.full_url
        RICHIESTE.append({"url": url, "ua": ua})

        # come la SEC vera: chi non dichiara il traffico viene respinto
        if ua.strip() in UA_GENERICI or ua.strip().startswith("Python-urllib"):
            raise urllib.error.HTTPError(url, 403, "Forbidden", {},
                                         io.BytesIO(TESTO_403))
        if modo == "rete_giu":
            raise urllib.error.URLError("getaddrinfo failed")
        if modo == "500":
            raise urllib.error.HTTPError(url, 500, "Internal Server Error", {},
                                         io.BytesIO(b"{}"))
        if modo == "json_rotto":
            return Ctx(io.BytesIO(b"<html>manutenzione</html>"))

        if "company_tickers.json" in url:
            if mappa_ko:
                raise urllib.error.HTTPError(url, 403, "Forbidden", {},
                                             io.BytesIO(TESTO_403))
            return _risposta(MAPPA)
        if "search-index" in url:
            # la ricerca full-text conosce solo ALFA
            if "ALFA" in url:
                return _risposta({"hits": {"hits": [
                    {"_source": {"display_names": ["ALFA CORP  (ALFA)  "
                                                   "(CIK 0001045810)"]}}] * 3}})
            return _risposta({"hits": {"hits": []}})
        if "companyfacts" in url:
            cik = int(url.rsplit("CIK", 1)[1].split(".")[0])
            if cik not in FATTI:
                raise urllib.error.HTTPError(url, 404, "Not Found", {},
                                             io.BytesIO(b"{}"))
            return _risposta(FATTI[cik])
        if "submissions" in url:
            cik = int(url.rsplit("CIK", 1)[1].split(".")[0])
            return _risposta(ANAGRAFICHE.get(cik, {}))
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(b"{}"))

    urllib.request.urlopen = finto_urlopen


def check(label: str, condition: bool, detail: str = "") -> bool:
    print(f"  [{'ok ' if condition else 'KO '}] {label}" + (f" - {detail}" if detail
                                                            else ""))
    return bool(condition)


def main() -> int:
    ok = True
    tmp = Path(tempfile.mkdtemp(prefix="selftest_sec_"))
    S.CACHE_DIR = tmp            # la cache del test non tocca quella vera
    os.environ.pop("SEC_USER_AGENT", None)

    print("1. User-Agent: la SEC risponde 403 a chi non dichiara il traffico")
    installa_finto_edgar()
    RICHIESTE.clear()
    s = S.Sec(use_cache=False, pace_s=0)
    b = s.bilanci("ALFA")
    ok &= check("con l'intestazione dichiarata i bilanci arrivano", b["disponibile"],
                str(b.get("motivo")))
    ok &= check("l'intestazione viene mandata a ogni chiamata",
                bool(RICHIESTE) and all(r["ua"] for r in RICHIESTE),
                f"{len(RICHIESTE)} chiamate")
    ok &= check("senza SEC_USER_AGENT si usa il valore di riserva, senza posta finta",
                S.user_agent() == S.UA_RISERVA and "@" not in S.UA_RISERVA,
                S.user_agent())
    ok &= check("e l'avviso dice come essere conformi",
                any("setx SEC_USER_AGENT" in a for a in b["avvisi"]))
    os.environ["SEC_USER_AGENT"] = "Mario Rossi (mario@esempio.it)"
    ok &= check("SEC_USER_AGENT, se c'e', viene rispettato",
                S.user_agent() == "Mario Rossi (mario@esempio.it)"
                and S.Sec(use_cache=False).ua == "Mario Rossi (mario@esempio.it)")
    os.environ.pop("SEC_USER_AGENT", None)

    s403 = S.Sec(use_cache=False, pace_s=0, user_agent_="python-urllib/3.11")
    b403 = s403.bilanci("ALFA")
    ok &= check("intestazione generica: 403 gestito, nessuna eccezione",
                b403["disponibile"] is False)
    # il motivo deve dire "ci hanno respinti", non "la societa' non esiste":
    # sono due diagnosi diverse e portano a due azioni diverse
    ok &= check("il motivo dice che e' un 403 e perche'",
                "403" in (b403["motivo"] or "")
                and "dichiarare il traffico" in (b403["motivo"] or ""),
                b403["motivo"] or "")
    ok &= check("e non scambia il rifiuto per una societa' inesistente",
                "non e' quotata" not in (b403["motivo"] or ""))
    ok &= check("e indica su quale fonte si ricade",
                b403.get("fonte_di_ripiego") == "Yahoo Finance")

    print("\n2. Il tag dei ricavi cambia da societa' a societa'")
    installa_finto_edgar()
    s = S.Sec(use_cache=False, pace_s=0)
    a = s.bilanci("ALFA")
    bb = s.bilanci("BETA")
    ok &= check("ALFA: ricavi dal tag Revenues",
                a["annuali"]["ricavi"]["tag"] == "Revenues"
                and a["annuali"]["ricavi"]["valore"] == 215938000000,
                f"{a['annuali']['ricavi']['tag']} = "
                f"{a['annuali']['ricavi']['valore']:,.0f}")
    ok &= check("BETA: ricavi dal tag del contratto con il cliente",
                bb["annuali"]["ricavi"]["tag"]
                == "RevenueFromContractWithCustomerExcludingAssessedTax"
                and bb["annuali"]["ricavi"]["valore"] == 416161000000,
                f"{bb['annuali']['ricavi']['tag']} = "
                f"{bb['annuali']['ricavi']['valore']:,.0f}")
    ok &= check("il tag fermo al 2018 non viene scelto solo perche' esiste",
                bb["annuali"]["ricavi"]["data"] == "2025-09-27",
                bb["annuali"]["ricavi"]["data"])
    ok &= check("BETA senza DebtCurrent: il debito a breve e' ricomposto sommando",
                bb["annuali"]["debito"]["valore"] == 98657000000
                and "CommercialPaper" in bb["annuali"]["debito"]["tag"],
                f"{bb['annuali']['debito']['valore']:,.0f} "
                f"({bb['annuali']['debito']['tag']})")

    print("\n3. Il periodo si sceglie per 'end', mai per 'filed'")
    q = a["trimestrali"]["ricavi"]
    ok &= check("trimestre corrente, non il comparativo di un anno prima",
                q["valore"] == 96221000000 and q["data"] == "2026-07-26",
                f"{q['valore']:,.0f} al {q['data']}")
    ok &= check("i due periodi venivano dallo stesso deposito",
                q["depositato_il"] == "2026-08-26", q["depositato_il"])
    ok &= check("a pari 'end' vince la riesposizione piu' recente",
                S._ultimo({k: v for k, v in
                           S._per_data([_p("2025-01-26", 130497000000, "2025-02-26",
                                           start="2024-01-29"),
                                        _p("2025-01-26", 130500000000, "2026-02-25",
                                           start="2024-01-29")]).items()})["val"]
                == 130500000000)
    ok &= check("un documento d'assemblea non batte il bilancio",
                a["annuali"]["utile_netto"]["valore"] == 120067000000
                and a["annuali"]["utile_netto"]["forma"] == "10-K",
                f"{a['annuali']['utile_netto']['valore']:,.0f} da "
                f"{a['annuali']['utile_netto']['forma']}")
    ok &= check("il periodo annuale non viene confuso con un trimestre",
                a["annuali"]["ricavi"]["data"] == "2026-01-25"
                and a["annuali"]["ricavi"]["inizio"] == "2025-01-27")
    ok &= check("il flusso di cassa libero e' derivato e dichiarato tale",
                a["annuali"]["flusso_cassa_libero"]["valore"] == 96676000000
                and "non pubblica" in a["annuali"]["flusso_cassa_libero"]["derivata"],
                f"{a['annuali']['flusso_cassa_libero']['valore']:,.0f}")

    print("\n4. Ticker non statunitense: assente dalla mappa, e lo dice")
    RICHIESTE.clear()           # da qui in avanti guardiamo chi viene interrogato
    for t in ("ISP.MI", "ENI.MI", "NESN.SW"):
        bx = s.bilanci(t)
        ok &= check(f"{t}: nessun dato, motivo scritto",
                    bx["disponibile"] is False
                    and "non e' nella mappa ufficiale" in (bx["motivo"] or "")
                    and "Stati Uniti" in (bx["motivo"] or ""),
                    (bx["motivo"] or "")[:60])
    bx = s.bilanci("ISP.MI")
    ok &= check("nessun buco silenzioso: dice su quale fonte si ricade",
                bx.get("fonte_di_ripiego") == "Yahoo Finance")
    ok &= check("quando la mappa ufficiale risponde, non si interroga la ricerca",
                not any("search-index" in r["url"] for r in RICHIESTE))
    g = s.bilanci("GAMMA")
    ok &= check("chi deposita in IFRS (20-F) viene dichiarato, non finto",
                g["disponibile"] is False and "ifrs-full" in (g["motivo"] or "")
                and "20-F" in (g["motivo"] or ""), (g["motivo"] or "")[:70])

    print("\n5. Mappa ufficiale non raggiungibile: i due ripieghi, dichiarati")
    installa_finto_edgar(mappa_ko=True)
    RICHIESTE.clear()
    s2 = S.Sec(use_cache=False, pace_s=0)
    a2 = s2.bilanci("ALFA")
    ok &= check("col 403 sulla mappa i bilanci arrivano comunque",
                a2["disponibile"] and a2["cik"] == 1045810)
    ok &= check("l'origine del CIK e' dichiarata (tabella o ricerca)",
                "riserva" in (a2["cik_origine"] or "")
                or "ricerca" in (a2["cik_origine"] or ""), a2["cik_origine"] or "")
    ok &= check("ogni CIK della tabella di riserva ha un nome accanto",
                all(isinstance(v, tuple) and len(v) == 2 and v[0] > 0 and v[1]
                    for v in S.CIK_RISERVA.values()),
                f"{len(S.CIK_RISERVA)} societa'")
    sconosciuto = s2.bilanci("ZZZZ")
    ok &= check("un ticker che nessuno conosce non diventa un numero inventato",
                sconosciuto["disponibile"] is False
                and "tabella di riserva" in (sconosciuto["motivo"] or ""))

    print("\n6. Il confronto fra le due fonti, nei quattro esiti")
    installa_finto_edgar()
    s3 = S.Sec(use_cache=False, pace_s=0)
    dati_sec = s3.bilanci("ALFA")
    yahoo = {
        # concordano: lo stesso numero, con la data arrotondata a fine mese
        "annualTotalRevenue": [{"date": "2026-01-31", "value": 215938000000.0,
                                "currency": "USD"}],
        # scostamento accettabile: -3,9%
        "annualNetIncome": [{"date": "2026-01-31", "value": 125000000000.0,
                             "currency": "USD"}],
        # non concordano: +40%
        "annualDilutedEPS": [{"date": "2026-01-31", "value": 3.50, "currency": "USD"}],
        # debito: scostamento spiegato dal leasing
        "annualTotalDebt": [{"date": "2026-01-31", "value": 11040000000.0,
                             "currency": "USD"}],
        "annualFreeCashFlow": [{"date": "2026-01-31", "value": 96676000000.0,
                                "currency": "USD"}],
        # patrimonio netto assente: una delle due fonti manca il dato
    }
    c = S.confronta("ALFA", yahoo, dati_sec=dati_sec)
    m = c["metriche"]
    ok &= check("esito 1 - concordano (entro il 2%)",
                m["ricavi"]["verdetto"] == "concordano"
                and m["ricavi"]["scostamento_pct"] == 0.0,
                f"{m['ricavi']['scostamento_pct']}%")
    ok &= check("esito 2 - scostamento accettabile (entro il 10%)",
                m["utile_netto"]["verdetto"] == "scostamento accettabile"
                and -5 < m["utile_netto"]["scostamento_pct"] < -3,
                f"{m['utile_netto']['scostamento_pct']}%")
    ok &= check("esito 3 - non concordano (oltre il 10%)",
                m["utile_per_azione"]["verdetto"] == "non concordano"
                and m["utile_per_azione"]["scostamento_pct"] == 40.0,
                f"{m['utile_per_azione']['scostamento_pct']}%")
    ok &= check("esito 4 - una delle due fonti manca il dato",
                m["patrimonio_netto"]["verdetto"] == "una delle due fonti manca il dato"
                and m["patrimonio_netto"]["yahoo"] is None)
    ok &= check("ogni riga porta i due valori, le due date e il tag usato",
                all(m["ricavi"][k] is not None for k in
                    ("sec", "yahoo", "data_sec", "data_yahoo", "tag_sec")))
    ok &= check("lo scostamento sul debito e' spiegato dal leasing, non contato",
                m["debito"].get("spiegato_da_definizione") is True
                and "debito" in c["complessivo"]["differenze_di_definizione"]
                and "debito" not in c["complessivo"]["metriche_in_contrasto"],
                (m["debito"]["nota"] or "")[:60])
    ok &= check("la fiducia scende per la metrica in contrasto",
                c["complessivo"]["fattore_fiducia"] == 0.8
                and c["complessivo"]["metriche_in_contrasto"] == ["utile_per_azione"],
                f"x{c['complessivo']['fattore_fiducia']} "
                f"{c['complessivo']['verdetto']}")

    tutte_ok = dict(yahoo)
    tutte_ok["annualNetIncome"] = [{"date": "2026-01-31", "value": 120067000000.0}]
    tutte_ok["annualDilutedEPS"] = [{"date": "2026-01-31", "value": 4.90}]
    c2 = S.confronta("ALFA", tutte_ok, dati_sec=dati_sec)
    ok &= check("quando tutto coincide: 'i conti concordano', fiducia intera",
                c2["complessivo"]["verdetto"] == "i conti concordano"
                and c2["complessivo"]["fattore_fiducia"] == 1.0,
                c2["complessivo"]["motivo"])
    ok &= check("il motivo non dice 'tutte entro il 2%' se una differisce per "
                "definizione",
                "differisce solo per come le due fonti la definiscono"
                in c2["complessivo"]["motivo"])
    ok &= check("due date identiche sono lo stesso periodo (zero giorni e' valido)",
                S.confronta("ALFA", {"ricavi": {"valore": 215938000000.0,
                                                "data": "2026-01-25"}},
                            dati_sec=dati_sec)["metriche"]["ricavi"]["verdetto"]
                == "concordano")
    lontano = S.confronta("ALFA", {"ricavi": {"valore": 215938000000.0,
                                              "data": "2024-01-31"}},
                          dati_sec=dati_sec)["metriche"]["ricavi"]
    ok &= check("due periodi lontani non vengono confrontati",
                lontano["verdetto"] == "una delle due fonti manca il dato"
                and "periodi non confrontabili" in (lontano["nota"] or ""))
    senza_yahoo = [S.confronta("ALFA", x, dati_sec=dati_sec)["complessivo"]["verdetto"]
                   for x in (None, {}, [], "boh")]
    ok &= check("se Yahoo non ha dato niente, nessuna eccezione e verdetto onesto",
                set(senza_yahoo) == {"verifica non possibile"}, str(set(senza_yahoo)))
    ok &= check("un ticker vuoto non diventa una richiesta alla SEC",
                S.Sec(use_cache=False, pace_s=0).cik_di("")["motivo"]
                == "ticker vuoto: niente da cercare")
    c3 = S.confronta("ISP.MI", yahoo, dati_sec=s3.bilanci("ISP.MI"))
    ok &= check("senza la seconda fonte il verdetto e' 'verifica non possibile'",
                c3["complessivo"]["verdetto"] == "verifica non possibile"
                and c3["confronto_possibile"] is False
                and c3["complessivo"]["fonte_unica"] == "Yahoo Finance")
    ok &= check("e non abbassa la fiducia: non e' un disaccordo, e' un limite noto",
                c3["complessivo"]["fattore_fiducia"] == 1.0)

    print("\n7. Niente ferma il ciclo: la fonte giu' non solleva eccezioni (OP-06)")
    for modo in ("rete_giu", "json_rotto", "500"):
        installa_finto_edgar(modo=modo)
        sx = S.Sec(use_cache=False, pace_s=0)
        try:
            bx = sx.bilanci("ALFA")
            cx = S.confronta("ALFA", yahoo, dati_sec=bx)
            esito = (bx["disponibile"] is False and bx["motivo"]
                     and cx["complessivo"]["verdetto"] == "verifica non possibile")
            dettaglio = (bx["motivo"] or "")[:50]
        except Exception as e:                      # noqa: BLE001
            esito, dettaglio = False, f"ECCEZIONE {type(e).__name__}: {e}"
        ok &= check(f"{modo}: nessuna eccezione, motivo scritto", bool(esito), dettaglio)

    print("\n8. Cache: un file per fonte per giorno, e il secondo giro non chiama")
    installa_finto_edgar()
    RICHIESTE.clear()
    s4 = S.Sec(use_cache=True, pace_s=0)
    s4.bilanci("ALFA")
    chiamate_prima = len(RICHIESTE)
    atteso = tmp / f"sec_fatti_ALFA_{date.today().isoformat()}.json"
    ok &= check("il file di cache ha il nome previsto (fonte + simbolo + giorno)",
                atteso.exists(), atteso.name)
    s5 = S.Sec(use_cache=True, pace_s=0)
    b5 = s5.bilanci("ALFA")
    ok &= check("il secondo giro nello stesso giorno non tocca la rete",
                len(RICHIESTE) == chiamate_prima and s5.stats["http"] == 0
                and s5.stats["cache"] > 0,
                f"http {s5.stats['http']}, cache {s5.stats['cache']}")
    ok &= check("dalla cache escono gli stessi numeri",
                b5["annuali"]["ricavi"]["valore"] == 215938000000)
    salvato = json.loads(atteso.read_text(encoding="utf-8"))
    ok &= check("la cache e' potata ai tag usati, e lo dichiara",
                "_cache" in salvato
                and len(salvato["facts"]["us-gaap"])
                <= len(FATTI_ALFA["facts"]["us-gaap"]))
    gc = S.Sec(use_cache=True, pace_s=0).bilanci("GAMMA")
    gc2 = S.Sec(use_cache=True, pace_s=0).bilanci("GAMMA")
    ok &= check("anche dalla cache, chi pubblica in IFRS resta riconoscibile",
                gc["motivo"] == gc2["motivo"] and "ifrs-full" in (gc2["motivo"] or ""))

    print("\n9. Limite di frequenza: la pausa fra due chiamate c'e' davvero")
    ok &= check("la pausa dichiarata sta sotto le 10 richieste al secondo della SEC",
                S.PACE_S >= 0.1, f"{S.PACE_S} s fra due chiamate")
    installa_finto_edgar()
    s6 = S.Sec(use_cache=False, pace_s=0.05)
    inizio = time.monotonic()
    s6.bilanci("ALFA")
    durata = time.monotonic() - inizio
    ok &= check("tre chiamate di fila rispettano la pausa",
                durata >= 0.05 and s6.stats["http"] >= 2,
                f"{durata:.3f} s per {s6.stats['http']} chiamate")

    shutil.rmtree(tmp, ignore_errors=True)
    print("\n" + ("Tutti i controlli superati." if ok else "ALCUNI CONTROLLI FALLITI."))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
