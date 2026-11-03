"""Controlla la freschezza dei dati di mercato: cache a scadenza e orario.

PERCHE' ESISTE. Il ciclo gira ogni due ore, ma la cache era intestata al solo
giorno: il primo giro scaricava, gli altri undici rileggevano gli stessi file.
Nel file pubblicato si leggeva "http": 0, "cache": 150 - un ciclo intero senza
una sola richiesta di rete - e la pagina restava ferma fino al giorno dopo. Il
difetto non si vedeva da nessuna parte: nessun test falliva, nessun errore nel
log, e i calcoli erano giusti. Erano giusti su numeri vecchi.

    python tools/selftest_dati.py

Gira senza rete: le risposte di Yahoo sono finte e l'orologio si sposta a mano.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import providers  # noqa: E402

VERDE, ROSSO, RESET = "\033[32m", "\033[31m", "\033[0m"
ok_totale = True
CHIAMATE: list[str] = []


def check(label: str, condizione: bool, dettaglio: str = "") -> None:
    global ok_totale
    segno = f"{VERDE}ok {RESET}" if condizione else f"{ROSSO}KO {RESET}"
    print(f"  [{segno}] {label}" + (f" - {dettaglio}" if dettaglio else ""))
    if not condizione:
        ok_totale = False


def chart_finto(close: float, market_time: int | None, quando: int | None = None) -> dict:
    """La forma di risposta di Yahoo, ridotta all'osso."""
    return {"chart": {"result": [{
        "meta": {"currency": "USD", "fullExchangeName": "NasdaqGS",
                 "symbol": "AAA", "regularMarketTime": market_time},
        "timestamp": [quando if quando is not None else 1762000000],
        "indicators": {"quote": [{"open": [10.0], "high": [11.0], "low": [9.0],
                                  "close": [close], "volume": [1000]}]},
    }]}}


def finge_rete(risposta: dict):
    """Sostituisce urlopen e registra ogni chiamata davvero partita."""
    class Ctx:
        def __init__(self, dati):
            self.dati = dati

        def __enter__(self):
            return self.dati

        def __exit__(self, *a):
            return False

    def fake(req, timeout=None, context=None):
        CHIAMATE.append(req.full_url)
        return Ctx(io.BytesIO(json.dumps(risposta).encode("utf-8")))

    urllib.request.urlopen = fake


def main() -> int:
    originale = urllib.request.urlopen
    cartella = Path(tempfile.mkdtemp(prefix="ams-cache-"))
    vera = providers.CACHE_DIR
    ttl_veri = dict(providers.TTL_S)
    providers.CACHE_DIR = cartella
    OGGI = date.today().isoformat()
    try:
        print("1. Un dato appena scaricato si riusa, non si richiede")
        finge_rete(chart_finto(100.0, 1762000000))
        y = providers.Yahoo()
        CHIAMATE.clear()
        y._fetch("chart", "https://esempio/1", "AAA")
        y._fetch("chart", "https://esempio/1", "AAA")
        check("la seconda volta non va in rete", len(CHIAMATE) == 1, f"{len(CHIAMATE)} chiamate")
        check("ed e' contata come cache", y.stats["cache"] == 1, str(y.stats["cache"]))

        print("\n2. Lo stesso dato, passato il tempo, si riscarica")
        # IL DIFETTO ORIGINALE. Qui il file c'e' ed e' del giorno giusto: la
        # versione precedente lo riusava e basta, per tutte le 24 ore.
        f = cartella / f"chart_AAA_{OGGI}.json"
        vecchio = datetime.now(timezone.utc) - timedelta(minutes=120)
        f.write_text(json.dumps({"_scaricato": vecchio.isoformat(timespec="seconds"),
                                 "dati": chart_finto(100.0, 1762000000)}), encoding="utf-8")
        y = providers.Yahoo()
        CHIAMATE.clear()
        y._fetch("chart", "https://esempio/1", "AAA")
        check("due ore dopo torna in rete (TTL 90 minuti)", len(CHIAMATE) == 1,
              f"{len(CHIAMATE)} chiamate")
        check("e lo dichiara come scaduto", y.stats["scaduti"] == 1, str(y.stats["scaduti"]))
        f.write_text(json.dumps({
            "_scaricato": (datetime.now(timezone.utc) - timedelta(minutes=30))
                          .isoformat(timespec="seconds"),
            "dati": chart_finto(100.0, 1762000000)}), encoding="utf-8")
        y = providers.Yahoo()
        CHIAMATE.clear()
        y._fetch("chart", "https://esempio/1", "AAA")
        check("mezz'ora dopo invece basta la cache", len(CHIAMATE) == 0,
              f"{len(CHIAMATE)} chiamate")

        print("\n3. Non tutti i dati scadono allo stesso modo")
        # Chiedere i bilanci ogni due ore e' spreco: sono trimestrali.
        g = cartella / f"statements_AAA_{OGGI}.json"
        g.write_text(json.dumps({
            "_scaricato": (datetime.now(timezone.utc) - timedelta(hours=10))
                          .isoformat(timespec="seconds"),
            "dati": {"x": 1}}), encoding="utf-8")
        y = providers.Yahoo()
        CHIAMATE.clear()
        out = y._fetch("statements", "https://esempio/2", "AAA")
        check("i bilanci valgono tutta la giornata, anche dopo dieci ore",
              len(CHIAMATE) == 0 and out == {"x": 1}, f"{len(CHIAMATE)} chiamate")
        check("i prezzi scadono prima delle notizie",
              providers.TTL_S["chart"] < providers.TTL_S["news"],
              f'{providers.TTL_S["chart"]}s vs {providers.TTL_S["news"]}s')

        print("\n4. Un'ora che non si capisce vale come dato scaduto")
        for etichetta, contenuto in (
                ("ora nel futuro (orologio spostato)",
                 {"_scaricato": (datetime.now(timezone.utc) + timedelta(hours=3))
                                .isoformat(timespec="seconds"), "dati": {"x": 1}}),
                ("ora scritta male", {"_scaricato": "ieri sera", "dati": {"x": 1}}),
                ("involucro senza dati", {"_scaricato": "2026-11-02T10:00:00+00:00"}),
        ):
            f.write_text(json.dumps(contenuto), encoding="utf-8")
            y = providers.Yahoo()
            CHIAMATE.clear()
            y._fetch("chart", "https://esempio/1", "AAA")
            check(f"{etichetta}: si riscarica", len(CHIAMATE) == 1, f"{len(CHIAMATE)}")
        f.write_text("{non sono json", encoding="utf-8")
        y = providers.Yahoo()
        CHIAMATE.clear()
        y._fetch("chart", "https://esempio/1", "AAA")
        check("file illeggibile: si riscarica invece di esplodere", len(CHIAMATE) == 1)

        print("\n5. I file della versione precedente non si buttano via")
        # Non portavano l'ora dentro: si guarda la data di modifica.
        f.write_text(json.dumps(chart_finto(100.0, 1762000000)), encoding="utf-8")
        os.utime(f, (time.time() - 60, time.time() - 60))
        y = providers.Yahoo()
        CHIAMATE.clear()
        y._fetch("chart", "https://esempio/1", "AAA")
        check("formato vecchio e recente: si riusa", len(CHIAMATE) == 0, f"{len(CHIAMATE)}")
        os.utime(f, (time.time() - 7200, time.time() - 7200))
        y = providers.Yahoo()
        CHIAMATE.clear()
        y._fetch("chart", "https://esempio/1", "AAA")
        check("formato vecchio e stantio: si riscarica", len(CHIAMATE) == 1, f"{len(CHIAMATE)}")

        print("\n6. Quello che si scrive porta dentro l'ora dello scarico")
        for p in cartella.glob("*.json"):
            p.unlink()
        finge_rete(chart_finto(123.0, 1762000000))
        y = providers.Yahoo()
        y._fetch("chart", "https://esempio/1", "BBB")
        scritto = json.loads((cartella / f"chart_BBB_{OGGI}.json").read_text(encoding="utf-8"))
        check("c'e' il campo _scaricato", "_scaricato" in scritto)
        check("ed e' leggibile come data",
              isinstance(datetime.fromisoformat(scritto["_scaricato"]), datetime))
        check("i dati stanno sotto 'dati', non mescolati", "chart" in scritto.get("dati", {}))

        print("\n7. L'ora dell'ultimo scambio arriva fino a chi la mostra")
        # Senza questo la pagina puo' solo dire la data: i prezzi si muovono
        # ogni due ore e il lettore non ha modo di sapere di quando sono.
        finge_rete(chart_finto(123.0, 1762099200))
        y = providers.Yahoo(use_cache=False)
        ch = y.chart("AAA", range_="5d", min_bars=1)
        check("chart() restituisce market_time", ch.get("market_time") is not None,
              str(ch.get("market_time")))
        check("ed e' un istante UTC", str(ch.get("market_time", "")).endswith("+00:00"),
              str(ch.get("market_time")))
        check("corrisponde all'ora dichiarata dalla borsa",
              ch["market_time"] == datetime.fromtimestamp(1762099200, timezone.utc)
                                           .isoformat(timespec="seconds"),
              str(ch.get("market_time")))
        for valore in (None, 0):
            finge_rete(chart_finto(123.0, valore))
            y = providers.Yahoo(use_cache=False)
            ch = y.chart("AAA", range_="5d", min_bars=1)
            check(f"se la borsa non la dichiara ({valore!r}) resta None",
                  ch.get("market_time") is None, str(ch.get("market_time")))

        print("\n8. La cartella della cache non cresce per sempre")
        # Nel cloud viene portata avanti da un ciclo all'altro: senza pulizia
        # si accumulerebbe un file per simbolo per giorno, per sempre.
        for p in cartella.glob("*.json"):
            p.unlink()
        ieri = (date.today() - timedelta(days=1)).isoformat()
        vecchissimo = (date.today() - timedelta(days=9)).isoformat()
        for nome in (f"chart_AAA_{OGGI}.json", f"chart_AAA_{ieri}.json",
                     f"chart_AAA_{vecchissimo}.json", "senza_data.json"):
            (cartella / nome).write_text("{}", encoding="utf-8")
        buttati = providers.pulisci_cache(giorni=2)
        restano = sorted(p.name for p in cartella.glob("*.json"))
        check("butta i file dei giorni passati", buttati == 1, f"{buttati} buttati")
        check("tiene quello di oggi", f"chart_AAA_{OGGI}.json" in restano)
        check("tiene anche ieri, per il cambio di data a mezzanotte",
              f"chart_AAA_{ieri}.json" in restano)
        check("non tocca i file che non portano una data", "senza_data.json" in restano,
              str(restano))

        print("\n8b. La scadenza dei prezzi deve stare sotto la cadenza dei cicli")
        # IL DIFETTO, visto in produzione e invisibile da ogni altra parte.
        # Scadenza 90 minuti, cicli ogni 120: un ciclo partito 80 minuti dopo
        # il precedente ha trovato i prezzi ancora validi, non ha scaricato
        # niente e - correttamente - non ha pubblicato. La pagina e' rimasta
        # ferma per un'altra fascia. Run verde, 24 secondi, nessun errore:
        # l'unico modo di accorgersene era guardare l'orologio sul telefono.
        import re as _re
        yml = Path(providers.__file__).resolve().parent.parent \
            / ".github" / "workflows" / "ciclo.yml"
        testo_yml = yml.read_text(encoding="utf-8")
        cron = _re.findall(r"(?m)^\s*-\s*cron:\s*'([^']+)'", testo_yml)
        check("il workflow dichiara la cadenza in un cron solo", len(cron) == 1, str(cron))
        if cron:
            ore = sorted(int(h) for h in cron[0].split()[1].split(","))
            # la distanza minima fra due fasce, in minuti: e' la cadenza vera
            salti = [(b - a) * 60 for a, b in zip(ore, ore[1:])] or [24 * 60]
            cadenza = min(salti)
            check("fra due cicli passano due ore", cadenza == 120, f"{cadenza} minuti")
            check("e i prezzi scadono PRIMA che arrivi il ciclo dopo",
                  ttl_veri["chart"] / 60 < cadenza,
                  f"scadenza {int(ttl_veri['chart']/60)} min, cadenza {cadenza} min")
            # NON "un po' sotto": al massimo META' della cadenza. Il primo
            # controllo che avevo scritto chiedeva mezz'ora di margine, e col
            # valore vecchio (90 su 120) passava - cioe' non avrebbe colto il
            # difetto che stava correggendo. Il caso reale era un ciclo
            # arrivato 40 minuti in anticipo: con la meta' della cadenza,
            # qualunque ciclo che arrivi fino a un'ora prima o dopo trova i
            # prezzi scaduti e li rinnova.
            minuti = ttl_veri["chart"] / 60
            check("e non supera la META' della cadenza",
                  minuti <= cadenza / 2,
                  f"scadenza {int(minuti)} min, meta' della cadenza "
                  f"{int(cadenza / 2)} min: oltre, un ciclo in anticipo "
                  f"trova la cache valida e non pubblica")

        print("\n9. Il tempo si puo' cambiare senza toccare il codice")
        check("la tabella e' esposta e modificabile",
              isinstance(providers.TTL_S, dict) and "chart" in providers.TTL_S)
        # Il numero non si fissa qui: il vincolo vero e' il rapporto con la
        # cadenza dei cicli, verificato nel gruppo 8b. Un controllo che
        # pretende "90 minuti" costringe a cambiare due file per cambiare
        # un'impostazione, e quando e' servito farlo e' diventato un test
        # rosso da aggiustare invece di una conferma.
        check("i prezzi hanno una scadenza, e ragionevole",
              10 * 60 <= ttl_veri["chart"] <= 180 * 60,
              f'{int(ttl_veri["chart"] / 60)} minuti')
        check("c'e' la variabile d'ambiente, documentata nel modulo",
              "DATI_TTL_MIN" in Path(providers.__file__).read_text(encoding="utf-8"))
    finally:
        urllib.request.urlopen = originale
        providers.CACHE_DIR = vera
        providers.TTL_S.clear()
        providers.TTL_S.update(ttl_veri)
        shutil.rmtree(cartella, ignore_errors=True)

    print("\n" + ("Tutti i controlli superati." if ok_totale
                  else "ALCUNI CONTROLLI FALLITI."))
    return 0 if ok_totale else 1


if __name__ == "__main__":
    raise SystemExit(main())
