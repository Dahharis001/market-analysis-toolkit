"""
ПРОФЕССИОНАЛЬНЫЙ СКАНЕР ЗОЛОТА (XAU/USD, фьючерс GC=F).
Данные: Yahoo Finance (бесплатно, без ключа). Ничего не покупает.

Анализ как у профи:
  • Мультитаймфрейм (15м + 1ч + дневной) — ловим тренд на всех горизонтах
  • EMA 9/21/50  — направление тренда
  • MACD          — импульс и развороты
  • RSI           — перекупленность/перепроданность
  • Bollinger     — границы волатильности (где цена дорогая/дешёвая)
  • ATR           — реальная волатильность -> грамотный стоп-лосс
  • Уровни        — поддержка/сопротивление по свингам
  • Итоговый вердикт + готовый план входа (вход/стоп/тейк)

Запуск:  python silver_scanner.py
Выход:   Ctrl + C
"""

import sys
import time
import requests

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

try:
    import winsound
    def beep():
        for f in (880, 1100, 1320):
            winsound.Beep(f, 150)
except Exception:
    def beep():
        print("\a", end="", flush=True)

# ----------------- НАСТРОЙКИ -----------------
SYMBOL      = "GC=F"     # золото. XAUUSD.s у брокера = почти то же (спот vs фьючерс)
DEPOSIT_USD = 120.0      # депозит
SPREAD_PCT  = 0.0004     # спред/комиссия за круг по золоту (уточни у брокера)
REFRESH_SEC = 60         # пауза между обновлениями
RISK_PCT    = 0.02       # риск на сделку = 2% депозита
ATR_STOP_MULT   = 1.5    # стоп = вход - 1.5*ATR (профессиональный способ)
ATR_TARGET_MULT = 2.5    # тейк = вход + 2.5*ATR (риск/прибыль ~1:1.7)
# ---------------------------------------------

HEADERS = {"User-Agent": "Mozilla/5.0"}
TIMEFRAMES = [("15m", "5d", "15 мин"), ("1h", "1mo", "1 час"), ("1d", "6mo", "Дневной")]


def fetch(symbol, interval, rng):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    for _ in range(4):
        try:
            r = requests.get(url, params={"interval": interval, "range": rng},
                             headers=HEADERS, timeout=15)
            r.raise_for_status()
            q = r.json()["chart"]["result"][0]["indicators"]["quote"][0]
            n = len(q["close"])
            rows = [(q["close"][i], q["high"][i], q["low"][i]) for i in range(n)
                    if q["close"][i] is not None and q["high"][i] is not None
                    and q["low"][i] is not None]
            closes = [x[0] for x in rows]
            highs  = [x[1] for x in rows]
            lows   = [x[2] for x in rows]
            return closes, highs, lows
        except Exception:
            time.sleep(2)
    return None, None, None


def ema_series(values, period):
    k = 2 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def ema(values, period):
    return ema_series(values, period)[-1]


def rsi(closes, period=14):
    g = [max(closes[i] - closes[i - 1], 0) for i in range(1, len(closes))]
    l = [max(closes[i - 1] - closes[i], 0) for i in range(1, len(closes))]
    if len(g) < period:
        return 50.0
    ag = sum(g[:period]) / period
    al = sum(l[:period]) / period
    for i in range(period, len(g)):
        ag = (ag * (period - 1) + g[i]) / period
        al = (al * (period - 1) + l[i]) / period
    return 100.0 if al == 0 else 100 - 100 / (1 + ag / al)


def macd(closes):
    if len(closes) < 35:
        return 0.0, 0.0, 0.0
    e12 = ema_series(closes, 12)
    e26 = ema_series(closes, 26)
    macd_line = [a - b for a, b in zip(e12, e26)]
    signal = ema_series(macd_line, 9)
    hist = macd_line[-1] - signal[-1]
    return macd_line[-1], signal[-1], hist


def bollinger(closes, period=20, mult=2):
    seg = closes[-period:]
    sma = sum(seg) / len(seg)
    var = sum((x - sma) ** 2 for x in seg) / len(seg)
    sd = var ** 0.5
    return sma + mult * sd, sma, sma - mult * sd


def atr(highs, lows, closes, period=14):
    trs = []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i - 1]),
                 abs(lows[i] - closes[i - 1]))
        trs.append(tr)
    if len(trs) < period:
        return sum(trs) / len(trs) if trs else 0.0
    return sum(trs[-period:]) / period


def analyze_tf(symbol, interval, rng):
    closes, highs, lows = fetch(symbol, interval, rng)
    if not closes or len(closes) < 50:
        return None
    price = closes[-1]
    e9, e21, e50 = ema(closes, 9), ema(closes, 21), ema(closes, 50)
    r = rsi(closes)
    m_line, m_sig, m_hist = macd(closes)
    bb_up, bb_mid, bb_low = bollinger(closes)
    a = atr(highs, lows, closes)

    # балл тренда по этому ТФ
    score = 0
    if e9 > e21: score += 1
    if e21 > e50: score += 1
    if m_hist > 0: score += 1          # MACD бычий
    if 45 < r < 70: score += 1
    if price < bb_low * 1.002: score += 1   # у нижней границы — дёшево
    if e9 < e21: score -= 1
    if e21 < e50: score -= 1
    if m_hist < 0: score -= 1
    if r > 75 or price > bb_up * 0.998: score -= 1   # перекуплено/дорого

    trend = "ВВЕРХ" if (e9 > e21 > e50) else ("ВНИЗ" if (e9 < e21 < e50) else "смешанный")
    resist = max(highs[-40:])
    support = min(lows[-40:])

    return {
        "price": price, "e9": e9, "e21": e21, "e50": e50, "rsi": r,
        "macd_hist": m_hist, "bb_up": bb_up, "bb_low": bb_low, "atr": a,
        "score": score, "trend": trend, "resist": resist, "support": support,
    }


def run_once():
    data = {}
    for interval, rng, label in TIMEFRAMES:
        res = analyze_tf(SYMBOL, interval, rng)
        if res:
            data[label] = res
    if not data:
        print("  Нет данных (рынок закрыт или связь). Повтор позже.")
        return

    price = data[list(data)[0]]["price"]
    print(f"\n{'='*64}")
    print(f"  ЗОЛОТО (XAU/USD)   Цена: {price:.3f}   [{time.strftime('%H:%M:%S')}]")
    print(f"{'='*64}")

    total = 0
    for label in ["15 мин", "1 час", "Дневной"]:
        if label not in data:
            continue
        d = data[label]
        total += d["score"]
        macd_txt = "бычий" if d["macd_hist"] > 0 else "медвежий"
        print(f"  [{label:<8}] тренд {d['trend']:<10} RSI {d['rsi']:>3.0f}  "
              f"MACD {macd_txt:<8} балл {d['score']:+d}")
        print(f"             EMA9 {d['e9']:.3f} | EMA21 {d['e21']:.3f} | EMA50 {d['e50']:.3f}")
        print(f"             Bollinger: низ {d['bb_low']:.3f} <-> верх {d['bb_up']:.3f}")

    # уровни берём с 1ч (или 15м)
    ref = data.get("1 час") or data.get("15 мин")
    print(f"\n  УРОВНИ:  Сопротивление {ref['resist']:.3f} (+{(ref['resist']-price)/price*100:.2f}%)  "
          f"| Поддержка {ref['support']:.3f} ({(ref['support']-price)/price*100:.2f}%)")

    # ---- ИТОГОВЫЙ ВЕРДИКТ ----
    print(f"\n  ИТОГОВЫЙ БАЛЛ ПО ВСЕМ ТФ: {total:+d}")
    short = data.get("15 мин")
    daily = data.get("Дневной")

    if total >= 5:
        verdict = "🟢 СИЛЬНЫЙ БЫЧИЙ — тренд вверх на всех горизонтах"
        bullish = True
    elif total >= 2:
        verdict = "🟡 СЛАБЫЙ БЫЧИЙ — есть рост, но не на всех ТФ (осторожно)"
        bullish = True
    elif total <= -2:
        verdict = "🔴 МЕДВЕЖИЙ — тренд вниз, покупать опасно"
        bullish = False
    else:
        verdict = "⚪ БОКОВИК / неопределённость — лучше ждать"
        bullish = False

    print(f"  {verdict}")

    # предупреждение о конфликте таймфреймов
    if short and daily and short["trend"] == "ВВЕРХ" and daily["trend"] == "ВНИЗ":
        print("  ⚠️ ВНИМАНИЕ: краткосрок вверх, но ДНЕВНОЙ ТРЕНД ВНИЗ —")
        print("     это может быть отскок внутри падения. Не покупай на хае,")
        print("     жди пробоя сопротивления или входи только от поддержки.")

    # ---- ПЛАН ВХОДА (на основе ATR) ----
    if bullish and short:
        a = short["atr"]
        entry = price
        stop  = entry - ATR_STOP_MULT * a
        targ  = entry + ATR_TARGET_MULT * a
        stop_pct = (entry - stop) / entry
        risk_usd = DEPOSIT_USD * RISK_PCT
        position = min(risk_usd / stop_pct, DEPOSIT_USD) if stop_pct > 0 else DEPOSIT_USD
        fee = position * SPREAD_PCT * 2
        loss = position * stop_pct + fee
        gain = position * (targ - entry) / entry - fee
        rr = gain / loss if loss > 0 else 0

        beep()
        print(f"\n  ⭐ ПЛАН ВХОДА (стоп по ATR — профессиональный способ):")
        print(f"     ┌──────────────────────────────────────────────")
        print(f"     │ ВХОД:        {entry:.3f}")
        print(f"     │ СТОП-ЛОСС:   {stop:.3f}  (-{stop_pct*100:.2f}%, 1.5xATR)")
        print(f"     │ ТЕЙК:        {targ:.3f}  (+{(targ-entry)/entry*100:.2f}%, 2.5xATR)")
        print(f"     │ Размер:      ${position:.2f}")
        print(f"     ├──────────────────────────────────────────────")
        print(f"     │ Риск:        ~${loss:.2f}   Потенциал: ~${gain:.2f}")
        print(f"     │ Риск/прибыль: 1 к {rr:.1f}")
        print(f"     └──────────────────────────────────────────────")
        print(f"     ⚠️ СТОП-ЛОСС ставь сразу! С плечом цифры умножаются.")
    else:
        print("\n  План входа не выдаю — сигнал не бычий. Лучшая сделка — та, что не сделал.")


def main():
    print("ПРОФ-СКАНЕР ЗОЛОТА запущен. Ctrl+C для выхода.")
    print("Мультитаймфрейм: 15м + 1ч + дневной. НЕ финсовет, риск твой.")
    while True:
        try:
            run_once()
        except Exception as e:
            print(f"  Ошибка: {e}")
        print(f"\n  ...следующее обновление через {REFRESH_SEC}с...")
        time.sleep(REFRESH_SEC)


if __name__ == "__main__":
    main()
