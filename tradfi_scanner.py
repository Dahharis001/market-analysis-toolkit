"""
СКАНЕР ВСЕГО TradFi — валюты, индексы, сырьё.
Данные: Yahoo Finance (бесплатно, без ключа). Ничего не покупает.
Даёт сигнал по каждому инструменту на основе тренда + RSI + волатильности.

Это НЕ гарантированный прогноз. Рынок никто не предсказывает со 100%.
Это вероятностная оценка по индикаторам — инструмент для решения, не приказ.

Запуск:  python tradfi_scanner.py
"""

import sys
import time
import requests

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

INTERVAL = "15m"
RANGE    = "5d"
HEADERS  = {"User-Agent": "Mozilla/5.0"}

# Инструменты: (символ Yahoo, читаемое имя, категория)
INSTRUMENTS = [
    # --- Валюты (форекс) ---
    ("EURUSD=X", "EUR/USD", "Валюты"),
    ("GBPUSD=X", "GBP/USD", "Валюты"),
    ("USDJPY=X", "USD/JPY", "Валюты"),
    ("AUDUSD=X", "AUD/USD", "Валюты"),
    ("USDCHF=X", "USD/CHF", "Валюты"),
    ("USDCAD=X", "USD/CAD", "Валюты"),
    ("NZDUSD=X", "NZD/USD", "Валюты"),
    ("EURGBP=X", "EUR/GBP", "Валюты"),
    # --- Индексы ---
    ("^GSPC", "S&P 500", "Индексы"),
    ("^IXIC", "Nasdaq", "Индексы"),
    ("^DJI",  "Dow Jones", "Индексы"),
    ("^GDAXI","DAX (Германия)", "Индексы"),
    ("^FTSE", "FTSE 100 (UK)", "Индексы"),
    # --- Сырьё ---
    ("GC=F", "Золото", "Сырьё"),
    ("SI=F", "Серебро", "Сырьё"),
    ("CL=F", "Нефть WTI", "Сырьё"),
    ("NG=F", "Газ", "Сырьё"),
]


def get_closes(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"interval": INTERVAL, "range": RANGE}
    for _ in range(3):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=15)
            r.raise_for_status()
            d = r.json()["chart"]["result"][0]
            raw = d["indicators"]["quote"][0]["close"]
            return [c for c in raw if c is not None]
        except Exception:
            time.sleep(1)
    return None


def ema(values, period):
    k = 2 / (period + 1)
    e = values[0]
    for v in values[1:]:
        e = v * k + e * (1 - k)
    return e


def rsi(closes, period=14):
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0)); losses.append(max(-d, 0))
    if len(gains) < period:
        return 50.0
    ag = sum(gains[:period]) / period
    al = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        ag = (ag * (period - 1) + gains[i]) / period
        al = (al * (period - 1) + losses[i]) / period
    if al == 0:
        return 100.0
    return 100 - 100 / (1 + ag / al)


def forecast(symbol, name, cat):
    closes = get_closes(symbol)
    if not closes or len(closes) < 30:
        return None
    price = closes[-1]
    e9, e21, e50 = ema(closes, 9), ema(closes, 21), ema(closes, 50)
    r = rsi(closes, 14)
    recent = closes[-16:]
    volat = (max(recent) - min(recent)) / price * 100
    # импульс за последние свечи
    momentum = (closes[-1] - closes[-8]) / closes[-8] * 100

    score = 0
    if e9 > e21:   score += 1
    if e21 > e50:  score += 1   # средний тренд тоже вверх
    if 45 < r < 68: score += 1
    if momentum > 0: score += 1
    if e9 < e21:   score -= 1
    if r > 75:     score -= 1

    if score >= 3:
        view = "📈 ВВЕРХ (бычий)"
    elif score <= 0:
        view = "📉 ВНИЗ (медвежий)"
    else:
        view = "➡️ БОКОВИК (нет тренда)"

    return {"name": name, "cat": cat, "price": price, "rsi": r,
            "volat": volat, "momentum": momentum, "score": score, "view": view}


def fmt_price(p):
    if p > 1000:  return f"{p:,.1f}"
    if p > 10:    return f"{p:.3f}"
    return f"{p:.5f}"


def main():
    print("=" * 70)
    print("  ПРОГНОЗ TradFi  (валюты • индексы • сырьё)")
    print(f"  Таймфрейм {INTERVAL} | источник Yahoo Finance")
    print("  Вероятностная оценка по индикаторам. НЕ гарантия. Риск — твой.")
    print("=" * 70)

    results = []
    for sym, name, cat in INSTRUMENTS:
        f = forecast(sym, name, cat)
        if f:
            results.append(f)
        else:
            print(f"  (нет данных: {name} — возможно рынок закрыт)")

    # группируем по категориям
    for cat in ["Валюты", "Индексы", "Сырьё"]:
        group = [r for r in results if r["cat"] == cat]
        if not group:
            continue
        group.sort(key=lambda x: x["score"], reverse=True)
        print(f"\n  ═══ {cat} ═══")
        print(f"  {'ИНСТРУМЕНТ':<16}{'ЦЕНА':>12}{'RSI':>6}{'ИМПУЛЬС':>9}  ПРОГНОЗ")
        print("  " + "-" * 62)
        for r in group:
            print(f"  {r['name']:<16}{fmt_price(r['price']):>12}{r['rsi']:>6.0f}"
                  f"{r['momentum']:>+8.2f}%  {r['view']}")

    # общий топ бычьих
    bulls = sorted([r for r in results if r["score"] >= 3],
                   key=lambda x: (x["score"], x["momentum"]), reverse=True)
    print("\n  ⭐ Самые сильные восходящие сигналы сейчас:")
    if bulls:
        for r in bulls[:5]:
            print(f"     📈 {r['name']:<16} импульс {r['momentum']:+.2f}%, движ {r['volat']:.2f}%")
    else:
        print("     Сильных бычьих сигналов нет — рынок в боковике или нисходящий.")

    print("\n  ⚠️ Это оценка вероятности, не предсказание. Всегда ставь стоп-лосс.")


if __name__ == "__main__":
    main()
