"""Verifica del contesto di mercato senza toccare la rete.

Serve a provare la parte che in rete non si puo' provare a comando: che cosa
succede quando una fonte ufficiale risponde male. E rispondono male in modi
precisi, tutti visti dal vero su questa macchina:

* HTTP 500 o 404 (la chiave della serie e' cambiata);
* HTTP 200 con il corpo VUOTO (il Tesoro USA, se l'anno non esiste);
* HTTP 200 con dati FERMI da un anno e mezzo (la vecchia serie CISS della BCE);
* rete assente del tutto.

Il caso dei dati fermi e' il piu' insidioso dei quattro, perche' sembra un
successo: la fonte risponde, il numero e' un numero, la data non la guarda
nessuno. Qui si controlla che venga scartato.

    python tools/selftest_macro.py

Non chiama la rete: sostituisce `urlopen` con risposte finte nel formato esatto
delle fonti vere (csvdata della BCE, CSV del Tesoro, JSON del BLS, JSON-stat di
Eurostat, chart di Yahoo).
"""

from __future__ import annotations

import io
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import macro                               # noqa: E402
from engine.macro import Macro, snapshot               # noqa: E402

# Giorno finto da cui si contano le eta': un venerdi', cosi' le serie
# pubblicate nei giorni lavorativi sono fresche senza casi di fine settimana.
OGGI = date(2026, 10, 30)
CHIAMATE: list[str] = []


# --------------------------------------------------------------- risposte finte
def _csv_bce(key: str, righe, titolo="Serie di prova", unita="PCPA") -> bytes:
    """Il csvdata della BCE: intestazione piatta, una riga per osservazione,
    dalla piu' vecchia alla piu' recente."""
    out = ["KEY,FREQ,TIME_PERIOD,OBS_VALUE,OBS_STATUS,TITLE,UNIT"]
    for periodo, valore in righe:
        out.append(f"{key},D,{periodo},{valore},A,{titolo},{unita}")
    return ("\n".join(out) + "\n").encode("utf-8")


def _csv_tesoro(righe, reale: bool = False) -> bytes:
    """Il CSV del Tesoro USA, col BOM davanti come quello vero e dal piu'
    recente al piu' vecchio. I due file non scrivono le colonne allo stesso
    modo: la curva nominale dice "10 Yr", quella reale "10 YR". La differenza e'
    riprodotta di proposito, perche' e' una vera trappola e il modulo deve
    passarci sopra."""
    out = ['Date,"5 YR","7 YR","10 YR","30 YR"'] if reale else \
          ['Date,"3 Mo","2 Yr","10 Yr","30 Yr"']
    for riga in righe:
        out.append(",".join(str(c) for c in riga))
    return ("﻿" + "\n".join(out) + "\n").encode("utf-8")


def _json_bls(righe, stato="REQUEST_SUCCEEDED") -> bytes:
    dati = [{"year": str(a), "period": f"M{m:02d}", "value": f"{v}"} for a, m, v in righe]
    return json.dumps({"status": stato, "message": [],
                       "Results": {"series": [{"seriesID": "CUUR0000SA0",
                                               "data": dati}]}}).encode("utf-8")


def _json_eurostat(valori: dict, tempi: list[str]) -> bytes:
    return json.dumps({
        "version": "2.0", "class": "dataset", "source": "ESTAT",
        "updated": "2026-10-29T11:00:00+0100", "id": ["freq", "indic", "s_adj", "geo", "time"],
        "size": [1, 1, 1, 1, len(tempi)],
        "dimension": {"time": {"category": {"index": {t: i for i, t in enumerate(tempi)}}}},
        "value": valori}).encode("utf-8")


def _json_yahoo(data_iso: str, chiusura: float) -> bytes:
    import calendar as _cal
    import datetime as _dt
    ts = _cal.timegm(_dt.date.fromisoformat(data_iso).timetuple())
    return json.dumps({"chart": {"result": [{
        "meta": {"currency": "USD", "symbol": "^VIX", "fullExchangeName": "CBOE"},
        "timestamp": [ts],
        "indicators": {"quote": [{"open": [chiusura], "high": [chiusura],
                                  "low": [chiusura], "close": [chiusura],
                                  "volume": [0]}]}}], "error": None}}).encode("utf-8")


class _Ctx:
    """urlopen vero si usa con `with`: la finta deve fare lo stesso."""

    def __init__(self, data):
        self.data = io.BytesIO(data)

    def read(self):
        return self.data.read()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def installa(modo: str = "ok"):
    """modo: ok | http_500 | http_404 | vuoto | fermo | senza_rete | bls_rifiuta
    | eurostat_senza_valori"""

    def finto_urlopen(req, timeout=None, context=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        CHIAMATE.append(url)

        if modo == "senza_rete":
            raise urllib.error.URLError("getaddrinfo failed")
        if modo == "http_500":
            raise urllib.error.HTTPError(url, 500, "Internal Server Error", {},
                                         io.BytesIO(b"guasto"))
        if modo == "http_404":
            raise urllib.error.HTTPError(url, 404, "Not Found", {},
                                         io.BytesIO(b'{"status":404}'))
        if modo == "vuoto":
            return _Ctx(b"")

        # ------------------------------------------------- BCE: cambi e curve
        if "data-api.ecb.europa.eu" in url:
            if "/EXR/" in url:
                return _Ctx(_csv_bce("EXR.D.USD.EUR.SP00.A",
                                     [("2026-10-28", "1.1133"), ("2026-10-29", "1.1130"),
                                      ("2026-10-30", "1.1172")],
                                     "US dollar/Euro", "USD"))
            if "SR_10Y" in url:
                return _Ctx(_csv_bce("YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y",
                                     [("2026-10-28", "3.392748863"),
                                      ("2026-10-29", "3.3733145545")],
                                     "AAA yield curve - 10-year spot rate"))
            if "SR_2Y" in url:
                return _Ctx(_csv_bce("YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_2Y",
                                     [("2026-10-28", "2.0"), ("2026-10-29", "2.1")],
                                     "AAA yield curve - 2-year spot rate"))
            if "/CISS/" in url:
                if modo == "fermo":
                    # E' il comportamento vero della serie SS_CI: risponde 200 e
                    # consegna un valore del maggio 2025 come se fosse di oggi.
                    return _Ctx(_csv_bce("CISS.D.U2.Z0Z.4F.EC.SS_CI.IDX",
                                         [("2025-04-25", "0.1167"),
                                          ("2025-05-02", "0.094106")],
                                         "CISS", "PURE_NUMB"))
                return _Ctx(_csv_bce("CISS.D.U2.Z0Z.4F.EC.SS_CIN.IDX",
                                     [("2026-10-23", "0.0248"), ("2026-10-26", "0.0235"),
                                      ("2026-10-27", "0.0186"), ("2026-10-28", "0.0152"),
                                      ("2026-10-29", "0.0128")],
                                     "NEW CISS", "PURE_NUMB"))
            if "/FM/" in url:
                return _Ctx(_csv_bce("FM.D.U2.EUR.4F.KR.DFR.LEV",
                                     [("2026-10-29", "2.5"), ("2026-10-30", "2.5")],
                                     "Deposit facility", "PCPA"))

        # ------------------------------------------------------- Frankfurter
        if "frankfurter" in url:
            return _Ctx(json.dumps({"amount": 1.0, "base": "USD", "date": "2026-10-30",
                                    "rates": {"EUR": 0.89509}}).encode("utf-8"))

        # ------------------------------------------------------- Tesoro USA
        if "home.treasury.gov" in url:
            if "real_yield" in url:
                return _Ctx(_csv_tesoro([("10/30/2026", "2.25", "2.42", "2.60", "3.08"),
                                         ("10/29/2026", "2.31", "2.46", "2.63", "3.07")],
                                        reale=True))
            if modo == "fermo":
                return _Ctx(_csv_tesoro([("06/30/2026", "4.00", "4.10", "4.20", "4.50")]))
            # Il 3 mesi e' vuoto di proposito: capita, e non deve diventare zero
            # ne' portarsi via il resto della curva.
            return _Ctx(_csv_tesoro([("10/30/2026", "", "4.56", "4.94", "5.31"),
                                     ("10/29/2026", "4.18", "4.61", "4.98", "5.32")]))

        # ------------------------------------------------------------- Yahoo
        if "finance.yahoo.com" in url:
            return _Ctx(_json_yahoo("2026-10-30", 19.42))

        # --------------------------------------------------------------- BLS
        if "api.bls.gov" in url:
            if modo == "bls_rifiuta":
                return _Ctx(json.dumps({"status": "REQUEST_NOT_PROCESSED",
                                        "message": ["serie non trovata"],
                                        "Results": {}}).encode("utf-8"))
            if modo == "fermo":
                return _Ctx(_json_bls([(2025, 1, 320.0), (2025, 2, 321.0)]))
            return _Ctx(_json_bls([(2025, 8, 323.0), (2025, 9, 324.800),
                                   (2026, 8, 334.980), (2026, 9, 336.940)]))

        # ---------------------------------------------------------- Eurostat
        if "eurostat" in url:
            if modo == "eurostat_senza_valori":
                return _Ctx(_json_eurostat({}, ["2026-08", "2026-09", "2026-10"]))
            # Ultimo mese vuoto di proposito: va preso settembre, non ottobre.
            return _Ctx(_json_eurostat({"0": 98.1, "1": 97.5},
                                       ["2026-08", "2026-09", "2026-10"]))

        # ------------------------------------------------- cripto: Fear & Greed
        if "alternative.me" in url:
            return _Ctx(json.dumps({"name": "Fear and Greed Index",
                                    "data": [{"value": "30",
                                              "value_classification": "Fear",
                                              "timestamp": "1793404800"}],
                                    "metadata": {"error": None}}).encode("utf-8"))

        raise AssertionError(f"url non previsto dal finto: {url}")

    urllib.request.urlopen = finto_urlopen


def cliente(modo: str = "ok", **kw) -> Macro:
    installa(modo)
    CHIAMATE.clear()
    return Macro(use_cache=False, pace_s=0.0, today=OGGI, retry_wait_s=0.0, **kw)


def check(label: str, condition: bool, detail: str = "") -> bool:
    print(f"  [{'ok ' if condition else 'KO '}] {label}" + (f" - {detail}" if detail else ""))
    return bool(condition)


# ------------------------------------------------------------------ i controlli
def main() -> int:
    ok = True

    print("1. Risposte valide: ogni numero arriva con la sua data e la sua fonte")
    m = cliente("ok")
    fx = m.fx_eur(("USD",))
    ok &= check("il cambio della BCE e' letto bene",
                fx["USD"]["value"] == 1.1172, str(fx.get("USD", {}).get("value")))
    ok &= check("si prende l'ultima osservazione, non la prima",
                fx["USD"]["date"] == "2026-10-30", fx["USD"]["date"])
    ok &= check("il verso opposto del cambio e' calcolato",
                abs(fx["USD"]["eur_per_unit"] - 1 / 1.1172) < 1e-6)
    ok &= check("la fonte e' dichiarata", fx["USD"]["source"].startswith("BCE"),
                fx["USD"]["source"])
    ok &= check("si e' chiesto il CSV, non il JSON (altrimenti la BCE ignora format)",
                all("format=csvdata" in u for u in CHIAMATE if "ecb.europa.eu" in u))

    curva = m.euro_yield_curve()
    ok &= check("decennale AAA area euro", round(curva["euro_10y"]["value"], 4) == 3.3733,
                str(curva["euro_10y"]["value"]))
    ok &= check("l'inclinazione della curva euro e' calcolata",
                abs(curva["euro_curve_slope"]["value"] - (3.3733 - 2.1)) < 1e-4,
                str(curva["euro_curve_slope"]["value"]))
    ok &= check("il valore calcolato dichiara di essere calcolato",
                curva["euro_curve_slope"]["source"].startswith("calcolato"))

    stress = m.euro_stress()
    ok &= check("NEW CISS letto e tradotto in parole",
                stress["value"] == 0.0128 and stress["band"] == "basso",
                f"{stress['value']} -> {stress['band']}")
    ok &= check("la direzione su una settimana e' calcolata",
                stress["rising"] is False and stress["change_5d"] < 0,
                str(stress["change_5d"]))

    tasso = m.ecb_policy_rate()
    ok &= check("tasso BCE sui depositi", tasso["value"] == 2.5, str(tasso["value"]))

    usa = m.us_yield_curve()
    ok &= check("decennale USA dal CSV col BOM", usa["us_10y"]["value"] == 4.94,
                str(usa["us_10y"]["value"]))
    ok &= check("si prende la riga piu' recente del file, non la prima",
                usa["us_10y"]["date"] == "2026-10-30", usa["us_10y"]["date"])
    ok &= check("la cella vuota non diventa zero: il 3 mesi manca e lo dice",
                "us_3m" not in usa
                and any("3 mesi" in g["what"] for g in m.gaps), str(sorted(usa)))
    ok &= check("una cella vuota non si porta via il resto della curva",
                {"us_2y", "us_10y", "us_30y"} <= set(usa), str(sorted(usa)))
    ok &= check("inflazione attesa = nominale meno reale",
                abs(usa["us_breakeven_10y"]["value"] - 2.34) < 1e-6,
                str(usa["us_breakeven_10y"]["value"]))
    ok &= check("l'inclinazione USA sa di non essere invertita",
                usa["us_curve_slope"]["inverted"] is False)

    vix = m.vix()
    ok &= check("VIX via providers.Yahoo", vix and vix["value"] == 19.42, str(vix))

    cpi = m.us_inflation()
    ok &= check("indice dei prezzi USA", cpi["value"] == 336.94, str(cpi["value"]))
    ok &= check("la variazione annuale usa lo stesso mese dell'anno prima",
                cpi["yoy_pct"] == 3.74 and cpi["yoy_basis"] == "2025-09",
                f"{cpi['yoy_pct']}% su {cpi.get('yoy_basis')}")
    ok &= check("il mensile porta il periodo, non solo la data di fine mese",
                cpi["period"] == "2026-09" and cpi["date"] == "2026-09-30",
                f"{cpi['period']} / {cpi['date']}")

    esi = m.euro_sentiment(("EU27_2020",))
    ok &= check("ESI: si prende l'ultimo mese che ha davvero un valore",
                esi["EU27_2020"]["period"] == "2026-09"
                and esi["EU27_2020"]["value"] == 97.5,
                f"{esi['EU27_2020']['period']} = {esi['EU27_2020']['value']}")
    ok &= check("ESI sotto la media storica e' riconosciuto",
                esi["EU27_2020"]["above_average"] is False)

    fng = m.crypto_sentiment()
    ok &= check("Fear & Greed cripto", fng["value"] == 30 and fng["classification"] == "Fear")
    ok &= check("quando le fonti rispondono l'unico buco e' la cella vuota",
                [g["what"] for g in m.gaps] == ["Rendimento USA 3 mesi"],
                "; ".join(g["what"] for g in m.gaps))

    print("\n2. Dati fermi: la fonte risponde 200, il numero c'e', ma e' vecchio")
    m = cliente("fermo")
    stress = m.euro_stress()
    ok &= check("la vecchia serie CISS (maggio 2025) viene scartata", stress is None,
                str(stress))
    ok &= check("il motivo dice che la serie e' ferma e da che giorno",
                any("ferma" in g["why"] and "2025-05-02" in g["why"] for g in m.gaps),
                "; ".join(g["why"] for g in m.gaps))
    usa = m.us_yield_curve()
    ok &= check("la curva USA di quattro mesi fa viene scartata",
                "us_10y" not in usa and "us_breakeven_10y" not in usa,
                str(sorted(usa)))
    cpi = m.us_inflation()
    ok &= check("l'indice dei prezzi fermo a febbraio 2025 viene scartato", cpi is None)
    ok &= check("ogni scarto lascia la sua riga tra i buchi", len(m.gaps) >= 4,
                f"{len(m.gaps)} buchi")
    ok &= check("niente di scartato finisce comunque nei dati",
                all(not p.get("stale") for p in (usa or {}).values()))

    print("\n3. HTTP 500: la fonte e' giu', il ciclo non si ferma")
    m = cliente("http_500")
    ok &= check("nessuna eccezione, risposta assente", m.euro_stress() is None)
    ok &= check("il codice di errore e' scritto nel motivo",
                any("500" in g["why"] for g in m.gaps),
                "; ".join(g["why"] for g in m.gaps))
    ok &= check("un guasto passeggero viene riprovato una volta",
                m.stats["retries"] == 1 and len(CHIAMATE) == 2,
                f"{m.stats['retries']} nuovi tentativi, {len(CHIAMATE)} chiamate")
    m = cliente("http_404")
    ok &= check("una chiave sbagliata (404) non viene riprovata",
                m.euro_stress() is None and m.stats["retries"] == 0,
                f"{m.stats['retries']} nuovi tentativi")

    print("\n4. HTTP 200 con corpo vuoto: e' un guasto, non un dato")
    m = cliente("vuoto")
    usa = m.us_yield_curve()
    ok &= check("la curva USA non viene costruita sul vuoto", usa == {}, str(usa))
    ok &= check("il motivo distingue il vuoto dall'errore",
                any("corpo vuoto" in g["why"] for g in m.gaps),
                "; ".join(g["why"] for g in m.gaps)[:90])
    ok &= check("il corpo vuoto non viene messo in cache",
                not list(macro.CACHE_DIR.glob(f"macro_us_curve_nominal_{OGGI}.json"))
                if macro.CACHE_DIR.exists() else True)
    ok &= check("nessun numero inventato al posto del vuoto", m.us_inflation() is None)

    print("\n5. Eurostat risponde 200 ma senza valori (il caso geo=EA20)")
    m = cliente("eurostat_senza_valori")
    esi = m.euro_sentiment(("EA20",))
    ok &= check("niente valori, niente dato", esi == {}, str(esi))
    ok &= check("il motivo lo dice in chiaro",
                any("senza valori" in g["why"] for g in m.gaps),
                "; ".join(g["why"] for g in m.gaps))
    m = cliente("bls_rifiuta")
    ok &= check("un rifiuto del BLS non diventa un numero", m.us_inflation() is None)
    ok &= check("il messaggio del BLS viene riportato",
                any("serie non trovata" in g["why"] for g in m.gaps),
                "; ".join(g["why"] for g in m.gaps))

    print("\n6. Rete assente: snapshot completo, tutto dichiarato, nessuna eccezione")
    installa("senza_rete")
    CHIAMATE.clear()
    s = snapshot(profile={"asset_classes": ["Azioni", "Crypto"]}, use_cache=False,
                 today=OGGI, retry_wait_s=0.0)
    ok &= check("lo snapshot torna comunque un dizionario", isinstance(s, dict))
    ok &= check("nessuna serie raccolta", s["coverage"]["collected"] == 0,
                str(s["coverage"]))
    ok &= check("ogni buco ha il suo perche'",
                all(g.get("what") and g.get("why") for g in s["missing"]),
                f"{len(s['missing'])} buchi")
    ok &= check("si capisce che il problema e' la rete",
                sum("non raggiungibile" in g["why"] for g in s["missing"]) >= 8,
                f"{sum('non raggiungibile' in g['why'] for g in s['missing'])} su "
                f"{len(s['missing'])}")
    ok &= check("nessuna fonte risulta aver risposto", s["sources"]["count"] == 0)
    ok &= check("senza dati non si scrive nessuna frase", s["summary"] == {})

    print("\n7. Snapshot con tutte le fonti in piedi")
    installa("ok")
    CHIAMATE.clear()
    s = snapshot(profile={"asset_classes": ["Azioni", "ETF", "Crypto"]}, use_cache=False,
                 today=OGGI, retry_wait_s=0.0)
    serie = s["series"]
    ok &= check("sono arrivate tutte le serie attese", s["coverage"]["collected"] >= 18,
                str(s["coverage"]["collected"]))
    # Vale anche per i valori calcolati: se l'inclinazione della curva non ha la
    # stessa forma delle altre, chi la mostra si rompe su quella e basta.
    CAMPI = ("value", "date", "period", "source", "unit", "label", "age_days")
    mancanti = {k: [c for c in CAMPI if p.get(c) is None]
                for k, p in serie.items() if any(p.get(c) is None for c in CAMPI)}
    ok &= check("ogni osservazione, raccolta o calcolata, ha la stessa forma",
                not mancanti, str(mancanti))
    ok &= check("l'inflazione dell'area euro resta dichiarata mancante",
                any("area euro" in g["what"] for g in s["missing"])
                and not any("inflazione" in k for k in serie if "us" not in k),
                "; ".join(g["what"] for g in s["missing"]))
    ok &= check("le fonti che hanno risposto sono elencate",
                s["sources"]["count"] >= 8, str(s["sources"]["count"]))
    ok &= check("i valori calcolati sono separati da quelli raccolti",
                all(f.startswith("calcolato") for f in s["sources"]["computed"])
                and not any(f.startswith("calcolato") for f in s["sources"]["answered"]))
    ok &= check("il contesto e' riassunto in italiano semplice",
                len(s["summary"]) >= 5 and "stress" in s["summary"],
                str(sorted(s["summary"])))
    ok &= check("i numeri nelle frasi hanno la virgola, non il punto",
                "3,37" in s["summary"].get("senza_rischio", ""),
                s["summary"].get("senza_rischio", ""))
    ok &= check("le cripto si chiedono perche' sono nel profilo",
                s["crypto_requested"] and "crypto_sentiment" in serie)

    print("\n8. Profilo senza cripto: quella fonte non viene nemmeno interrogata")
    installa("ok")
    CHIAMATE.clear()
    s = snapshot(profile={"asset_classes": ["Obbligazioni", "ETF"]}, use_cache=False,
                 today=OGGI, retry_wait_s=0.0)
    ok &= check("nessuna chiamata ad alternative.me",
                not any("alternative.me" in u for u in CHIAMATE))
    ok &= check("e nessun dato cripto nello snapshot",
                "crypto_sentiment" not in s["series"] and not s["crypto_requested"])
    ok &= check("il resto del contesto c'e' tutto", s["coverage"]["collected"] >= 18,
                str(s["coverage"]["collected"]))

    print("\n9. La scadenza e' calcolata, non stimata a occhio")
    ok &= check("un mese si conta dalla sua fine",
                macro._parse_period("2026-09") == date(2026, 9, 30))
    ok &= check("la forma del BLS (2026 M09) e' capita",
                macro._parse_period("2026 M09") == date(2026, 9, 30))
    ok &= check("una data illeggibile non diventa oggi",
                macro._parse_period("pippo") is None
                and macro._parse_period("2026-13-45") is None)
    p, why = macro._point(1.0, "2026-10-29", "x", "%", "prova", "fx", OGGI)
    ok &= check("dentro la scadenza il dato passa", p is not None and why is None)
    p, why = macro._point(1.0, "2026-10-01", "x", "%", "prova", "fx", OGGI)
    ok &= check("oltre la scadenza il dato viene scartato con il motivo",
                p is None and "ferma" in why, str(why))
    ok &= check("il limite della serie giornaliera copre il fine settimana",
                macro.MAX_AGE_D["fx"] >= 4 and macro.MAX_AGE_D["us_curve"] >= 4,
                f"fx {macro.MAX_AGE_D['fx']} giorni")
    ok &= check("il trattino e la cella vuota non diventano zero",
                macro._as_float("-") is None and macro._as_float("") is None
                and macro._as_float("N/A") is None and macro._as_float("4.94") == 4.94)
    ok &= check("le date americane sono convertite in ISO",
                macro._us_date("10/30/2026") == "2026-10-30"
                and macro._us_date("30/10/2026") is None)

    print("\n10. Ripiego sui cambi quando la BCE non risponde")

    def solo_bce_giu(req, timeout=None, context=None):
        url = req.full_url
        CHIAMATE.append(url)
        if "ecb.europa.eu" in url:
            raise urllib.error.HTTPError(url, 503, "Service Unavailable", {},
                                         io.BytesIO(b""))
        return _Ctx(json.dumps({"amount": 1.0, "base": "USD", "date": "2026-10-30",
                                "rates": {"EUR": 0.89509}}).encode("utf-8"))

    CHIAMATE.clear()
    urllib.request.urlopen = solo_bce_giu
    m = Macro(use_cache=False, pace_s=0.0, today=OGGI, retry_wait_s=0.0)
    fx = m.fx_eur(("USD",))
    ok &= check("il cambio arriva comunque", "USD" in fx,
                "; ".join(g["why"] for g in m.gaps))
    ok &= check("il ripiego e' dichiarato, non nascosto",
                fx["USD"]["source"].endswith("(ripiego)")
                and "BCE" in fx["USD"].get("fallback_from", ""),
                fx["USD"]["source"])
    ok &= check("il verso del cambio e' lo stesso della BCE",
                abs(fx["USD"]["value"] - 1.1172) < 0.001,
                str(fx["USD"]["value"]))

    print("\n" + ("Tutti i controlli superati." if ok else "ALCUNI CONTROLLI FALLITI."))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
