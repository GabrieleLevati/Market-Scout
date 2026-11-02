"""Verifica del modulo degli identificativi senza chiamare OpenFIGI.

Serve a provare quello che con la rete non si puo' provare a comando: che cosa
succede quando OpenFIGI non conosce un ticker, quando risponde con il limite di
frequenza (429), quando la rete non c'e' affatto, quando la cache e' gia' piena,
e soprattutto che cosa succede agli ISIN scritti a mano - quelli giusti, quelli
di formato sbagliato e quelli con la cifra di controllo storta.

    python tools/selftest_identificativi.py

Non chiama la rete: sostituisce `urlopen` con un finto OpenFIGI che risponde nel
formato vero dell'endpoint `v3/mapping`, compresi i due modi veri di dire di no
(`{"warning": "No identifier found."}` per il codice sconosciuto,
`{"error": "Invalid idValue format."}` per il codice malfatto) e il rifiuto
`HTTP 413` sopra i dieci strumenti per richiesta.

I dati finti sono quelli veri che ho letto da OpenFIGI il 1 novembre 2026: il
FIGI di NVIDIA, la denominazione di LVMH, le quattro quotazioni dell'ETF iShares
Core DAX che non comprendono Xetra. Chi legge il test riconosce i casi, perche'
sono loro ad avere mostrato le trappole.
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
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import identificativi as I          # noqa: E402

RICHIESTE: list[list[dict]] = []        # tutto quello che e' stato chiesto


# ------------------------------------------------------------------ dati finti
def _q(figi, nome, ticker, borsa, tipo="Common Stock", settore="Equity",
       composito=None, classe="BBG001S00001", tipo2=None):
    """Una quotazione come la scrive OpenFIGI."""
    return {"figi": figi, "name": nome, "ticker": ticker, "exchCode": borsa,
            "compositeFIGI": composito or figi, "securityType": tipo,
            "marketSector": settore, "shareClassFIGI": classe,
            "securityType2": tipo2 or tipo, "securityDescription": ticker}


# chiave: (idValue, exchCode o marketSecDes o None) -> elenco di quotazioni
ANAGRAFICA = {
    ("NVDA", "US"): [_q("BBG000BBJQV0", "NVIDIA CORP", "NVDA", "US",
                        composito="BBG000BBJQV0", classe="BBG001S5TZJ6")],
    ("MC", "FP"): [_q("BBG000BC7Q05", "LVMH MOET HENNESSY LOUIS VUI", "MC", "FP",
                      classe="BBG001S81PV8")],
    ("SPY", "US"): [_q("BBG000BDTBL9", "SS SPDR S&P 500 ETF TRUST-US", "SPY", "US",
                       tipo="ETP", tipo2="Mutual Fund", classe="BBG001S72SM3")],
    ("BTC", "Curncy"): [_q("KKG000000M81", "bitcoin", "BTC", None, tipo="Crypto",
                           settore="Curncy", classe=None)],
    # NOVO-B.CO: Yahoo scrive il trattino, OpenFIGI no. La prima variante non
    # trova niente, la seconda si'.
    ("NOVOB", "DC"): [_q("BBG000F8TZ33", "NOVO NORDISK A/S-B", "NOVOB", "DC",
                         classe="BBG001S7F4L8")],
    # EXS1.DE: quattro quotazioni dello stesso ETF, nessuna su Xetra (GY). Serve
    # il ripiego senza borsa, e la classe di azioni e' unica.
    ("EXS1", None): [_q("BBG0015GJWS5", "ISHARES CORE DAX DE EUR ACC", "EXS1", "TH",
                        tipo="ETP", classe="BBG001SGNC72"),
                     _q("BBG0077HC4S7", "ISHARES CORE DAX DE EUR ACC", "EXS1", "QT",
                        tipo="ETP", classe="BBG001SGNC72"),
                     _q("BBG00FGXC4L1", "ISHARES CORE DAX DE EUR ACC", "EXS1", "GZ",
                        tipo="ETP", classe="BBG001SGNC72"),
                     _q("BBG012CFCCX1", "ISHARES CORE DAX DE EUR ACC", "EXS1", "NA",
                        tipo="ETP", classe="BBG001SGNC72")],
    # OMONIMI: lo stesso codice usato da societa' diverse. Qui il programma deve
    # rinunciare, non scegliere.
    ("XYZ", None): [_q("BBG000C02841", "XYZ HEALTH LTD", "XYZ", "AU"),
                    _q("BBG000C028N0", "XYZ MINING CORP", "XYZ", "CN",
                       classe="BBG001S00002")],
}

# ISIN -> quotazioni, per il riscontro nel verso ISIN -> FIGI
PER_ISIN = {
    "US67066G1040": [_q("BBG000BBJQV0", "NVIDIA CORP", "NVDA", "US",
                        classe="BBG001S5TZJ6"),
                     _q("BBG000BBJQX8", "NVIDIA CORP", "NVDA", "GY",
                        classe="BBG001S5TZJ6")],
    "FR0000121014": [_q("BBG000BC7Q05", "LVMH MOET HENNESSY LOUIS VUI", "MC", "FP",
                        classe="BBG001S81PV8")],
    # ISIN formalmente perfetto ma di un ALTRO strumento: e' l'errore pericoloso,
    # quello che la cifra di controllo non vede
    "US0378331005": [_q("BBG000B9XRY4", "APPLE INC", "AAPL", "US",
                        classe="BBG001S5N8V8")],
}

TESTO_413 = b"Request may only contain 10 mapping jobs."


class Ctx:
    """Il minimo che serve per stare in un `with urlopen(...) as r`."""

    def __init__(self, dati, headers=None):
        self.dati = dati
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.dati


def installa_finto_openfigi(modo: str = "ok", restanti: int = 24):
    """modo: ok | 429 | rete_giu | json_rotto | 500"""

    def finto_urlopen(req, timeout=None, context=None):
        job = json.loads(req.data.decode("utf-8"))
        RICHIESTE.append(job)
        url = req.full_url
        if len(job) > 10:
            raise urllib.error.HTTPError(url, 413, "Payload Too Large", {},
                                         io.BytesIO(TESTO_413))
        if modo == "rete_giu":
            raise urllib.error.URLError("getaddrinfo failed")
        if modo == "429":
            raise urllib.error.HTTPError(url, 429, "Too Many Requests",
                                         {"retry-after": "1"},
                                         io.BytesIO(b"Too Many Requests"))
        if modo == "500":
            raise urllib.error.HTTPError(url, 500, "Internal Server Error", {},
                                         io.BytesIO(b"{}"))
        if modo == "json_rotto":
            return Ctx(b"<html>manutenzione</html>")

        fuori = []
        for j in job:
            if j.get("idType") == "ID_ISIN":
                isin = j.get("idValue")
                # come OpenFIGI vero: una cifra di controllo sbagliata non e' un
                # codice sconosciuto, e' una richiesta malfatta
                if isin in PER_ISIN:
                    fuori.append({"data": PER_ISIN[isin]})
                elif I.valida_isin(isin)["valido"]:
                    fuori.append({"warning": "No identifier found."})
                else:
                    fuori.append({"error": "Invalid idValue format."})
                continue
            chiave = (j.get("idValue"), j.get("exchCode") or j.get("marketSecDes"))
            if chiave in ANAGRAFICA:
                fuori.append({"data": ANAGRAFICA[chiave]})
            else:
                fuori.append({"warning": "No identifier found."})
        headers = {"ratelimit-limit": "25", "ratelimit-remaining": str(restanti),
                   "ratelimit-reset": "60", "ratelimit-policy": "25;w=60"}
        return Ctx(json.dumps(fuori).encode("utf-8"), headers)

    urllib.request.urlopen = finto_urlopen


def check(label: str, condition: bool, detail: str = "") -> bool:
    print(f"  [{'ok ' if condition else 'KO '}] {label}" + (f" - {detail}" if detail
                                                            else ""))
    return bool(condition)


def scrivi(path: Path, contenuto) -> Path:
    path.write_text(json.dumps(contenuto, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return path


def asset(ticker, nome, settore="Tecnologia", classe="Azioni", target=None):
    """Un asset ridotto all'osso: `arricchisci` deve lavorare anche su questo."""
    a = {"ticker": ticker, "name": nome, "sector": settore, "asset_class": classe,
         "class_in_words": classe, "currency": "USD"}
    if target is not None:
        a["valuation"] = {"value": target, "method": "multiplo dei simili"}
    return a


def main() -> int:
    ok = True
    tmp = Path(tempfile.mkdtemp(prefix="selftest_ident_"))
    cache = tmp / "cache.json"
    isin_file = tmp / "isin.json"
    I.CACHE_PATH = cache                  # niente tocca i file veri del progetto
    I.ISIN_PATH = isin_file

    print("1. Cifra di controllo ISO 6166: ISIN veri accettati")
    veri = ["US67066G1040", "US0378331005", "NL0010273215", "DE0007164600",
            "IE00BK5BQT80", "FR0000121014", "IT0003128367", "DK0060534915",
            "KR7005930003", "JP3633400001"]
    esiti = {x: I.valida_isin(x) for x in veri}
    ok &= check("dieci ISIN veri passano il controllo",
                all(e["valido"] for e in esiti.values()),
                "; ".join(f"{k}: {v['motivo']}" for k, v in esiti.items()
                          if not v["valido"]) or "tutti validi")
    ok &= check("la cifra calcolata e' quella scritta nel codice",
                all(I.cifra_controllo_isin(x[:11]) == x[11] for x in veri))
    ok &= check("spazi e trattini di chi copia e incolla non sono un errore",
                I.valida_isin(" us-6706-6g10-40 ")["isin"] == "US67066G1040")

    print("\n2. ISIN alterati di una cifra: rifiutati")
    storti = {
        "US67066G1041": "ultima cifra cambiata",
        "US67066G1140": "una cifra in mezzo",
        "US07066G1040": "una cifra all'inizio",
        "IE00BK5BQT81": "ETF, ultima cifra",
        "FR0000121015": "LVMH, ultima cifra",
    }
    for codice, come in storti.items():
        e = I.valida_isin(codice)
        ok &= check(f"rifiutato ({come})", not e["valido"] and "cifra di controllo" in e["motivo"],
                    f"{codice}: {e['motivo'][:60]}")
    # Misura, non impressione. Due classi di errore separate, perche' la norma
    # garantisce la prima e non la seconda: dichiarare "tutti gli errori vengono
    # presi" sarebbe falso, e su un ISIN il falso costa un ordine sbagliato.
    import string
    cifre_tot = cifre_sfuggite = 0
    for x in veri:
        for i in range(2, 12):
            if not x[i].isdigit():
                continue
            for c in string.digits:
                if c == x[i]:
                    continue
                cifre_tot += 1
                if I.valida_isin(x[:i] + c + x[i + 1:])["valido"]:
                    cifre_sfuggite += 1
    ok &= check("una cifra sbagliata viene SEMPRE respinta (garanzia di Luhn)",
                cifre_tot > 500 and cifre_sfuggite == 0,
                f"{cifre_tot} cifre alterate, {cifre_sfuggite} sfuggite")
    lettere_tot = lettere_sfuggite = 0
    for x in veri:
        for i in range(2, 11):
            for c in string.digits + string.ascii_uppercase:
                if c == x[i]:
                    continue
                lettere_tot += 1
                if I.valida_isin(x[:i] + c + x[i + 1:])["valido"]:
                    lettere_sfuggite += 1
    quota = lettere_sfuggite / lettere_tot
    ok &= check("con le lettere in mezzo ne sfugge meno del 10%, e il modulo lo dice",
                lettere_tot > 1000 and quota < 0.10
                and "239" in I.cifra_controllo_isin.__doc__,
                f"{lettere_sfuggite} sfuggite su {lettere_tot} ({quota * 100:.1f}%): "
                f"e' il limite della norma, per questo esiste il riscontro con OpenFIGI")

    print("\n3. Formati sbagliati: rifiutati con il motivo giusto")
    casi = {
        "": "casella vuota",
        "US67066G104": "12 caratteri",
        "US67066G10400": "12 caratteri",
        "U167066G1040": "formato non valido",
        "US67066G104X": "formato non valido",
        "1267066G1040": "formato non valido",
    }
    for codice, atteso in casi.items():
        e = I.valida_isin(codice)
        ok &= check(f"{codice!r} rifiutato", not e["valido"] and atteso in e["motivo"],
                    e["motivo"][:70])

    print("\n4. isin.json mancante: non e' un errore, e' la condizione iniziale")
    voci, problemi = I.leggi_isin(isin_file)
    ok &= check("nessuna voce e nessun problema", voci == {} and problemi == [])
    a = [asset("NVDA", "NVIDIA")]
    installa_finto_openfigi()
    r = I.arricchisci(a, isin_path=isin_file, figi=I.OpenFigi(usa_cache=False, pausa_s=0))
    ide = a[0]["identita"]
    ok &= check("l'ISIN resta None e la fonte lo dichiara",
                ide["isin"] is None and ide["fonti"]["isin"] == I.NON_DISPONIBILE)
    ok &= check("la nota spiega all'utente che deve compilarlo a mano",
                any("isin.json" in n for n in ide["note"]), "; ".join(ide["note"])[:90])
    ok &= check("il FIGI invece c'e', e con la sua fonte",
                ide["figi"] == "BBG000BBJQV0" and ide["fonti"]["figi"].startswith("OpenFIGI"))
    ok &= check("e con lui denominazione ufficiale, tipo e borsa",
                ide["nome_ufficiale"] == "NVIDIA CORP" and ide["tipo"] == "Common Stock"
                and ide["borsa"] == "US",
                f"{ide['nome_ufficiale']} / {ide['tipo']} / {ide['borsa']}")
    ok &= check("l'ISIN compare fra i campi mancanti", "isin" in ide["mancanti"])

    print("\n5. isin.json compilato: valido, formato storto, cifra storta")
    scrivi(isin_file, {"NVDA": "US67066G1040", "MC.PA": "FR0000121014",
                       "SPY": "US78462F103", "BTC-USD": "",
                       "NOVO-B.CO": "DK0060534916",
                       "_note": ["questa riga non e' uno strumento"]})
    voci, problemi = I.leggi_isin(isin_file)
    ok &= check("l'ISIN valido e' accettato", voci["NVDA"]["valido"])
    ok &= check("il formato storto e' rifiutato",
                not voci["SPY"]["valido"] and "12 caratteri" in voci["SPY"]["motivo"])
    ok &= check("la cifra di controllo storta e' rifiutata",
                not voci["NOVO-B.CO"]["valido"]
                and "cifra di controllo" in voci["NOVO-B.CO"]["motivo"])
    ok &= check("la casella vuota non e' un errore, e' un buco",
                voci["BTC-USD"]["vuoto"] and not voci["BTC-USD"]["valido"])
    ok &= check("le note del file non vengono prese per strumenti", "_note" not in voci)
    ok &= check("i due codici sbagliati sono elencati come problemi",
                len(problemi) == 2, "; ".join(problemi)[:120])

    assets = [asset("NVDA", "NVIDIA", target=240.0), asset("MC.PA", "LVMH"),
              asset("SPY", "SPDR S&P 500", classe="ETF"),
              asset("NOVO-B.CO", "Novo Nordisk"), asset("BTC-USD", "Bitcoin",
                                                        classe="Crypto")]
    installa_finto_openfigi()
    RICHIESTE.clear()
    cli = I.OpenFigi(usa_cache=True, pausa_s=0, cache_path=cache)
    r = I.arricchisci(assets, isin_path=isin_file, figi=cli)
    per_ticker = {a["ticker"]: a["identita"] for a in assets}
    ok &= check("ISIN valido e riscontrato: usato, e la fonte dice che e' verificato",
                per_ticker["NVDA"]["isin"] == "US67066G1040"
                and "riscontro con OpenFIGI superati" in per_ticker["NVDA"]["fonti"]["isin"])
    ok &= check("ISIN di formato sbagliato: non usato, e la nota dice perche'",
                per_ticker["SPY"]["isin"] is None
                and any("RIFIUTATO" in n for n in per_ticker["SPY"]["note"]))
    ok &= check("ISIN con cifra storta: non usato",
                per_ticker["NOVO-B.CO"]["isin"] is None)
    ok &= check("due ISIN rifiutati nel riepilogo, due accettati",
                r["isin_rifiutati"] == 2 and r["con_isin"] == 2,
                f"rifiutati {r['isin_rifiutati']}, con isin {r['con_isin']}")
    ok &= check("il ticker col trattino e' stato trovato alla seconda variante",
                per_ticker["NOVO-B.CO"]["figi"] == "BBG000F8TZ33",
                str(per_ticker["NOVO-B.CO"]["figi"]))
    ok &= check("la cripto e' cercata nel settore valute, non su una borsa",
                per_ticker["BTC-USD"]["tipo"] == "Crypto"
                and per_ticker["BTC-USD"]["settore_mercato"] == "Curncy")
    ok &= check("ogni campo porta la sua fonte",
                all(c in per_ticker["NVDA"]["fonti"]
                    for c in ("isin", "figi", "nome_ufficiale", "tipo", "borsa",
                              "settore", "tipologia", "target")),
                ", ".join(sorted(per_ticker["NVDA"]["fonti"])))
    ok &= check("settore e tipologia restano quelli della scheda interna",
                per_ticker["NVDA"]["settore"] == "Tecnologia"
                and per_ticker["NVDA"]["fonti"]["settore"] == I.FONTE_SCHEDA)
    ok &= check("il prezzo obiettivo e' dichiarato come stima del motore",
                per_ticker["NVDA"]["target"] == 240.0
                and "motore" in per_ticker["NVDA"]["fonti"]["target"])
    ok &= check("nessuna richiesta supera i dieci strumenti di OpenFIGI",
                all(len(j) <= 10 for j in RICHIESTE),
                f"{len(RICHIESTE)} richieste, massimo {max(len(j) for j in RICHIESTE)} job")
    ok &= check("la riga pronta per la notifica porta i codici",
                "US67066G1040" in I.riga_identita(per_ticker["NVDA"])
                and "non disponibile" in I.riga_identita(per_ticker["SPY"]),
                I.riga_identita(per_ticker["NVDA"])[:80])

    print("\n6. ISIN perfetto ma di un ALTRO strumento: rifiutato")
    scrivi(isin_file, {"NVDA": "US0378331005"})      # ISIN di Apple su NVIDIA
    a = [asset("NVDA", "NVIDIA")]
    installa_finto_openfigi()
    r = I.arricchisci(a, isin_path=isin_file, figi=I.OpenFigi(usa_cache=False, pausa_s=0))
    ide = a[0]["identita"]
    ok &= check("l'ISIN non viene usato", ide["isin"] is None)
    ok &= check("il motivo nomina entrambi gli strumenti, cosi' si vede chi sbaglia",
                any("APPLE INC" in n and "NVIDIA" in n for n in ide["note"]),
                "; ".join(ide["note"])[:120])
    scrivi(isin_file, {"NVDA": "US67066G1041"})      # cifra storta: non si chiede nemmeno
    RICHIESTE.clear()
    installa_finto_openfigi()
    I.arricchisci([asset("NVDA", "NVIDIA")], isin_path=isin_file,
                  figi=I.OpenFigi(usa_cache=False, pausa_s=0))
    ok &= check("un ISIN gia' bocciato in casa non viene mandato a OpenFIGI",
                not any(j.get("idType") == "ID_ISIN" for job in RICHIESTE for j in job))

    print("\n7. Ticker sconosciuto a OpenFIGI: nessun dato inventato")
    installa_finto_openfigi()
    cli = I.OpenFigi(usa_cache=False, pausa_s=0)
    esiti = cli.identita(["NVDA", "ZZZZ"])
    ok &= check("quello noto c'e'", esiti["NVDA"]["trovato"])
    ok &= check("quello sconosciuto non c'e', e il motivo riporta l'avviso vero",
                not esiti["ZZZZ"]["trovato"]
                and "No identifier found" in esiti["ZZZZ"]["motivo"],
                esiti["ZZZZ"]["motivo"][:90])
    ok &= check("tutti i campi del codice sconosciuto restano vuoti",
                all(esiti["ZZZZ"][c] is None for c in ("figi", "nome", "tipo", "borsa")))

    print("\n8. Ripiego senza borsa: si accetta solo se e' lo stesso strumento")
    installa_finto_openfigi()
    cli = I.OpenFigi(usa_cache=False, pausa_s=0)
    esiti = cli.identita(["EXS1.DE", "XYZ.MI"])
    ok &= check("l'ETF che su Xetra non c'e' viene trovato altrove",
                esiti["EXS1.DE"]["trovato"]
                and esiti["EXS1.DE"]["figi_classe"] == "BBG001SGNC72",
                str(esiti["EXS1.DE"].get("figi")))
    ok &= check("e la nota dice che il FIGI e' di un'altra quotazione",
                "un'altra quotazione" in (esiti["EXS1.DE"]["nota"] or ""),
                esiti["EXS1.DE"]["nota"][:90])
    ok &= check("con due omonimi il programma rinuncia invece di scegliere",
                not esiti["XYZ.MI"]["trovato"]
                and "ambigua" in esiti["XYZ.MI"]["motivo"],
                esiti["XYZ.MI"]["motivo"][:90])

    print("\n9. Limite di frequenza (429): aspetta, riprova, poi cede senza eccezioni")
    installa_finto_openfigi("429")
    cli = I.OpenFigi(usa_cache=False, pausa_s=0)
    RICHIESTE.clear()
    esiti = cli.identita(["NVDA"])
    ok &= check("nessuna eccezione, esito negativo dichiarato",
                not esiti["NVDA"]["trovato"] and "429" in esiti["NVDA"]["motivo"],
                esiti["NVDA"]["motivo"][:90])
    ok &= check("il motivo cita il limite dichiarato dal servizio",
                "limite di frequenza" in esiti["NVDA"]["motivo"])
    ok &= check("ha riprovato prima di cedere", len(RICHIESTE) == I.MAX_TENTATIVI,
                f"{len(RICHIESTE)} tentativi")
    ok &= check("l'esito di rete e' marcato temporaneo (non va in cache)",
                esiti["NVDA"].get("temporaneo") is True)
    ok &= check("la pausa dichiarata rispetta le 25 richieste al minuto di OpenFIGI",
                I.PAUSA_S >= I.LIMITE_FINESTRA_S / I.LIMITE_RICHIESTE,
                f"{I.PAUSA_S}s fra due richieste, minimo "
                f"{I.LIMITE_FINESTRA_S / I.LIMITE_RICHIESTE}s")
    # Con il contatore del servizio a zero si aspetta la finestra invece di andare
    # a sbattere. Il `reset` arriva a zero quando la finestra sta girando proprio
    # ora: zero secondi di attesa, non un minuto, e questa riga esiste perche' la
    # prima versione dormiva 61 secondi in quel caso.
    installa_finto_openfigi("ok", restanti=0)
    cli = I.OpenFigi(usa_cache=False, pausa_s=0)
    cli.identita(["NVDA"])
    cli._reset_s = 0
    inizio = time.monotonic()
    cli.identita(["MC.PA"])
    durata = time.monotonic() - inizio
    ok &= check("contatore agli sgoccioli: aspetta la finestra, e solo quella",
                cli.stats["attese"] >= 1 and durata < 5,
                f"{cli.stats['attese']} attese, {durata:.1f}s")

    print("\n10. Rete assente e risposte rotte: il ciclo non si ferma")
    for modo, atteso in (("rete_giu", "URLError"), ("json_rotto", "JSONDecodeError"),
                         ("500", "HTTP 500")):
        installa_finto_openfigi(modo)
        a = [asset("NVDA", "NVIDIA", target=240.0)]
        r = I.arricchisci(a, isin_path=isin_file,
                          figi=I.OpenFigi(usa_cache=False, pausa_s=0))
        ide = a[0]["identita"]
        ok &= check(f"{modo}: nessuna eccezione, identita' comunque presente",
                    isinstance(ide, dict) and ide["figi"] is None)
        ok &= check(f"{modo}: il motivo e' scritto nelle note",
                    any("OpenFIGI non raggiunto" in n for n in ide["note"]),
                    "; ".join(ide["note"])[:80])
        ok &= check(f"{modo}: i dati che il motore aveva gia' restano",
                    ide["settore"] == "Tecnologia" and ide["target"] == 240.0)

    print("\n11. Cache permanente: il secondo ciclo non tocca la rete")
    cache.unlink(missing_ok=True)
    scrivi(isin_file, {"NVDA": "US67066G1040"})
    installa_finto_openfigi()
    primo = I.OpenFigi(usa_cache=True, pausa_s=0, cache_path=cache)
    I.arricchisci([asset("NVDA", "NVIDIA")], isin_path=isin_file, figi=primo)
    ok_salva, motivo = primo.chiudi()
    ok &= check("la cache viene scritta", ok_salva and cache.exists(), motivo)
    salvata = json.loads(cache.read_text(encoding="utf-8"))
    ok &= check("un file solo, con la data in cui e' stato scritto",
                salvata["strumenti"]["NVDA"]["scritto_il"] == date.today().isoformat()
                and bool(salvata["aggiornato"]),
                f"{salvata['strumenti']['NVDA']['scritto_il']} / {salvata['aggiornato']}")
    ok &= check("ci sta anche il verdetto sull'ISIN, che non va chiesto due volte",
                salvata["isin_verificati"]["NVDA|US67066G1040"]["esito"] == "concorda")
    RICHIESTE.clear()
    secondo = I.OpenFigi(usa_cache=True, pausa_s=0, cache_path=cache)
    a = [asset("NVDA", "NVIDIA")]
    I.arricchisci(a, isin_path=isin_file, figi=secondo)
    ok &= check("secondo giro: nessuna richiesta di rete",
                RICHIESTE == [] and secondo.stats["http"] == 0,
                f"{len(RICHIESTE)} richieste, {secondo.stats['cache']} letture da cache")
    ok &= check("e i dati sono gli stessi",
                a[0]["identita"]["figi"] == "BBG000BBJQV0"
                and a[0]["identita"]["isin"] == "US67066G1040")

    print("\n12. Cache: un buco si riprova, un dato trovato no")
    vecchio = (date.today() - timedelta(days=I.GIORNI_RIPROVA + 1)).isoformat()
    scrivi(cache, {"versione": I.VERSIONE, "aggiornato": vecchio,
                   "strumenti": {"NVDA": {"trovato": True, "figi": "BBG000BBJQV0",
                                          "nome": "NVIDIA CORP", "scritto_il": vecchio},
                                 "ZZZZ": {"trovato": False, "motivo": "ieri non c'era",
                                          "scritto_il": vecchio}},
                   "isin_verificati": {}})
    installa_finto_openfigi()
    RICHIESTE.clear()
    cli = I.OpenFigi(usa_cache=True, pausa_s=0, cache_path=cache)
    esiti = cli.identita(["NVDA", "ZZZZ"])
    chiesti = [j.get("idValue") for job in RICHIESTE for j in job]
    ok &= check("il dato vecchio ma trovato non viene richiesto",
                "NVDA" not in chiesti and esiti["NVDA"]["figi"] == "BBG000BBJQV0")
    ok &= check("il buco di una settimana viene riprovato", "ZZZZ" in chiesti,
                str(chiesti))
    ok &= check("una cache che non ha la forma attesa viene dichiarata",
                bool(I.carica_cache(scrivi(tmp / "rotta.json", "non un oggetto"))[1]))
    (tmp / "rotta2.json").write_text("{non json", encoding="utf-8")
    vuota, avvisi = I.carica_cache(tmp / "rotta2.json")
    ok &= check("e ricomincia da zero invece di cadere",
                vuota["strumenti"] == {} and bool(avvisi), "; ".join(avvisi)[:80])

    print("\n13. Il modello di isin.json: dice all'utente esattamente che cosa manca")
    modello = tmp / "modello.json"
    path, messaggio, riepilogo = I.scrivi_modello_isin(["NVDA", "MC.PA", "BTC-USD"],
                                                       path=modello)
    dati = json.loads(modello.read_text(encoding="utf-8"))
    ok &= check("il file viene creato con tutti i ticker e i valori vuoti",
                path == modello and dati["NVDA"] == "" and dati["MC.PA"] == ""
                and riepilogo["da_compilare"] == 3, messaggio)
    ok &= check("e con le note che spiegano dove si trova un ISIN",
                any("KID" in n or "emittente" in n for n in dati["_note"]))
    ok &= check("una delle note dice che il programma non inventa ISIN",
                any("NON inventa" in n for n in dati["_note"]))
    scrivi(modello, {"NVDA": "US67066G1040", "ALTRO": "FR0000121014"})
    path, messaggio, riepilogo = I.scrivi_modello_isin(["NVDA", "MC.PA"], path=modello)
    dati = json.loads(modello.read_text(encoding="utf-8"))
    ok &= check("rigenerandolo NON cancella il lavoro a mano",
                dati["NVDA"] == "US67066G1040" and dati["ALTRO"] == "FR0000121014",
                messaggio)
    ok &= check("e aggiunge solo i ticker che mancavano",
                dati["MC.PA"] == "" and riepilogo["aggiunti"] == ["MC.PA"]
                and riepilogo["conservati"] == ["ALTRO"])
    ok &= check("i ticker dell'universo del progetto sono leggibili",
                len(I.ticker_universo()) >= 40, f"{len(I.ticker_universo())} ticker")

    print("\n14. Le richieste: raggruppate a dieci, e la convenzione delle borse")
    installa_finto_openfigi()
    cli = I.OpenFigi(usa_cache=False, pausa_s=0)
    RICHIESTE.clear()
    cli.identita([f"T{i}" for i in range(23)])
    ok &= check("23 strumenti, nessuna richiesta oltre il limite di dieci",
                RICHIESTE and all(len(j) <= 10 for j in RICHIESTE),
                f"{len(RICHIESTE)} richieste da {[len(j) for j in RICHIESTE]}")
    ok &= check("oltre dieci strumenti la richiesta non parte nemmeno",
                cli._chiama([{"idType": "TICKER", "idValue": "X"}] * 11)[0] is None)
    coppie = {"NVDA": ("NVDA", "US"), "ASML.AS": ("ASML", "NA"),
              "SAP.DE": ("SAP", "GY"), "ENEL.MI": ("ENEL", "IM"),
              "MC.PA": ("MC", "FP"), "7203.T": ("7203", "JT"),
              "005930.KS": ("005930", "KS")}
    for ticker, (valore, borsa) in coppie.items():
        j = I.job_per_ticker(ticker)[0]
        ok &= check(f"{ticker} -> {valore} su {borsa}",
                    j["idValue"] == valore and j.get("exchCode") == borsa, str(j))
    ok &= check("0823.HK: gli zeri di riempimento di Yahoo vengono provati senza",
                I.job_per_ticker("0823.HK")[0]["idValue"] == "823")
    ok &= check("BTC-USD: settore valute, nessuna borsa",
                I.job_per_ticker("BTC-USD")[0].get("marketSecDes") == "Curncy")
    ok &= check("GC=F: future generico di prima scadenza",
                I.job_per_ticker("GC=F")[0]["idValue"] == "GC1")
    ok &= check("suffisso sconosciuto: non si inventa un codice di borsa",
                "exchCode" not in I.job_per_ticker("ABC.XYZ")[0])

    print("\n15. Niente rete per scelta: si lavora comunque")
    a = [asset("NVDA", "NVIDIA", target=240.0)]
    scrivi(isin_file, {"NVDA": "US67066G1040"})
    r = I.arricchisci(a, isin_path=isin_file,
                      figi=I.OpenFigi(usa_cache=False, pausa_s=0, usa_rete=False))
    ide = a[0]["identita"]
    ok &= check("l'ISIN scritto a mano viene usato anche senza riscontro",
                ide["isin"] == "US67066G1040"
                and "non fatto" in ide["fonti"]["isin"], ide["fonti"]["isin"][:90])
    ok &= check("il FIGI manca e si dice", ide["figi"] is None
                and ide["fonti"]["figi"] == I.NON_DISPONIBILE)
    ok &= check("il riepilogo conta quello che c'e' e quello che manca",
                r["con_isin"] == 1 and r["senza_figi"] == 1 and r["strumenti"] == 1)

    print("\n16. Dati sporchi in ingresso: nessuna eccezione")
    ok &= check("asset non validi vengono ignorati",
                I.arricchisci([None, 42, {}, {"ticker": ""}],
                              figi=I.OpenFigi(usa_cache=False, pausa_s=0,
                                              usa_rete=False))["strumenti"] == 0)
    ok &= check("un dizionario di asset va bene come una lista",
                I.arricchisci({"NVDA": asset("NVDA", "NVIDIA")},
                              figi=I.OpenFigi(usa_cache=False, pausa_s=0,
                                              usa_rete=False))["strumenti"] == 1)
    ok &= check("isin.json con valori non testuali: segnalato, non esplosivo",
                bool(I.leggi_isin(scrivi(tmp / "brutto.json",
                                         {"NVDA": 670661040})) [1]))
    ok &= check("isin.json che non e' un oggetto: segnalato",
                bool(I.leggi_isin(scrivi(tmp / "lista.json", ["US67066G1040"]))[1]))
    ok &= check("valida_isin accetta qualunque spazzatura senza alzare eccezioni",
                all(I.valida_isin(x)["valido"] is False
                    for x in (None, 12, [], {}, "", "   ")))
    ok &= check("cifra_controllo_isin su spazzatura restituisce None",
                all(I.cifra_controllo_isin(x) is None
                    for x in (None, "", 12, "US67066G1", "US67066G10$",
                              "US67066G1040")))
    ok &= check("e sugli undici caratteri giusti restituisce la cifra",
                I.cifra_controllo_isin("US67066G104") == "0")

    shutil.rmtree(tmp, ignore_errors=True)
    print("\n" + ("Tutti i controlli superati." if ok else "ALCUNI CONTROLLI FALLITI."))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
