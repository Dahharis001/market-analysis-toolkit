"""
СКАНЕР всех USDT-пар (спот, Bybit).
Тянет ПУБЛИЧНЫЕ данные — API-ключ НЕ нужен. Ничего не покупает.
Находит пары с сигналом на покупку и ранжирует их по силе.

Запуск:  python scanner.py
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
INTERVAL       = "5"        # таймфрейм свечей (минуты)
DEPOSIT_USD    = 120.0      # депозит на споте (крипта)
FEE_ONE_WAY    = 0.001      # комиссия спот тейкер за одну сторону
REFRESH_SEC    = 60         # пауза между полными сканами (сек)
MIN_TURNOVER   = 5_000_000  # мин. оборот за 24ч в USDT (фильтр ликвидности)
TOP_SHOW       = 10         # сколько лучших показывать

RISK_PCT       = 0.02       # риск на сделку = 2% депозита (макс. убыток)
STOP_PCT       = 0.007      # стоп-лосс 0.7% ниже входа
TARGET_PCT     = 0.012      # тейк-профит 1.2% выше входа
# ---------------------------------------------

FEE_ROUND = FEE_ONE_WAY * 2
BREAKEVEN_PCT = FEE_ROUND * 100


def get_usdt_symbols():
    """Все USDT-пары спот, отфильтрованные по обороту, отсортированные по ликвидности."""
    url = "https://api.bybit.com/v5/market/tickers"
    rows = None
    for _ in range(4):
        try:
            r = requests.get(url, params={"category": "spot"}, timeout=15)
            r.raise_for_status()
            rows = r.json()["result"]["list"]
            break
        except Exception:
            time.sleep(2)
    if rows is None:
        raise RuntimeError("Не удалось получить список пар с Bybit")
    pairs = []
    for x in rows:
        sym = x["symbol"]
        if not sym.endswith("USDT"):
            continue
        try:
            turnover = float(x["turnover24h"])
        except (KeyError, ValueError):
            continue
        if turnover >= MIN_TURNOVER:
            pairs.append((sym, turnover))
    pairs.sort(key=lambda p: p[1], reverse=True)
    return [p[0] for p in pairs]


def get_klines(symbol, interval, limit=200):
    url = "https://api.bybit.com/v5/market/kline"
    params = {"category": "spot", "symbol": symbol, "interval": interval, "limit": limit}
    for _ in range(3):
        try:
            r = requests.get(url, params=params, timeout=15)
            r.raise_for_status()
            return list(reversed(r.json()["result"]["list"]))
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
    data = get_klines(symbol, INTERVAL)
    if not data or len(data) < 30:
        return None
    closes  = [float(c[4]) for c in data]
    volumes = [float(c[5]) for c in data]
    price = closes[-1]

    e9, e21 = ema(closes, 9), ema(closes, 21)
    r = rsi(closes, 14)
    vol_now = volumes[-1]
    vol_avg = sum(volumes[-20:]) / 20

    # волатильность за последние свечи (размах в %), чтобы движение перекрывало комиссию
    recent = closes[-12:]
    volat = (max(recent) - min(recent)) / price * 100

    score = 0
    if e9 > e21:                 score += 1   # тренд вверх
    if 45 < r < 65:              score += 1   # здоровый RSI
    if vol_now > vol_avg * 1.3:  score += 1   # всплеск объёма
    if volat > BREAKEVEN_PCT * 3: score += 1  # хватает движения перекрыть комиссию
    if r > 78:                   score -= 2   # перекупленность — опасно
    if e9 < e21:                 score -= 1   # тренд вниз

    return {"symbol": symbol, "price": price, "rsi": r,
            "volat": volat, "score": score, "up": e9 > e21}


def scan():
    symbols = get_usdt_symbols()
    print(f"  Ликвидных USDT-пар к сканированию: {len(symbols)}")
    results = []
    for i, sym in enumerate(symbols, 1):
        res = score_pair(sym)
        if res:
            results.append(res)
        if i % 25 == 0:
            print(f"   ...просканировано {i}/{len(symbols)}")
    results.sort(key=lambda x: (x["score"], x["volat"]), reverse=True)
    return results


def main():
    print("=" * 64)
    print(f"  СКАНЕР USDT-ПАР  ({INTERVAL}-мин)  | Депозит ${DEPOSIT_USD:.0f}")
    print(f"  Комиссия за круг {BREAKEVEN_PCT:.2f}% — цена должна двигаться больше неё")
    print("  НЕ финансовый совет. Решение и риск — твои.")
    print("=" * 64)

    while True:
        try:
            t0 = time.time()
            results = scan()
            buys = [r for r in results if r["score"] >= 3]

            print(f"\n[{time.strftime('%H:%M:%S')}]  ТОП кандидатов на покупку:")
            print(f"  {'ПАРА':<14}{'ЦЕНА':>12}{'RSI':>6}{'ДВИЖ%':>8}{'БАЛЛ':>6}")
            print("  " + "-" * 46)
            for r in results[:TOP_SHOW]:
                mark = "🟢" if r["score"] >= 3 else ("⚪" if r["score"] >= 1 else "🔴")
                print(f"  {mark} {r['symbol']:<11}{r['price']:>12.5f}{r['rsi']:>6.0f}"
                      f"{r['volat']:>7.2f}%{r['score']:>6}")

            if buys:
                beep()  # звук когда есть сильный сигнал
                best = buys[0]
                entry = best["price"]
                stop_price   = entry * (1 - STOP_PCT)
                target_price = entry * (1 + TARGET_PCT)

                # размер позиции: чтобы при стопе потерять не больше RISK_PCT депозита,
                # но не больше самого депозита
                risk_usd = DEPOSIT_USD * RISK_PCT
                pos_by_risk = risk_usd / STOP_PCT
                position = min(pos_by_risk, DEPOSIT_USD)

                # сколько реально потеряешь/заработаешь в $ (с учётом комиссии за круг)
                fee_round = position * FEE_ROUND
                loss_if_stop = position * STOP_PCT + fee_round
                gain_if_tp   = position * TARGET_PCT - fee_round

                print(f"\n  ⭐ ГОТОВЫЙ ПЛАН — {best['symbol']}")
                print(f"     ┌────────────────────────────────────────────")
                print(f"     │ ПОКУПКА по цене:   {entry:.5f}")
                print(f"     │ СТАВИШЬ:           ${position:.2f}")
                print(f"     │ СТОП-ЛОСС:         {stop_price:.5f}  (-{STOP_PCT*100:.1f}%)")
                print(f"     │ ТЕЙК-ПРОФИТ:       {target_price:.5f}  (+{TARGET_PCT*100:.1f}%)")
                print(f"     ├────────────────────────────────────────────")
                print(f"     │ Если стоп → потеря ~${loss_if_stop:.2f}")
                print(f"     │ Если тейк → прибыль ~${gain_if_tp:.2f}")
                print(f"     └────────────────────────────────────────────")
                print(f"     ⚠️ СТОП-ЛОСС ставь на Bybit СРАЗУ при покупке!")
            else:
                print("\n  ⚪ Сильных сигналов сейчас нет — лучшее действие ЖДАТЬ.")

            print(f"  (скан занял {time.time()-t0:.0f}с, следующий через {REFRESH_SEC}с)")
        except Exception as e:
            print(f"  Ошибка: {e}")
        time.sleep(REFRESH_SEC)


if __name__ == "__main__":
    main()
