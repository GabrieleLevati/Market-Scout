"""Adapter sui dati di mercato reali.

È il modulo che l'FDD chiama "data provider" (3.2). Prende da Yahoo Finance
quello che si può prendere senza chiave e senza licenza a pagamento:

* **prezzi** (OHLCV giornaliero, 2 anni) — endpoint `chart`;
* **bilanci** (ricavi, utile netto, EPS diluito, debito, patrimonio, free cash
  flow; annuali e trimestrali) — endpoint `fundamentals-timeseries`;
* **notizie** (titolo, editore, data) — endpoint `search`.

Quello che NON si può prendere senza un contratto dati è dichiarato, non finto:
operazioni degli insider, dati di bilancio di ETF e obbligazioni, metriche
on-chain delle crypto. Dove il dato manca, il sistema abbassa la confidenza e lo
scrive (è il comportamento già previsto in `valuation.confidence`).

Nessun dato di analisti: non chiediamo rating né target price, perché il valore
lo stima il sistema (`valuation.py`) e il giudizio lo dà Gemini.

Tutto passa da una cache su disco giornaliera (`.data_cache/`): un secondo
ciclo nello stesso giorno non tocca la rete.
"""

from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

CACHE_DIR = Path(__file__).resolve().parent.parent / ".data_cache"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
TIMEOUT_S = 25
PACE_S = 0.35               # distanza minima tra due chiamate allo stesso host
MIN_BARS = 260              # sedute minime per calcolare EMA200 e un anno di storia

FUND_FIELDS_ANNUAL = ["annualTotalRevenue", "annualNetIncome", "annualDilutedEPS",
                      "annualTotalDebt", "annualStockholdersEquity", "annualFreeCashFlow",
                      "annualGrossProfit"]
FUND_FIELDS_QUARTERLY = ["quarterlyTotalRevenue", "quarterlyNetIncome",
                         "quarterlyDilutedEPS", "quarterlyFreeCashFlow"]


class DataError(RuntimeError):
    pass


class Yahoo:
    """Client minimale: niente dipendenze, cache giornaliera, un tentativo di
    recupero sugli errori temporanei."""

    def __init__(self, use_cache: bool = True, pace_s: float = PACE_S):
        self.use_cache = use_cache
        self.pace_s = pace_s
        self._last = 0.0
        self.stats = {"http": 0, "cache": 0, "errors": 0, "bytes": 0}
        self.log: list[dict] = []
        if use_cache:
            CACHE_DIR.mkdir(exist_ok=True)

    # ------------------------------------------------------------------ rete
    def _cache_file(self, kind: str, symbol: str) -> Path:
        safe = urllib.parse.quote(symbol, safe="")
        return CACHE_DIR / f"{kind}_{safe}_{date.today().isoformat()}.json"

    def _fetch(self, kind: str, url: str, symbol: str) -> dict:
        cf = self._cache_file(kind, symbol)
        if self.use_cache and cf.exists():
            try:
                self.stats["cache"] += 1
                return json.loads(cf.read_text(encoding="utf-8"))
            except Exception:
                pass
        for attempt in (1, 2):
            wait = self.pace_s - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA,
                                                           "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=TIMEOUT_S,
                                            context=ssl.create_default_context()) as r:
                    raw = r.read()
                self._last = time.monotonic()
                self.stats["http"] += 1
                self.stats["bytes"] += len(raw)
                data = json.loads(raw)
                if self.use_cache:
                    cf.write_text(json.dumps(data), encoding="utf-8")
                self.log.append({"kind": kind, "symbol": symbol, "status": "ok"})
                return data
            except urllib.error.HTTPError as e:
                self._last = time.monotonic()
                if e.code in (429, 500, 502, 503) and attempt == 1:
                    time.sleep(2.0)
                    continue
                self.stats["errors"] += 1
                self.log.append({"kind": kind, "symbol": symbol, "status": f"http {e.code}"})
                raise DataError(f"{symbol}: HTTP {e.code} su {kind}") from e
            except Exception as e:
                self._last = time.monotonic()
                if attempt == 1:
                    time.sleep(1.0)
                    continue
                self.stats["errors"] += 1
                self.log.append({"kind": kind, "symbol": symbol, "status": type(e).__name__})
                raise DataError(f"{symbol}: {type(e).__name__} su {kind}") from e
        raise DataError(f"{symbol}: {kind} non disponibile")

    # ------------------------------------------------------------- prezzi
    def chart(self, symbol: str, range_: str = "2y", min_bars: int = MIN_BARS) -> dict:
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/"
               f"{urllib.parse.quote(symbol)}?range={range_}&interval=1d"
               f"&includePrePost=false&events=div%2Csplit")
        data = self._fetch("chart", url, symbol)
        res = (data.get("chart") or {}).get("result") or []
        if not res:
            err = ((data.get("chart") or {}).get("error") or {}).get("description", "nessun dato")
            raise DataError(f"{symbol}: {err}")
        r = res[0]
        meta = r.get("meta") or {}
        ts = r.get("timestamp") or []
        q = ((r.get("indicators") or {}).get("quote") or [{}])[0]
        rows = []
        for i, t in enumerate(ts):
            o, h, l, c, v = (q.get("open") or [])[i], (q.get("high") or [])[i], \
                            (q.get("low") or [])[i], (q.get("close") or [])[i], \
                            (q.get("volume") or [])[i]
            if None in (o, h, l, c):
                continue                      # seduta incompleta: si salta
            rows.append((datetime.fromtimestamp(t, timezone.utc).date().isoformat(),
                         float(o), float(h), float(l), float(c), float(v or 0)))
        if len(rows) < min_bars:
            raise DataError(f"{symbol}: solo {len(rows)} sedute disponibili "
                            f"(ne servono {min_bars})")
        return {
            "date": [r[0] for r in rows],
            "open": [r[1] for r in rows],
            "high": [r[2] for r in rows],
            "low": [r[3] for r in rows],
            "close": [r[4] for r in rows],
            "volume": [r[5] for r in rows],
            "currency": meta.get("currency", "USD"),
            "exchange": meta.get("fullExchangeName", ""),
            "symbol": meta.get("symbol", symbol),
        }

    def fx_to_eur(self, currency: str) -> float | None:
        """Cambio verso euro di oggi. Senza rete o senza quotazione, chi chiama
        ricade sulla tabella statica e lo dichiara."""
        if currency == "EUR":
            return 1.0
        try:
            ch = self.chart(f"{currency}EUR=X", range_="5d", min_bars=1)
            return round(ch["close"][-1], 6)
        except DataError:
            return None

    # -------------------------------------------------------- bilanci
    def statements(self, symbol: str) -> dict:
        """Serie di bilancio annuali e trimestrali, già riordinate per data."""
        types = ",".join(FUND_FIELDS_ANNUAL + FUND_FIELDS_QUARTERLY)
        url = (f"https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/"
               f"timeseries/{urllib.parse.quote(symbol)}?symbol={urllib.parse.quote(symbol)}"
               f"&type={types}&period1=1420070400&period2=2000000000&merge=false")
        data = self._fetch("statements", url, symbol)
        out: dict[str, list[dict]] = {}
        for block in (data.get("timeseries") or {}).get("result") or []:
            for key, values in block.items():
                if key in ("meta", "timestamp") or not isinstance(values, list):
                    continue
                points = []
                for v in values:
                    if not isinstance(v, dict):
                        continue
                    raw = (v.get("reportedValue") or {}).get("raw")
                    if raw is None or not v.get("asOfDate"):
                        continue
                    points.append({"date": v["asOfDate"], "value": float(raw),
                                   "currency": v.get("currencyCode")})
                if points:
                    out[key] = sorted(points, key=lambda p: p["date"])
        return out

    # ---------------------------------------------------------------- news
    def news(self, symbol: str, query: str | None = None, count: int = 8) -> list[dict]:
        q = urllib.parse.quote(query or symbol)
        url = (f"https://query1.finance.yahoo.com/v1/finance/search?q={q}"
               f"&newsCount={count}&quotesCount=0&enableFuzzyQuery=false")
        # la chiave di cache include la query: cercare per simbolo o per nome
        # dà risultati diversi e non devono sovrascriversi
        try:
            data = self._fetch("news", url, f"{symbol}~{query or symbol}")
        except DataError:
            return []
        out = []
        for item in data.get("news") or []:
            ts = item.get("providerPublishTime")
            when = (datetime.fromtimestamp(ts, timezone.utc).date().isoformat()
                    if ts else date.today().isoformat())
            title = (item.get("title") or "").strip()
            if not title:
                continue
            out.append({"date": when, "headline": title,
                        "source": item.get("publisher") or "Yahoo Finance",
                        "url": item.get("link") or "",
                        # la polarità la decide il modello: senza LLM resta None
                        "polarity": None})
        return sorted(out, key=lambda n: n["date"], reverse=True)[:count]


# ------------------------------------------------------------------ derivate
def _last(series: list[dict] | None):
    return series[-1]["value"] if series else None


def _growth(series: list[dict] | None, periods: int = 1):
    if not series or len(series) <= periods:
        return None
    new, old = series[-1]["value"], series[-1 - periods]["value"]
    if old is None or old == 0:
        return None
    if old < 0 and new < 0:
        return None                       # crescita non interpretabile da due perdite
    return new / abs(old) - 1


def _ttm(series: list[dict] | None, quarters: int = 4, offset: int = 0):
    """Somma degli ultimi trimestri (trailing twelve months)."""
    if not series or len(series) < quarters + offset:
        return None
    window = series[len(series) - quarters - offset: len(series) - offset]
    return sum(p["value"] for p in window)


def statement_currency(statements: dict) -> str | None:
    """Valuta in cui l'emittente pubblica i bilanci: può essere diversa da
    quella di quotazione (TSMC pubblica in TWD e quota in dollari a New York).
    Senza questo controllo l'utile per azione sarebbe incomparabile col prezzo."""
    for key in ("quarterlyDilutedEPS", "annualDilutedEPS", "annualTotalRevenue"):
        for p in statements.get(key) or []:
            if p.get("currency"):
                return p["currency"]
    return None


def derive_fundamentals(statements: dict, price: float, eps_fx: float = 1.0) -> dict:
    """Dai bilanci grezzi alle metriche che usano gli agenti. Ogni voce assente
    resta `None`: nessun valore inventato, e la confidenza scende di conseguenza."""
    rev_a = statements.get("annualTotalRevenue")
    ni_a = statements.get("annualNetIncome")
    eps_a = statements.get("annualDilutedEPS")
    debt_a = statements.get("annualTotalDebt")
    eq_a = statements.get("annualStockholdersEquity")
    fcf_a = statements.get("annualFreeCashFlow")
    gp_a = statements.get("annualGrossProfit")
    rev_q = statements.get("quarterlyTotalRevenue")
    eps_q = statements.get("quarterlyDilutedEPS")
    ni_q = statements.get("quarterlyNetIncome")
    fcf_q = statements.get("quarterlyFreeCashFlow")

    revenue = _ttm(rev_q) or _last(rev_a)
    net_income = _ttm(ni_q) or _last(ni_a)
    # `eps_fx` porta l'utile per azione nella valuta del prezzo
    eps_ttm = _ttm(eps_q) or _last(eps_a)
    eps_ttm = eps_ttm * eps_fx if eps_ttm is not None else None
    eps_ttm_prev = _ttm(eps_q, offset=1)
    eps_ttm_prev = eps_ttm_prev * eps_fx if eps_ttm_prev is not None else None
    fcf = _ttm(fcf_q) or _last(fcf_a)
    debt, equity = _last(debt_a), _last(eq_a)

    rev_growth = _growth(rev_q, 4) if rev_q and len(rev_q) >= 5 else _growth(rev_a)
    eps_growth = _growth(eps_q, 4) if eps_q and len(eps_q) >= 5 else _growth(eps_a)

    def ratio(a, b):
        return (a / b) if (a is not None and b not in (None, 0)) else None

    invested = (debt or 0) + (equity or 0) if (debt is not None or equity is not None) else None
    f = {
        "basis": "bilancio (dati reali)",
        "revenue_growth": rev_growth,
        "eps_growth": eps_growth,
        "gross_margin": ratio(_last(gp_a), _last(rev_a)),
        "net_margin": ratio(net_income, revenue),
        "fcf_margin": ratio(fcf, revenue),
        "roe": ratio(net_income, equity),
        "roic": ratio(net_income, invested) if invested else None,
        "debt_to_equity": ratio(debt, equity),
        "eps_ttm": eps_ttm,
        "pe": ratio(price, eps_ttm) if (eps_ttm or 0) > 0 else None,
        "revenue_ttm": revenue,
        "net_income_ttm": net_income,
        # revisione della stima: un nuovo trimestre pubblicato sposta l'utile a
        # dodici mesi, e con esso il valore. Nessun analista coinvolto.
        "eps_ttm_change": (eps_ttm / eps_ttm_prev - 1)
        if (eps_ttm and eps_ttm_prev and eps_ttm_prev > 0) else None,
        "statement_currency": statement_currency(statements),
        "eps_fx_applied": eps_fx,
        "last_report_date": (rev_q or eps_q or [{}])[-1].get("date") if (rev_q or eps_q) else None,
        "quarterly_revenue_yoy": _growth(rev_q, 4) if rev_q and len(rev_q) >= 5 else None,
        "quarterly_eps_yoy": _growth(eps_q, 4) if eps_q and len(eps_q) >= 5 else None,
    }
    f["fields_available"] = sum(1 for k, v in f.items()
                                if k not in ("basis", "fields_available") and v is not None)
    return f
