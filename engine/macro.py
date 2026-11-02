"""Contesto di mercato: lo sfondo su cui si legge ogni singolo asset.

Un titolo che scende dell'8% vuol dire una cosa se scende da solo e un'altra se
scende mentre sale lo stress sul sistema finanziario e si invertono le curve dei
rendimenti. Questo modulo porta quello sfondo, e lo porta da fonti ufficiali:
banche centrali, tesoro, istituti di statistica. Nessuna chiave API, nessuna
registrazione, solo libreria standard.

Che cosa arriva e da chi:

* **cambi** verso euro -> BCE, tassi di riferimento (ripiego: Frankfurter);
* **curva dei rendimenti area euro** (AAA, 2 e 10 anni) -> BCE, dataset YC;
* **stress finanziario** -> BCE, NEW CISS;
* **tasso sui depositi BCE** -> BCE, dataset FM;
* **curva dei rendimenti USA** nominale e reale -> Tesoro degli Stati Uniti;
* **volatilita' attesa** (VIX) -> Yahoo, tramite `providers.Yahoo`;
* **inflazione USA** -> BLS, indice dei prezzi al consumo;
* **clima economico europeo** (ESI) -> Eurostat;
* **clima sulle cripto** (Fear & Greed) -> alternative.me, solo se servono.

Due regole che valgono per tutto il modulo.

**Ogni numero porta la sua data e la sua fonte.** Un valore senza data non si
puo' usare per decidere: non si sa se descrive oggi o l'anno scorso. Qui ogni
osservazione e' un dizionario con `value`, `date`, `source`, `unit`, `label`.

**Un numero vecchio e' peggio di un numero assente.** Diverse serie ufficiali
rispondono HTTP 200 con l'ultimo dato pubblicato anche quando quel dato e' fermo
da un anno: la serie storica del CISS (`SS_CI`) risponde ancora oggi, con un
valore del maggio 2025. Per questo ogni serie dichiara la sua cadenza e, se
l'ultima osservazione e' piu' vecchia del doppio della cadenza attesa, il dato
viene scartato e finisce tra i buchi dichiarati (`missing`), non tra i dati.

Niente qui solleva eccezioni verso il chiamante (OP-06): una fonte che non
risponde restituisce `None` e scrive il perche' in `Macro.gaps`. Il ciclo di
scansione non si ferma mai per una fonte giu'.

Cache su disco giornaliera in `.data_cache/`, un file per fonte per giorno,
come in `providers.py`: un secondo ciclo nello stesso giorno non tocca la rete.
"""

from __future__ import annotations

import calendar
import csv
import io
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

from .providers import DataError, Yahoo

CACHE_DIR = Path(__file__).resolve().parent.parent / ".data_cache"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
TIMEOUT_S = 25
PACE_S = 0.25               # distanza minima tra due chiamate, per educazione

ECB_BASE = "https://data-api.ecb.europa.eu/service/data"
TREASURY_BASE = ("https://home.treasury.gov/resource-center/data-chart-center/"
                 "interest-rates/daily-treasury-rates.csv")
BLS_BASE = "https://api.bls.gov/publicAPI/v1/timeseries/data"
EUROSTAT_BASE = ("https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
                 "ei_bssi_m_r2")
FRANKFURTER_BASE = "https://api.frankfurter.app/latest"
FNG_URL = "https://api.alternative.me/fng/?limit=1"

# Chiavi delle serie BCE, verificate una per una da questa macchina.
# Attenzione a due cose imparate provandole:
#  - la curva dei rendimenti sta sotto frequenza "B" (giorni lavorativi), non "D";
#  - del CISS esistono quattro serie e quella storica (SS_CI) e' MORTA dal maggio
#    2025 pur rispondendo 200. La serie viva e' SS_CIN, "NEW CISS".
ECB_KEYS = {
    "fx": "EXR/D.{cur}.EUR.SP00.A",
    "euro_10y": "YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y",
    "euro_2y": "YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_2Y",
    "stress": "CISS/D.U2.Z0Z.4F.EC.SS_CIN.IDX",
    "policy_rate": "FM/D.U2.EUR.4F.KR.DFR.LEV",
}

FX_DEFAULT = ("USD", "GBP", "CHF", "JPY")
# Scadenze: l'eta' massima, in giorni di calendario, che l'ultima osservazione
# puo' avere prima di essere dichiarata "ferma". La regola del progetto e' "il
# doppio della frequenza attesa", ma contata in giorni di CALENDARIO: una serie
# pubblicata solo nei giorni lavorativi, letta il lunedi' mattina, ha per forza
# l'ultimo dato di venerdi'. Senza questo margine il fine settimana farebbe
# scartare dati freschissimi, che e' l'errore opposto e altrettanto grave.
MAX_AGE_D = {
    "fx": 5,            # BCE, giorni lavorativi, pubblicati verso le 16 CET
    "euro_curve": 7,    # BCE, giorni lavorativi con un giorno di ritardo (T+1)
    "stress": 7,        # BCE, come sopra: il NEW CISS esce in ritardo di 1-2 giorni
    "policy_rate": 4,   # BCE, pubblicato ogni giorno di calendario, sabato compreso
    "us_curve": 5,      # Tesoro USA, giorni lavorativi, pubblicato la sera a New York
    "vix": 5,           # giorni di borsa
    "us_cpi": 62,       # mensile: esce circa due settimane dopo la fine del mese
    "eu_sentiment": 62,  # mensile: esce negli ultimi giorni del mese di riferimento
    "crypto": 3,        # giornaliero, si aggiorna a mezzanotte UTC
}

# Soglie di lettura in parole. Sono una scelta di demo, non una verita' di
# mercato: servono a non mettere in mano al cliente un numero nudo come 0,0128.
CISS_BANDS = ((0.10, "basso"), (0.25, "medio"), (1.01, "alto"))
VIX_BANDS = ((15.0, "calma"), (25.0, "normale"), (35.0, "tensione"), (999.0, "panico"))

# alternative.me classifica in inglese: per il cliente italiano va tradotto,
# altrimenti nella scheda compare "Fear" in mezzo a una frase in italiano.
FNG_IT = {
    "extreme fear": "paura estrema", "fear": "paura", "neutral": "neutrale",
    "greed": "avidità", "extreme greed": "avidità estrema",
}


def _band(value: float, bands) -> str:
    for limit, name in bands:
        if value < limit:
            return name
    return bands[-1][1]


def _num(value: float, decimals: int = 2) -> str:
    """Numero scritto come lo scrive un italiano, con la virgola. Fatto a mano e
    non con `locale`, che dipende da come e' configurata la macchina: la stessa
    frase deve leggersi uguale sul portatile e sul server."""
    return f"{value:.{decimals}f}".replace(".", ",")


# --------------------------------------------------------------- date e scadenze
def _parse_period(period: str) -> date | None:
    """Da un periodo di riferimento alla data in cui quel periodo FINISCE.

    Le fonti usano forme diverse: "2026-10-30" (giorno), "2026-10" e "2026 M09"
    (mese). Per un mese si prende l'ultimo giorno, perche' l'eta' di un dato
    mensile va contata da quando il mese e' chiuso, non dal primo giorno.
    """
    p = (period or "").strip().replace("M", "-").replace(" ", "")
    bits = [b for b in p.split("-") if b]
    try:
        if len(bits) >= 3:
            return date(int(bits[0]), int(bits[1]), int(bits[2]))
        if len(bits) == 2:
            y, m = int(bits[0]), int(bits[1])
            return date(y, m, calendar.monthrange(y, m)[1])
    except (ValueError, IndexError):
        return None
    return None


def _age_days(period: str, today: date | None = None) -> int | None:
    d = _parse_period(period)
    if d is None:
        return None
    return ((today or date.today()) - d).days


def _point(value, period: str, source: str, unit: str, label: str,
           kind: str, today: date | None = None, **extra) -> tuple[dict | None, str | None]:
    """Costruisce l'osservazione e applica la scadenza.

    Restituisce (osservazione, motivo). Il motivo e' valorizzato solo quando
    l'osservazione va buttata, e dice perche': cosi' chi chiama puo' dichiarare
    il buco invece di far finta che non ci sia.
    """
    if value is None:
        return None, f"{label}: valore assente nella risposta"
    when = _parse_period(period)
    if when is None:
        return None, f"{label}: data di riferimento illeggibile ({period!r})"
    age = _age_days(period, today)
    limit = MAX_AGE_D.get(kind, 7)
    if age is not None and age > limit:
        # Qui si chiude la trappola dei 200 con dati vecchi: la fonte ha
        # risposto, il numero c'e', ma descrive un mondo che non esiste piu'.
        return None, (f"{label}: serie ferma, ultimo dato {when.isoformat()} "
                      f"({age} giorni, limite {limit})")
    # `date` e' la data da cui si conta l'eta' del dato; `period` e' il periodo
    # di riferimento come lo scrive la fonte. Per una serie mensile i due
    # differiscono e serve tenerli separati: l'indice dei prezzi di settembre va
    # mostrato come "settembre 2026", non come "30 settembre 2026", che darebbe
    # l'idea di una misura fatta quel giorno.
    out = {"value": value, "date": when.isoformat(), "period": period.strip(),
           "source": source, "unit": unit, "label": label,
           "age_days": age, "stale": False}
    out.update(extra)
    return out, None


def _derived(value, base: dict, source: str, unit: str, label: str, **extra) -> dict:
    """Un valore calcolato su altre osservazioni, nella stessa forma di tutte le
    altre: chi legge non deve sapere se un numero e' stato scaricato o dedotto
    per poterlo mostrare. Data ed eta' sono quelle dell'osservazione da cui
    viene, perche' un calcolo non e' piu' fresco dei dati che lo compongono."""
    out = {"value": value, "date": base["date"], "period": base["period"],
           "source": source, "unit": unit, "label": label,
           "age_days": base["age_days"], "stale": False}
    out.update(extra)
    return out


# ------------------------------------------------------------------------ cliente
class Macro:
    """Client delle fonti macro: una funzione per fonte, cache giornaliera,
    nessuna eccezione verso l'esterno.

    I buchi si leggono in `gaps`: ogni voce dice che cosa manca e perche'.
    Dichiarare i buchi conta piu' che riempirli, perche' un contesto incompleto
    ma onesto si puo' ancora usare, uno falso no.
    """

    def __init__(self, use_cache: bool = True, pace_s: float = PACE_S,
                 today: date | None = None, retry_wait_s: float = 1.5):
        self.use_cache = use_cache
        self.pace_s = pace_s
        self.today = today or date.today()
        self.retry_wait_s = retry_wait_s
        self._last = 0.0
        self.stats = {"http": 0, "cache": 0, "errors": 0, "retries": 0, "bytes": 0}
        self.gaps: list[dict] = []
        self.log: list[dict] = []
        if use_cache:
            CACHE_DIR.mkdir(exist_ok=True)

    def _gap(self, what: str, why: str) -> None:
        self.gaps.append({"what": what, "why": why})

    # -------------------------------------------------------------------- rete
    def _cache_file(self, kind: str) -> Path:
        safe = urllib.parse.quote(kind, safe="")
        return CACHE_DIR / f"macro_{safe}_{self.today.isoformat()}.json"

    def _fetch(self, kind: str, url: str,
               accept: str = "application/json") -> tuple[str | None, str | None]:
        """Scarica un testo. Restituisce (testo, motivo): il motivo e' None solo
        quando il testo c'e' davvero. Non solleva niente, mai.

        Un corpo vuoto con HTTP 200 conta come errore, non come dato: il Tesoro
        USA risponde cosi' quando gli si chiede un anno che non esiste o un tipo
        di curva sbagliato, e un chiamante distratto leggerebbe "zero righe" come
        "nessun movimento" invece di "richiesta sbagliata". Per lo stesso motivo
        un corpo vuoto non viene messo in cache: avvelenerebbe tutta la giornata.

        Un solo tentativo di recupero sui guasti passeggeri, come in
        `providers.py`: le API delle banche centrali vanno in timeout un colpo
        ogni tanto, e perdere il tratto a 2 anni della curva per mezzo secondo di
        rete lenta sarebbe uno spreco. Un 404, invece, non si riprova: la chiave
        sbagliata resta sbagliata anche al secondo tentativo.
        """
        cf = self._cache_file(kind)
        if self.use_cache and cf.exists():
            try:
                cached = json.loads(cf.read_text(encoding="utf-8"))
                body = cached.get("body")
                if body:
                    self.stats["cache"] += 1
                    return body, None
            except Exception:
                pass                      # cache illeggibile: si riscarica
        why = "fonte non interrogata"
        for attempt in (1, 2):
            wait = self.pace_s - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA,
                                                           "Accept": accept})
                with urllib.request.urlopen(req, timeout=TIMEOUT_S,
                                            context=ssl.create_default_context()) as r:
                    raw = r.read()
                self._last = time.monotonic()
                self.stats["http"] += 1
                self.stats["bytes"] += len(raw)
                text = raw.decode("utf-8-sig", "replace")
                if not text.strip():
                    self.stats["errors"] += 1
                    self.log.append({"kind": kind, "status": "vuoto"})
                    return None, "la fonte ha risposto 200 ma con un corpo vuoto"
                if self.use_cache:
                    try:
                        cf.write_text(json.dumps({"url": url,
                                                  "fetched": self.today.isoformat(),
                                                  "body": text}), encoding="utf-8")
                    except OSError:
                        pass              # disco pieno o sola lettura: pazienza
                self.log.append({"kind": kind, "status": "ok"})
                return text, None
            except urllib.error.HTTPError as e:
                self._last = time.monotonic()
                why = f"la fonte ha risposto HTTP {e.code}"
                retriable = e.code in (429, 500, 502, 503, 504)
            except Exception as e:
                self._last = time.monotonic()
                why = f"fonte non raggiungibile ({type(e).__name__})"
                retriable = True
            self.log.append({"kind": kind, "status": why})
            if retriable and attempt == 1:
                self.stats["retries"] += 1
                if self.retry_wait_s:
                    time.sleep(self.retry_wait_s)
                continue
            self.stats["errors"] += 1
            return None, why
        self.stats["errors"] += 1
        return None, why

    # ------------------------------------------------------- lettori di formato
    def _ecb_series(self, kind: str, key: str,
                    n: int = 8) -> tuple[list[dict], str | None]:
        """Ultime osservazioni di una serie BCE, dalla piu' vecchia alla piu' recente.

        Si chiede `format=csvdata` perche' il CSV della BCE e' una tabella piatta
        con TIME_PERIOD e OBS_VALUE in chiaro, mentre il JSON SDMX mette i valori
        in un dizionario indicizzato per posizione e le date da un'altra parte:
        piu' codice e piu' modi di sbagliare. Attenzione: `format=csvdata` viene
        ignorato se l'intestazione Accept chiede JSON, quindi qui Accept dice CSV.
        """
        url = f"{ECB_BASE}/{key}?lastNObservations={n}&format=csvdata"
        text, why = self._fetch(kind, url, accept="text/csv")
        if text is None:
            return [], why
        try:
            rows = list(csv.DictReader(io.StringIO(text)))
        except Exception:
            return [], "risposta BCE illeggibile come CSV"
        out = []
        for r in rows:
            period, raw = r.get("TIME_PERIOD"), r.get("OBS_VALUE")
            if not period or raw in (None, ""):
                continue
            try:
                out.append({"period": period, "value": float(raw),
                            "title": (r.get("TITLE") or "").strip(),
                            "unit": (r.get("UNIT") or "").strip()})
            except ValueError:
                continue                  # riga senza numero: si salta
        if not out:
            return [], "la BCE ha risposto senza osservazioni valide"
        # Non si da' per scontato l'ordine: si ordina per periodo e si guarda in fondo.
        return sorted(out, key=lambda o: o["period"]), None

    # ------------------------------------------------------------------- cambi
    def fx_eur(self, currencies=FX_DEFAULT) -> dict:
        """Cambi verso euro dai tassi di riferimento BCE, con ripiego Frankfurter.

        La BCE e' la fonte primaria perche' i suoi tassi sono quelli che poi
        valgono per i rendiconti: sono pubblicati una volta al giorno e sono
        citabili. Frankfurter serve solo quando la BCE non risponde, e lo dice.
        """
        out: dict[str, dict] = {}
        for cur in currencies:
            cur = cur.upper()
            if cur == "EUR":
                continue
            obs, why = self._ecb_series(f"fx_{cur}", ECB_KEYS["fx"].format(cur=cur))
            point = None
            if obs:
                last = obs[-1]
                # Il tasso BCE e' espresso in valuta per un euro (USD/EUR = 1,11):
                # qui serve anche il verso opposto, quanti euro vale una unita'.
                point, why = _point(last["value"], last["period"],
                                    "BCE, tassi di riferimento",
                                    f"{cur} per 1 EUR", f"Cambio {cur}/EUR", "fx",
                                    self.today,
                                    eur_per_unit=round(1.0 / last["value"], 6)
                                    if last["value"] else None)
            if point is None:
                fallback, why2 = self._frankfurter(cur)
                if fallback is not None:
                    fallback["fallback_from"] = f"BCE non utilizzabile: {why}"
                    point = fallback
                else:
                    self._gap(f"Cambio {cur}/EUR", f"{why}; ripiego: {why2}")
                    continue
            out[cur] = point
        return out

    def _frankfurter(self, cur: str) -> tuple[dict | None, str | None]:
        """Ripiego sui cambi. Restituisce lo stesso verso della BCE (valuta per
        un euro) anche se l'API lo da' al contrario, altrimenti chi legge
        confronterebbe due numeri che sembrano uguali e non lo sono."""
        text, why = self._fetch(f"fx_fallback_{cur}",
                                f"{FRANKFURTER_BASE}?from={urllib.parse.quote(cur)}&to=EUR")
        if text is None:
            return None, why
        try:
            data = json.loads(text)
            eur_per_unit = float((data.get("rates") or {})["EUR"])
            when = data["date"]
        except Exception:
            return None, "risposta Frankfurter illeggibile"
        if not eur_per_unit:
            return None, "Frankfurter ha risposto con un cambio nullo"
        return _point(round(1.0 / eur_per_unit, 6), when, "Frankfurter (ripiego)",
                      f"{cur} per 1 EUR", f"Cambio {cur}/EUR", "fx", self.today,
                      eur_per_unit=eur_per_unit)

    # ------------------------------------------- curva dei rendimenti area euro
    def euro_yield_curve(self) -> dict:
        """Rendimenti dei titoli di Stato AAA dell'area euro a 2 e 10 anni.

        Si usa la curva AAA e non la media dell'area euro perche' la AAA e' il
        tasso privo di rischio in euro: e' il metro con cui si giudica se il
        rendimento di qualunque altra cosa vale il rischio che porta.
        """
        out: dict[str, dict] = {}
        for name, years, key in (("euro_10y", 10, ECB_KEYS["euro_10y"]),
                                 ("euro_2y", 2, ECB_KEYS["euro_2y"])):
            obs, why = self._ecb_series(name, key)
            if not obs:
                self._gap(f"Rendimento area euro {years} anni", why or "nessun dato")
                continue
            last = obs[-1]
            point, why = _point(round(last["value"], 4), last["period"],
                                "BCE, curva dei rendimenti AAA area euro", "%",
                                f"Rendimento area euro {years} anni", "euro_curve",
                                self.today, maturity_years=years)
            if point is None:
                self._gap(f"Rendimento area euro {years} anni", why or "scartato")
                continue
            out[name] = point
        # L'inclinazione si calcola solo se i due tratti sono dello stesso giorno:
        # sottrarre rendimenti di due date diverse produce un numero che non
        # descrive nessuna curva realmente esistita.
        a, b = out.get("euro_10y"), out.get("euro_2y")
        if a and b and a["date"] == b["date"]:
            slope = round(a["value"] - b["value"], 4)
            out["euro_curve_slope"] = _derived(
                slope, a, "calcolato su BCE (10 anni meno 2 anni)", "punti %",
                "Inclinazione della curva euro", inverted=slope < 0)
        elif a and b:
            self._gap("Inclinazione della curva euro",
                      f"i due tratti hanno date diverse ({a['date']} e {b['date']})")
        return out

    # ------------------------------------------------ stress finanziario (CISS)
    def euro_stress(self) -> dict | None:
        """Indicatore BCE di stress sistemico, scala da 0 a 1.

        Qui si usa la serie SS_CIN ("NEW CISS"). La serie storica SS_CI e'
        ferma al 2 maggio 2025 e risponde ancora HTTP 200 con quel valore: e' il
        caso che ha fatto nascere il controllo di scadenza di questo modulo.
        """
        obs, why = self._ecb_series("stress", ECB_KEYS["stress"])
        if not obs:
            self._gap("Stress finanziario area euro", why or "nessun dato")
            return None
        last = obs[-1]
        value = round(last["value"], 4)
        point, why = _point(value, last["period"], "BCE, NEW CISS", "indice 0-1",
                            "Stress sul sistema finanziario", "stress", self.today,
                            band=_band(value, CISS_BANDS),
                            in_parole=f"Lo stress sui mercati finanziari è "
                                      f"{_band(value, CISS_BANDS)}.")
        if point is None:
            self._gap("Stress finanziario area euro", why or "scartato")
            return None
        # La direzione su una settimana dice piu' del livello: uno stress basso
        # che sale veloce merita attenzione, uno alto che scende e' in rientro.
        if len(obs) >= 5:
            week_ago = obs[-5]["value"]
            point["change_5d"] = round(value - week_ago, 4)
            point["rising"] = value > week_ago
        return point

    # --------------------------------------------------------- tasso di politica
    def ecb_policy_rate(self) -> dict | None:
        """Tasso sui depositi presso la BCE: il rendimento senza rischio e senza
        durata in euro, cioe' il minimo che un investimento in euro deve battere
        per avere senso. La serie e' pubblicata ogni giorno di calendario, anche
        il sabato, quindi la sua scadenza e' piu' stretta delle altre."""
        obs, why = self._ecb_series("policy_rate", ECB_KEYS["policy_rate"], n=4)
        if not obs:
            self._gap("Tasso sui depositi BCE", why or "nessun dato")
            return None
        last = obs[-1]
        point, why = _point(round(last["value"], 4), last["period"],
                            "BCE, tasso sui depositi", "%", "Tasso BCE sui depositi",
                            "policy_rate", self.today)
        if point is None:
            self._gap("Tasso sui depositi BCE", why or "scartato")
            return None
        return point

    # ------------------------------------------------ curva dei rendimenti USA
    def us_yield_curve(self) -> dict:
        """Curva del Tesoro americano, nominale e reale.

        Due avvertenze imparate provandolo. Primo: un anno che non esiste o un
        `type` sbagliato NON danno errore, danno HTTP 200 con corpo vuoto, e per
        questo `_fetch` tratta il corpo vuoto come un guasto. Secondo: il CSV
        arriva dal piu' recente al piu' vecchio e con il BOM, quindi si legge in
        utf-8-sig e si prende la PRIMA riga, non l'ultima.
        """
        out: dict[str, dict] = {}
        year = self.today.year
        nominal, why_n = self._treasury_rows("us_curve_nominal",
                                             "daily_treasury_yield_curve", year)
        # A gennaio il file dell'anno nuovo puo' essere ancora vuoto: si torna
        # all'anno precedente invece di dichiarare la curva mancante.
        if not nominal:
            nominal, why_n = self._treasury_rows("us_curve_nominal_prev",
                                                 "daily_treasury_yield_curve", year - 1)
        real, why_r = self._treasury_rows("us_curve_real",
                                          "daily_treasury_real_yield_curve", year)
        if not real:
            real, why_r = self._treasury_rows("us_curve_real_prev",
                                              "daily_treasury_real_yield_curve", year - 1)

        if not nominal:
            self._gap("Curva dei rendimenti USA", why_n or "nessun dato")
        else:
            row = nominal[0]
            for name, column, years, label in (
                    ("us_3m", "3 MO", 0.25, "Rendimento USA 3 mesi"),
                    ("us_2y", "2 YR", 2, "Rendimento USA 2 anni"),
                    ("us_10y", "10 YR", 10, "Rendimento USA 10 anni"),
                    ("us_30y", "30 YR", 30, "Rendimento USA 30 anni")):
                point, why = _point(_as_float(row.get(column)), row["_date"],
                                    "Tesoro degli Stati Uniti", "%", label,
                                    "us_curve", self.today, maturity_years=years)
                if point is None:
                    self._gap(label, why or "scartato")
                    continue
                out[name] = point

        if not real:
            self._gap("Rendimento reale USA 10 anni", why_r or "nessun dato")
        else:
            row = real[0]
            point, why = _point(_as_float(row.get("10 YR")), row["_date"],
                                "Tesoro degli Stati Uniti (TIPS)", "%",
                                "Rendimento reale USA 10 anni", "us_curve", self.today)
            if point is None:
                self._gap("Rendimento reale USA 10 anni", why or "scartato")
            else:
                out["us_10y_real"] = point

        a, b = out.get("us_10y"), out.get("us_2y")
        if a and b and a["date"] == b["date"]:
            slope = round(a["value"] - b["value"], 4)
            out["us_curve_slope"] = _derived(
                slope, a, "calcolato su Tesoro USA (10 anni meno 2 anni)", "punti %",
                "Inclinazione della curva USA", inverted=slope < 0)
        # Inflazione attesa dal mercato: nominale meno reale sulla stessa
        # scadenza e sulla stessa data. E' l'unico dato sulle attese di
        # inflazione che si ottiene senza pagare nessuno.
        n10, r10 = out.get("us_10y"), out.get("us_10y_real")
        if n10 and r10 and n10["date"] == r10["date"]:
            out["us_breakeven_10y"] = _derived(
                round(n10["value"] - r10["value"], 4), n10,
                "calcolato su Tesoro USA (nominale meno reale, 10 anni)", "%",
                "Inflazione attesa dal mercato USA a 10 anni")
        elif n10 and r10:
            self._gap("Inflazione attesa dal mercato USA a 10 anni",
                      f"nominale del {n10['date']} e reale del {r10['date']}: "
                      f"date diverse, la differenza non significherebbe niente")
        return out

    def _treasury_rows(self, kind: str, curve_type: str,
                       year: int) -> tuple[list[dict], str | None]:
        url = (f"{TREASURY_BASE}/{year}/all?type={urllib.parse.quote(curve_type)}"
               f"&field_tdr_date_value={year}&page&_format=csv")
        text, why = self._fetch(kind, url, accept="text/csv")
        if text is None:
            return [], why
        try:
            rows = list(csv.DictReader(io.StringIO(text)))
        except Exception:
            return [], "risposta del Tesoro illeggibile come CSV"
        out = []
        for r in rows:
            # I nomi di colonna si portano in maiuscolo perche' i due file del
            # Tesoro non li scrivono allo stesso modo: la curva nominale dice
            # "10 Yr", quella reale "10 YR". Normalizzando si legge una volta
            # sola invece di tenere due elenchi di nomi quasi uguali.
            row = {(k or "").strip().upper(): v for k, v in r.items()}
            iso = _us_date(row.get("DATE"))
            if iso:
                row["_date"] = iso
                out.append(row)
        if not out:
            return [], "il Tesoro ha risposto senza righe utilizzabili"
        # Il file arriva dal piu' recente, ma non ci si fida: si ordina e si
        # mette davanti la data piu' alta.
        return sorted(out, key=lambda r: r["_date"], reverse=True), None

    # ------------------------------------------------------------------- VIX
    def vix(self) -> dict | None:
        """Volatilita' attesa sull'S&P 500 a 30 giorni, l'indice della paura.

        Si riusa `providers.Yahoo` invece di riscrivere la chiamata: stesso
        host, stessa cache, stesso trattamento degli errori gia' collaudato.
        """
        try:
            y = Yahoo(use_cache=self.use_cache, pace_s=0.0)
            chart = y.chart("^VIX", range_="1mo", min_bars=1)
        except DataError as e:
            self._gap("Volatilità attesa (VIX)", f"Yahoo non utilizzabile: {e}")
            return None
        except Exception as e:
            self._gap("Volatilità attesa (VIX)", f"Yahoo non raggiungibile ({type(e).__name__})")
            return None
        self.stats["http"] += y.stats["http"]
        self.stats["cache"] += y.stats["cache"]
        value = round(chart["close"][-1], 2)
        point, why = _point(value, chart["date"][-1], "Yahoo Finance (^VIX)", "punti",
                            "Volatilità attesa (VIX)", "vix", self.today,
                            band=_band(value, VIX_BANDS),
                            in_parole=f"La volatilità attesa sulle borse americane è "
                                      f"in zona {_band(value, VIX_BANDS)}.")
        if point is None:
            self._gap("Volatilità attesa (VIX)", why or "scartato")
            return None
        return point

    # -------------------------------------------------------- inflazione USA
    def us_inflation(self, series_id: str = "CUUR0000SA0") -> dict | None:
        """Indice dei prezzi al consumo americano e sua variazione annuale.

        L'API v1 del BLS funziona senza chiave e restituisce circa tre anni di
        storia: abbastanza per calcolare la variazione sullo stesso mese
        dell'anno prima, che e' il numero di cui si parla quando si dice
        "inflazione". Il confronto si fa mese su mese omologo e non sugli ultimi
        dodici valori, perche' l'indice grezzo ha una stagionalita' forte.
        """
        text, why = self._fetch(f"us_cpi_{series_id}", f"{BLS_BASE}/{series_id}")
        if text is None:
            self._gap("Inflazione USA", why or "nessun dato")
            return None
        try:
            data = json.loads(text)
        except Exception:
            self._gap("Inflazione USA", "risposta BLS illeggibile come JSON")
            return None
        if data.get("status") != "REQUEST_SUCCEEDED":
            msg = "; ".join(data.get("message") or []) or str(data.get("status"))
            self._gap("Inflazione USA", f"il BLS ha rifiutato la richiesta: {msg}")
            return None
        rows = []
        for series in (data.get("Results") or {}).get("series") or []:
            for r in series.get("data") or []:
                period = r.get("period") or ""
                # M13 e' la media annuale, non un mese: non va mischiata ai mesi.
                if not period.startswith("M") or period == "M13":
                    continue
                try:
                    rows.append({"year": int(r["year"]), "month": int(period[1:]),
                                 "value": float(r["value"])})
                except (KeyError, ValueError):
                    continue
        if not rows:
            self._gap("Inflazione USA", "il BLS ha risposto senza osservazioni mensili")
            return None
        rows.sort(key=lambda r: (r["year"], r["month"]))
        last = rows[-1]
        period = f"{last['year']}-{last['month']:02d}"
        point, why = _point(last["value"], period, "BLS (Bureau of Labor Statistics)",
                            "indice", "Indice dei prezzi al consumo USA", "us_cpi",
                            self.today, series_id=series_id)
        if point is None:
            self._gap("Inflazione USA", why or "scartato")
            return None
        prev = next((r for r in rows
                     if r["year"] == last["year"] - 1 and r["month"] == last["month"]), None)
        if prev and prev["value"]:
            yoy = round(100.0 * (last["value"] / prev["value"] - 1), 2)
            point["yoy_pct"] = yoy
            point["yoy_basis"] = f"{prev['year']}-{prev['month']:02d}"
            point["in_parole"] = (f"Negli Stati Uniti i prezzi sono saliti del "
                                  f"{_num(yoy, 1)}% in un anno.")
        else:
            # Senza il mese omologo si pubblica l'indice e si dichiara che la
            # variazione annuale non e' calcolabile: mezzo dato dichiarato e'
            # utile, un dato intero inventato no.
            self._gap("Variazione annuale dei prezzi USA",
                      "il BLS non copre lo stesso mese dell'anno precedente")
        return point

    # ------------------------------------------------- clima economico europeo
    def euro_sentiment(self, geos=("EU27_2020", "IT", "DE", "FR")) -> dict:
        """Indice Eurostat del clima economico (ESI): 100 e' la media storica.

        Attenzione: `geo=EA` e `geo=EA20` rispondono HTTP 200 ma con il
        dizionario dei valori VUOTO, quindi l'aggregato dell'area euro da qui
        non si ottiene. Si usa EU27_2020, che risulta popolato, piu' i tre
        maggiori paesi dell'area. Si chiede un `geo` per volta di proposito:
        con una sola geografia l'indice dei valori coincide con l'indice del
        tempo, e la lettura della risposta resta banale.
        """
        out: dict[str, dict] = {}
        for geo in geos:
            url = (f"{EUROSTAT_BASE}?format=JSON&indic=BS-ESI-I&s_adj=SA"
                   f"&geo={urllib.parse.quote(geo)}&lastTimePeriod=4")
            text, why = self._fetch(f"eu_sentiment_{geo}", url)
            if text is None:
                self._gap(f"Clima economico {geo}", why or "nessun dato")
                continue
            try:
                data = json.loads(text)
                index = data["dimension"]["time"]["category"]["index"]
                values = data.get("value") or {}
            except Exception:
                self._gap(f"Clima economico {geo}", "risposta Eurostat illeggibile")
                continue
            if not values:
                self._gap(f"Clima economico {geo}",
                          "Eurostat ha risposto 200 ma senza valori per questa geografia")
                continue
            # Dall'indice del tempo si risale al periodo: si tiene il periodo
            # piu' recente che abbia davvero un valore, non il piu' recente in
            # assoluto, perche' gli ultimi mesi possono essere ancora vuoti.
            best = None
            for period, pos in index.items():
                raw = values.get(str(pos))
                if raw is None:
                    continue
                if best is None or period > best[0]:
                    best = (period, raw)
            if best is None:
                self._gap(f"Clima economico {geo}",
                          "Eurostat ha risposto con tutti i mesi vuoti")
                continue
            period, raw = best
            label = f"Clima economico {geo.replace('EU27_2020', 'Unione europea')}"
            point, why = _point(float(raw), period, "Eurostat (ei_bssi_m_r2)",
                                "indice, 100 = media storica", label, "eu_sentiment",
                                self.today, geo=geo,
                                above_average=float(raw) >= 100.0,
                                updated=data.get("updated"))
            if point is None:
                self._gap(label, why or "scartato")
                continue
            out[geo] = point
        return out

    # ------------------------------------------------------ clima sulle cripto
    def crypto_sentiment(self) -> dict | None:
        """Fear & Greed delle cripto: 0 e' panico, 100 e' euforia. Serve solo a
        chi ha cripto nel profilo, quindi `snapshot()` lo chiede solo in quel
        caso: una fonte in meno interrogata e' una fonte in meno che puo' cadere."""
        text, why = self._fetch("crypto_fng", FNG_URL)
        if text is None:
            self._gap("Clima sulle cripto", why or "nessun dato")
            return None
        try:
            data = json.loads(text)
            row = (data.get("data") or [])[0]
            value = int(float(row["value"]))
            when = datetime.fromtimestamp(int(row["timestamp"]), timezone.utc).date()
        except Exception:
            self._gap("Clima sulle cripto", "risposta alternative.me illeggibile")
            return None
        etichetta = (row.get("value_classification") or "").strip()
        point, why = _point(value, when.isoformat(), "alternative.me (Fear & Greed)",
                            "indice 0-100", "Clima sulle cripto", "crypto", self.today,
                            classification=etichetta,
                            in_parole=FNG_IT.get(etichetta.lower(), "incerto"))
        if point is None:
            self._gap("Clima sulle cripto", why or "scartato")
            return None
        return point


def _as_float(raw) -> float | None:
    """I CSV ufficiali usano la cella vuota, "N/A" e il trattino per il dato che
    non c'e': tutti e tre devono diventare None, non zero. Uno zero finto in una
    curva dei rendimenti sarebbe una notizia enorme e falsa."""
    if raw is None:
        return None
    s = str(raw).strip()
    if s in ("", "-", "--", "N/A", "NA", "null", "."):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _us_date(raw) -> str | None:
    """Dalle date americane (10/30/2026) alla forma ISO usata in tutto il motore."""
    if not raw:
        return None
    bits = str(raw).strip().split("/")
    if len(bits) != 3:
        return None
    try:
        return date(int(bits[2]), int(bits[0]), int(bits[1])).isoformat()
    except ValueError:
        return None


# ----------------------------------------------------------------- lo snapshot
# Buco noto e dichiarato: l'inflazione dell'area euro. La serie BCE ICP e la
# HICP di Eurostat rispondono entrambe HTTP 200 ma sono ferme alla fine del
# 2025, e non si e' trovata una fonte viva senza chiave. Meglio un dato assente
# e dichiarato che un dato vecchio di un anno presentato come attuale: con il
# secondo si prendono decisioni sbagliate convinti di avere i numeri giusti.
EURO_INFLATION_GAP = {
    "what": "Inflazione dell'area euro",
    "why": ("nessuna fonte viva senza chiave: la serie BCE ICP e la HICP di "
            "Eurostat rispondono 200 ma sono ferme alla fine del 2025, quindi "
            "il dato viene dichiarato mancante invece di essere usato vecchio"),
}


def snapshot(profile: dict | None = None, use_cache: bool = True,
             include_crypto: bool | None = None, today: date | None = None,
             retry_wait_s: float = 1.5) -> dict:
    """Il contesto di mercato in un dizionario solo.

    Raccoglie quello che riesce a raccogliere e dichiara il resto. Non solleva
    eccezioni e non si ferma per una fonte giu': ogni blocco e' isolato, cosi'
    una BCE lenta non porta via la curva americana (OP-06).

    `series` contiene le osservazioni, una per riga, ognuna con valore, data,
    fonte e unita'. `missing` contiene i buchi con il motivo. `sources` dice
    quale fonte ha risposto in questo ciclo: e' il dato che serve alla scheda
    "perche' mi fido di questi numeri".

    Il clima sulle cripto si chiede solo se il profilo ha cripto, oppure se lo
    si chiede esplicitamente con `include_crypto`.
    """
    m = Macro(use_cache=use_cache, today=today, retry_wait_s=retry_wait_s)
    if include_crypto is None:
        classes = (profile or {}).get("asset_classes") or []
        include_crypto = any(str(c).lower().startswith("crypto") for c in classes)

    series: dict[str, dict] = {}

    def gather(name: str, fn, many: bool = False, prefix: str = ""):
        """Ogni fonte dentro la sua rete di sicurezza: se una esplode in modo
        imprevisto, le altre devono comunque arrivare a destinazione."""
        try:
            got = fn()
        except Exception as e:
            m.stats["errors"] += 1
            m._gap(name, f"errore inatteso nel modulo ({type(e).__name__})")
            return
        if not got:
            return
        if many:
            for key, point in got.items():
                series[f"{prefix}{key}"] = point
        else:
            series[name] = got

    gather("fx", lambda: m.fx_eur(), many=True, prefix="fx_")
    gather("euro_curve", m.euro_yield_curve, many=True)
    gather("euro_stress", m.euro_stress)
    gather("ecb_policy_rate", m.ecb_policy_rate)
    gather("us_curve", m.us_yield_curve, many=True)
    gather("vix", m.vix)
    gather("us_cpi", m.us_inflation)
    gather("eu_sentiment", lambda: m.euro_sentiment(), many=True, prefix="eu_sentiment_")
    if include_crypto:
        gather("crypto_sentiment", m.crypto_sentiment)

    missing = list(m.gaps)
    missing.append(dict(EURO_INFLATION_GAP))

    # Quali fonti hanno risposto in questo ciclo. Si guarda la fonte citata
    # dalle osservazioni arrivate, non l'elenco delle fonti che vorremmo avere.
    answered = sorted({p["source"] for p in series.values()
                       if not p["source"].startswith("calcolato")})
    computed = sorted({p["source"] for p in series.values()
                       if p["source"].startswith("calcolato")})

    out = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "as_of": m.today.isoformat(),
        "series": series,
        "summary": _summary(series),
        "missing": missing,
        "sources": {"answered": answered, "computed": computed,
                    "count": len(answered)},
        "coverage": {"collected": len(series), "missing": len(missing)},
        "stats": dict(m.stats),
        "log": list(m.log),
        "crypto_requested": bool(include_crypto),
    }
    return out


def _summary(series: dict) -> dict:
    """Lettura in parole del contesto, solo a regole fisse e solo sui dati che
    sono arrivati. Non c'e' niente di indovinato qui: se un pezzo manca, la
    frase corrispondente non viene scritta."""
    out: dict[str, str] = {}
    stress = series.get("euro_stress")
    if stress:
        verso = ""
        if stress.get("rising") is True:
            verso = " ed è in aumento nell'ultima settimana"
        elif stress.get("rising") is False:
            verso = " ed è in calo nell'ultima settimana"
        out["stress"] = (f"Lo stress sul sistema finanziario dell'area euro è "
                         f"{stress['band']}{verso}.")
    vix = series.get("vix")
    if vix:
        out["volatilita"] = (f"La volatilità attesa sulle borse americane è in zona "
                             f"{vix['band']} ({_num(vix['value'], 0)} punti).")
    slope = series.get("us_curve_slope")
    if slope:
        out["curva_usa"] = ("La curva dei rendimenti americana è invertita: il "
                            "mercato si aspetta tassi più bassi in futuro."
                            if slope.get("inverted") else
                            "La curva dei rendimenti americana ha la forma normale, "
                            "con le scadenze lunghe che rendono più delle corte.")
    safe = series.get("euro_10y") or series.get("ecb_policy_rate")
    if safe:
        out["senza_rischio"] = (f"In euro, senza rischio, oggi si prende circa il "
                                f"{_num(safe['value'])}%: è il rendimento che un "
                                f"investimento deve battere per valere la pena.")
    cpi = series.get("us_cpi")
    if cpi and cpi.get("yoy_pct") is not None:
        out["inflazione_usa"] = (f"Negli Stati Uniti i prezzi sono saliti del "
                                 f"{_num(cpi['yoy_pct'], 1)}% nell'ultimo anno.")
    esi = series.get("eu_sentiment_EU27_2020")
    if esi:
        out["clima_ue"] = (f"Il clima economico in Europa è "
                           f"{'sopra' if esi.get('above_average') else 'sotto'} la "
                           f"media storica ({_num(esi['value'], 0)} contro 100).")
    fng = series.get("crypto_sentiment")
    if fng:
        out["cripto"] = (f"Sul mondo cripto il clima è di "
                         f"{fng.get('in_parole') or 'incerto'} ({fng['value']}/100).")
    return out
