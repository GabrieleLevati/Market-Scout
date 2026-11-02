"""Indicatori tecnici previsti dall'FDD (3.4): RSI, MACD, EMA50, EMA200,
Bollinger Bands, ADX, volume. Implementati su stdlib, senza pandas/numpy."""

from __future__ import annotations


def ema(values: list[float], period: int) -> list[float]:
    k = 2.0 / (period + 1)
    out: list[float] = []
    prev = values[0]
    for v in values:
        prev = v * k + prev * (1 - k)
        out.append(prev)
    return out


def sma(values: list[float], period: int) -> list[float]:
    out, acc = [], 0.0
    for i, v in enumerate(values):
        acc += v
        if i >= period:
            acc -= values[i - period]
        out.append(acc / min(i + 1, period))
    return out


def stdev(values: list[float], period: int) -> list[float]:
    out = []
    for i in range(len(values)):
        win = values[max(0, i - period + 1): i + 1]
        m = sum(win) / len(win)
        var = sum((x - m) ** 2 for x in win) / len(win)
        out.append(var ** 0.5)
    return out


def rsi(closes: list[float], period: int = 14) -> list[float]:
    """RSI di Wilder."""
    out = [50.0]
    gain = loss = 0.0
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        up, down = max(delta, 0.0), max(-delta, 0.0)
        if i <= period:
            gain += up / period
            loss += down / period
        else:
            gain = (gain * (period - 1) + up) / period
            loss = (loss * (period - 1) + down) / period
        out.append(100.0 if loss == 0 else 100 - 100 / (1 + gain / loss))
    return out


def macd(closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9):
    ef, es = ema(closes, fast), ema(closes, slow)
    line = [a - b for a, b in zip(ef, es)]
    sig = ema(line, signal)
    hist = [a - b for a, b in zip(line, sig)]
    return line, sig, hist


def bollinger(closes: list[float], period: int = 20, mult: float = 2.0):
    mid = sma(closes, period)
    sd = stdev(closes, period)
    upper = [m + mult * s for m, s in zip(mid, sd)]
    lower = [m - mult * s for m, s in zip(mid, sd)]
    return lower, mid, upper


def adx(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list[float]:
    """ADX di Wilder (forza del trend, 0-100)."""
    tr_s = dm_pos_s = dm_neg_s = 0.0
    adx_v = 0.0
    out = [0.0]
    for i in range(1, len(closes)):
        up = highs[i] - highs[i - 1]
        dn = lows[i - 1] - lows[i]
        dm_pos = up if (up > dn and up > 0) else 0.0
        dm_neg = dn if (dn > up and dn > 0) else 0.0
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        if i <= period:
            tr_s += tr
            dm_pos_s += dm_pos
            dm_neg_s += dm_neg
        else:
            tr_s = tr_s - tr_s / period + tr
            dm_pos_s = dm_pos_s - dm_pos_s / period + dm_pos
            dm_neg_s = dm_neg_s - dm_neg_s / period + dm_neg
        if tr_s > 0:
            di_pos = 100 * dm_pos_s / tr_s
            di_neg = 100 * dm_neg_s / tr_s
            denom = di_pos + di_neg
            dx = 100 * abs(di_pos - di_neg) / denom if denom else 0.0
            adx_v = dx if i <= period + 1 else (adx_v * (period - 1) + dx) / period
        out.append(adx_v)
    return out


def atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float:
    trs = []
    for i in range(1, len(closes)):
        trs.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    win = trs[-period:] or [0.0]
    return sum(win) / len(win)


def annualized_volatility(closes: list[float], window: int = 90) -> float:
    rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))][-window:]
    m = sum(rets) / len(rets)
    var = sum((r - m) ** 2 for r in rets) / len(rets)
    return (var ** 0.5) * (252 ** 0.5)


def max_drawdown(closes: list[float]) -> float:
    peak, mdd = closes[0], 0.0
    for c in closes:
        peak = max(peak, c)
        mdd = min(mdd, c / peak - 1)
    return mdd


def snapshot(series: dict) -> dict:
    """Pacchetto di indicatori sull'ultima barra: ciò che gli agenti consumano."""
    c, h, l, v = series["close"], series["high"], series["low"], series["volume"]
    macd_line, _, hist = macd(c)
    bb_low, bb_mid, bb_up = bollinger(c)
    width = bb_up[-1] - bb_low[-1]
    rsi_v = rsi(c)[-1]
    ema50, ema200 = ema(c, 50)[-1], ema(c, 200)[-1]
    vol_avg = sum(v[-20:]) / 20
    high_52w, low_52w = max(c), min(c)
    resistance = max(c[-61:-1])
    return {
        "price": round(c[-1], 2),
        "rsi": round(rsi_v, 1),
        "macd_line": round(macd_line[-1], 3),
        "macd_line_pct": round(macd_line[-1] / c[-1] * 100, 3),
        "macd_hist": round(hist[-1], 3),
        "macd_positive": hist[-1] > 0,
        "ema50": round(ema50, 2),
        "ema200": round(ema200, 2),
        "above_ema50": c[-1] > ema50,
        "above_ema200": c[-1] > ema200,
        "golden_cross": ema50 > ema200,
        "bb_position": round((c[-1] - bb_low[-1]) / width, 3) if width else 0.5,
        "bb_upper": round(bb_up[-1], 2),
        "bb_lower": round(bb_low[-1], 2),
        "adx": round(adx(h, l, c)[-1], 1),
        "volume_ratio": round(v[-1] / vol_avg, 2) if vol_avg else 1.0,
        "atr": round(atr(h, l, c), 2),
        "volatility": round(annualized_volatility(c), 4),
        "max_drawdown": round(max_drawdown(c), 4),
        "high_52w": round(high_52w, 2),
        "low_52w": round(low_52w, 2),
        "from_high_52w": round(c[-1] / high_52w - 1, 4),
        "resistance_60d": round(resistance, 2),
        "breakout": c[-1] > resistance,
        "perf_1m": round(c[-1] / c[-22] - 1, 4),
        "perf_3m": round(c[-1] / c[-64] - 1, 4),
        "perf_6m": round(c[-1] / c[-127] - 1, 4),
    }
