"""
СКАНЕР АКЦИЙ (Bybit TradFi — AAPL, NVIDIA, MSFT и др.).
Данные: Yahoo Finance (бесплатно, без ключа). Ничего не покупает.

ВАЖНОЕ ПРЕИМУЩЕСТВО АКЦИЙ на Bybit TradFi:
  • Плечо ограничено 5x — тебя НЕ ликвидируют на шуме (в отличие от металлов 500x)
  • Мелкая мин. сделка (0.1 лот = ~$20-30) — можно почти как за наличные
  • Реальные компании с понятными трендами

ОГРАНИЧЕНИЕ: акции торгуются только в часы рынка США
  (16:30-23:00 МСК пн-пт). Вне этих часов цена не двигается.

Запуск:  python stock_scanner.py
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
INTERVAL    = "15m"
RANGE       = "5d"
DEPOSIT_USD = 131.0
REFRESH_SEC = 60
RISK_PCT    = 0.05       # на акциях можно рисковать чуть больше (нет ликвидации на шуме)
STOP_PCT    = 0.015      # стоп 1.5% (акции двигаются крупнее форекса)
TARGET_PCT  = 0.030      # тейк 3.0% (риск/прибыль 1:2)
TOP_SHOW    = 12
# Тикеры Yahoo = тикеры на Bybit TradFi
STOCKS = [
    ("AAPL",  "Apple"),
    ("NVDA",  "NVIDIA"),
    ("MSFT",  "Microsoft"),
    ("GOOGL", "Google"),
    ("META",  "Meta"),
    ("AMZN",  "Amazon"),
    ("TSLA",  "Tesla"),
    ("MSTR",  "Strategy"),
]
# ---------------------------------------------

HEADERS = {"User-Agent": "Mozilla/5.0"}


def get_data(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"interval": INTERVAL, "range": RANGE}
    for _ in range(3):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=15)
            r.raise_for_status()
            q = r.json()["chart"]["result"][0]["indicators"]["quote"][0]
            n = len(q["close"])
            rows = [(q["close"][i], q["high"][i], q["low"][i]) for i in range(n)
                    if q["close"][i] and q["high"][i] and q["low"][i]]
            return [x[0] for x in rows], [x[1] for x in rows], [x[2] for x in rows]
        except Exception:
            time.sleep(1)
    return None, None, None


def ema(values, period):
    k = 2 / (period + 1)
    e = values[0]
    for v in values[1:]:
        e = v * k + e * (1 - k)
    return e


def rsi(closes, period=14):
    g = [max(closes[i] - closes[i-1], 0) for i in range(1, len(closes))]
    l = [max(closes[i-1] - closes[i], 0) for i in range(1, len(closes))]
    if len(g) < period:
        return 50.0
    ag = sum(g[:period]) / period
    al = sum(l[:period]) / period
    for i in range(period, len(g)):
        ag = (ag * (period-1) + g[i]) / period
        al = (al * (period-1) + l[i]) / period
    return 100.0 if al == 0 else 100 - 100 / (1 + ag/al)


def analyze(symbol, name):
    closes, highs, lows = get_data(symbol)
    if not closes or len(closes) < 30:
        return None
    price = closes[-1]
    e9, e21, e50 = ema(closes, 9), ema(closes, 21), ema(closes, 50)
    r = rsi(closes)
    recent = closes[-16:]
    volat = (max(recent) - min(recent)) / price * 100
    momentum = (closes[-1] - closes[-8]) / closes[-8] * 100

    score = 0
    if e9 > e21:    score += 1
    if e21 > e50:   score += 1
    if 45 < r < 68: score += 1
    if momentum > 0: score += 1
    if e9 < e21:    score -= 1
    if r > 75:      score -= 1

    return {"name": name, "symbol": symbol, "price": price, "rsi": r,
            "volat": volat, "momentum": momentum, "score": score,
            "resist": max(highs[-40:]), "support": min(lows[-40:])}


def main():
    print("=" * 66)
    print(f"  СКАНЕР АКЦИЙ (Bybit TradFi)  | Депозит ${DEPOSIT_USD:.0f}")
    print("  Плечо на акциях макс 5x — безопаснее металлов. Риск твой.")
    print("=" * 66)

    while True:
        try:
            results = []
            for sym, name in STOCKS:
                a = analyze(sym, name)
                if a:
                    results.append(a)
            results.sort(key=lambda x: (x["score"], x["momentum"]), reverse=True)

            print(f"\n[{time.strftime('%H:%M:%S')}]  Акции:")
            print(f"  {'АКЦИЯ':<12}{'ЦЕНА':>10}{'RSI':>6}{'ИМПУЛЬС':>9}{'БАЛЛ':>6}")
            print("  " + "-" * 46)
            for r in results[:TOP_SHOW]:
                mark = "🟢" if r["score"] >= 3 else ("⚪" if r["score"] >= 1 else "🔴")
                print(f"  {mark} {r['name']:<9}{r['price']:>10.2f}{r['rsi']:>6.0f}"
                      f"{r['momentum']:>+8.2f}%{r['score']:>6}")

            buys = [r for r in results if r["score"] >= 3]
            if buys:
                beep()
                b = buys[0]
                entry = b["price"]
                stop = entry * (1 - STOP_PCT)
                targ = entry * (1 + TARGET_PCT)
                risk_usd = DEPOSIT_USD * RISK_PCT
                position = min(risk_usd / STOP_PCT, DEPOSIT_USD)
                print(f"\n  ⭐ ЛУЧШИЙ СИГНАЛ: {b['name']} ({b['symbol']})")
                print(f"     ВХОД {entry:.2f} | СТОП {stop:.2f} (-{STOP_PCT*100:.1f}%) | ТЕЙК {targ:.2f} (+{TARGET_PCT*100:.1f}%)")
                print(f"     Размер позиции: ~${position:.2f}  | Риск/прибыль 1:2")
                print(f"     Плечо макс 5x — ликвидация только при падении ~20% (почти невозможно)")
            else:
                print("\n  ⚪ Сильных сигналов нет. Если рынок США закрыт — цены не двигаются.")
        except Exception as e:
            print(f"  Ошибка: {e}")
        print(f"  (обновление через {REFRESH_SEC}с)")
        time.sleep(REFRESH_SEC)


if __name__ == "__main__":
    main()
