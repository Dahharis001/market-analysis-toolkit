"""
СКАНЕР ВАЛЮТНОГО РЫНКА (форекс / TradFi).
Данные — Yahoo Finance (бесплатно, без ключа). Ничего не покупает.
Находит валютные пары с сигналом и даёт готовый план.

Запуск:  python forex_scanner.py
Выход:   Ctrl + C

ВАЖНО: форекс обычно торгуется С ПЛЕЧОМ. Плечо умножает и прибыль, и убыток.
Стоп-лосс тут не пожелание, а вопрос выживания депозита.
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
INTERVAL    = "5m"      # таймфрейм (Yahoo: 1m,5m,15m,30m,1h)
RANGE       = "1d"      # сколько истории грузить
DEPOSIT_USD = 120.0     # депозит на форекс
SPREAD_PCT  = 0.0002    # спред/комиссия за круг (~0.02% для мажоров; уточни у брокера)
REFRESH_SEC = 60        # пауза между сканами
TOP_SHOW    = 10

RISK_PCT    = 0.02      # риск на сделку = 2% депозита
STOP_PCT    = 0.0020    # стоп-лосс 0.20% от цены
TARGET_PCT  = 0.0035    # тейк-профит 0.35%

# Главные валютные пары (символы Yahoo). Можешь добавить/убрать.
PAIRS = [
    "EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X", "USDCHF=X",
    "USDCAD=X", "NZDUSD=X", "EURGBP=X", "EURJPY=X", "GBPJPY=X",
    "EURCHF=X", "AUDJPY=X",
]
# ---------------------------------------------

HEADERS = {"User-Agent": "Mozilla/5.0"}


def get_closes(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"interval": INTERVAL, "range": RANGE}
    for _ in range(3):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=15)
            r.raise_for_status()
            d = r.json()["chart"]["result"][0]
            raw = d["indicators"]["quote"][0]["close"]
            closes = [c for c in raw if c is not None]
            return closes
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


def score_pair(symbol):
    closes = get_closes(symbol)
    if not closes or len(closes) < 30:
        return None
    price = closes[-1]
    e9, e21 = ema(closes, 9), ema(closes, 21)
    r = rsi(closes, 14)
    recent = closes[-12:]
    volat = (max(recent) - min(recent)) / price * 100  # размах в %

    score = 0
    if e9 > e21:                       score += 1   # тренд вверх
    if 45 < r < 65:                    score += 1   # здоровый RSI
    if volat > (SPREAD_PCT * 100 * 4): score += 1   # хватает движения перекрыть спред
    if abs(e9 - e21) / price > 0.0005: score += 1   # тренд выраженный
    if r > 78:                         score -= 2   # перекупленность
    if e9 < e21:                       score -= 1   # тренд вниз

    name = symbol.replace("=X", "")
    name = name[:3] + "/" + name[3:]
    return {"symbol": name, "raw": symbol, "price": price,
            "rsi": r, "volat": volat, "score": score, "up": e9 > e21}


def scan():
    results = []
    for sym in PAIRS:
        res = score_pair(sym)
        if res:
            results.append(res)
    results.sort(key=lambda x: (x["score"], x["volat"]), reverse=True)
    return results


def digits(price):
    # JPY-пары котируются с 3 знаками, остальные с 5
    return 3 if price > 10 else 5


def main():
    print("=" * 64)
    print(f"  ВАЛЮТНЫЙ СКАНЕР (форекс/TradFi)  | Депозит ${DEPOSIT_USD:.0f}")
    print(f"  Источник: Yahoo Finance | Спред за круг ~{SPREAD_PCT*100:.2f}%")
    print("  ВНИМАНИЕ: форекс часто с ПЛЕЧОМ — стоп-лосс обязателен!")
    print("  НЕ финансовый совет. Решение и риск — твои.")
    print("=" * 64)

    while True:
        try:
            t0 = time.time()
            results = scan()
            buys = [r for r in results if r["score"] >= 3]

            print(f"\n[{time.strftime('%H:%M:%S')}]  Валютные пары:")
            print(f"  {'ПАРА':<12}{'ЦЕНА':>12}{'RSI':>6}{'ДВИЖ%':>8}{'БАЛЛ':>6}")
            print("  " + "-" * 44)
            for r in results[:TOP_SHOW]:
                mark = "🟢" if r["score"] >= 3 else ("⚪" if r["score"] >= 1 else "🔴")
                dg = digits(r["price"])
                print(f"  {mark} {r['symbol']:<9}{r['price']:>12.{dg}f}{r['rsi']:>6.0f}"
                      f"{r['volat']:>7.2f}%{r['score']:>6}")

            if buys:
                beep()
                best = buys[0]
                entry = best["price"]
                dg = digits(entry)
                stop_price   = entry * (1 - STOP_PCT)
                target_price = entry * (1 + TARGET_PCT)
                risk_usd = DEPOSIT_USD * RISK_PCT
                position = min(risk_usd / STOP_PCT, DEPOSIT_USD)
                fee_round = position * SPREAD_PCT * 2
                loss_if_stop = position * STOP_PCT + fee_round
                gain_if_tp   = position * TARGET_PCT - fee_round

                print(f"\n  ⭐ ГОТОВЫЙ ПЛАН — {best['symbol']}")
                print(f"     ┌────────────────────────────────────────────")
                print(f"     │ ПОКУПКА по цене:   {entry:.{dg}f}")
                print(f"     │ СТАВИШЬ (без плеча): ${position:.2f}")
                print(f"     │ СТОП-ЛОСС:         {stop_price:.{dg}f}  (-{STOP_PCT*100:.2f}%)")
                print(f"     │ ТЕЙК-ПРОФИТ:       {target_price:.{dg}f}  (+{TARGET_PCT*100:.2f}%)")
                print(f"     ├────────────────────────────────────────────")
                print(f"     │ Если стоп → потеря ~${loss_if_stop:.2f}")
                print(f"     │ Если тейк → прибыль ~${gain_if_tp:.2f}")
                print(f"     └────────────────────────────────────────────")
                print(f"     ⚠️ С ПЛЕЧОМ цифры умножаются! Плечо x10 → и риск, и прибыль x10.")
            else:
                print("\n  ⚪ Сильных сигналов сейчас нет — лучшее действие ЖДАТЬ.")

            print(f"  (скан {time.time()-t0:.0f}с, следующий через {REFRESH_SEC}с)")
        except Exception as e:
            print(f"  Ошибка: {e}")
        time.sleep(REFRESH_SEC)


if __name__ == "__main__":
    main()
