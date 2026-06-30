"""
Алерт-инструмент для SOL/USDT (спот, Bybit).
Тянет ПУБЛИЧНЫЕ рыночные данные — API-ключ НЕ нужен и НЕ используется.
Ничего не покупает и не продаёт. Только даёт сигнал — решаешь ты.

Запуск:  python signal_tool.py
Выход:   Ctrl + C
"""

import sys
import time
import requests

# Принудительно UTF-8, чтобы Windows-консоль не падала на эмодзи
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# Звуковой сигнал (только Windows)
try:
    import winsound
    def beep():
        for f in (880, 1100, 1320):
            winsound.Beep(f, 150)
except Exception:
    def beep():
        print("\a", end="", flush=True)  # системный звук как запасной вариант

# ----------------- НАСТРОЙКИ -----------------
SYMBOL       = "SOLUSDT"   # пара
INTERVAL     = "5"         # таймфрейм свечи в минутах (5 = 5-минутки)
DEPOSIT_USD  = 240.0       # твой депозит
FEE_ONE_WAY  = 0.001       # комиссия спот тейкер ~0.1% за одну сторону
REFRESH_SEC  = 30          # как часто обновлять (сек)
# ---------------------------------------------

FEE_ROUND = FEE_ONE_WAY * 2          # комиссия за круг (вход+выход)
BREAKEVEN_PCT = FEE_ROUND * 100      # на сколько % должна вырасти цена, чтобы выйти в ноль


def get_klines(symbol, interval, limit=200):
    url = "https://api.bybit.com/v5/market/kline"
    params = {"category": "spot", "symbol": symbol, "interval": interval, "limit": limit}
    # до 4 попыток на случай разовых обрывов связи
    last_err = None
    for attempt in range(4):
        try:
            r = requests.get(url, params=params, timeout=15)
            r.raise_for_status()
            break
        except Exception as e:
            last_err = e
            time.sleep(2)
    else:
        raise last_err
    data = r.json()["result"]["list"]
    # Bybit отдаёт от новых к старым — разворачиваем в хронологию
    data = list(reversed(data))
    closes  = [float(c[4]) for c in data]
    volumes = [float(c[5]) for c in data]
    return closes, volumes


def ema(values, period):
    k = 2 / (period + 1)
    e = values[0]
    out = [e]
    for v in values[1:]:
        e = v * k + e * (1 - k)
        out.append(e)
    return out


def rsi(closes, period=14):
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def analyze():
    closes, volumes = get_klines(SYMBOL, INTERVAL)
    price = closes[-1]

    ema9  = ema(closes, 9)[-1]
    ema21 = ema(closes, 21)[-1]
    r = rsi(closes, 14)

    vol_now = volumes[-1]
    vol_avg = sum(volumes[-20:]) / 20
    vol_spike = vol_now > vol_avg * 1.3

    # --- логика сигнала (подтверждение по нескольким факторам) ---
    trend_up   = ema9 > ema21
    trend_down = ema9 < ema21

    score = 0
    reasons = []

    if trend_up:
        score += 1; reasons.append("тренд вверх (EMA9>EMA21)")
    if trend_down:
        score -= 1; reasons.append("тренд вниз (EMA9<EMA21)")

    if 40 < r < 65 and trend_up:
        score += 1; reasons.append(f"RSI здоровый ({r:.0f})")
    if r > 75:
        score -= 1; reasons.append(f"RSI перекуплен ({r:.0f}) — опасно покупать")
    if r < 30:
        reasons.append(f"RSI перепродан ({r:.0f}) — возможен отскок, но не лови нож")

    if vol_spike and trend_up:
        score += 1; reasons.append("всплеск объёма подтверждает движение")

    if score >= 2:
        signal = "🟢 СИГНАЛ НА ПОКУПКУ (рассмотри вход)"
    elif score <= -1:
        signal = "🔴 НЕ ПОКУПАТЬ (тренд/перекупленность против тебя)"
    else:
        signal = "⚪ ЖДАТЬ (чёткого сигнала нет — лучшая сделка та, которую не сделал)"

    return {
        "price": price, "ema9": ema9, "ema21": ema21, "rsi": r,
        "vol_now": vol_now, "vol_avg": vol_avg,
        "signal": signal, "reasons": reasons,
    }


def main():
    print("=" * 60)
    print(f"  АЛЕРТ-ИНСТРУМЕНТ  {SYMBOL}  ({INTERVAL}-мин свечи)")
    print(f"  Депозит: ${DEPOSIT_USD:.0f} | Комиссия за круг: {BREAKEVEN_PCT:.2f}%")
    print(f"  >>> Цена должна сдвинуться минимум на {BREAKEVEN_PCT:.2f}% чтобы выйти в НОЛЬ")
    print("  Это НЕ финансовый совет. Решение и риск — твои.")
    print("=" * 60)

    while True:
        try:
            a = analyze()
            tp = a["price"] * (1 + BREAKEVEN_PCT / 100 + 0.005)  # +0.5% сверх комиссии
            sl = a["price"] * (1 - 0.007)                        # стоп -0.7%
            print(f"\n[{time.strftime('%H:%M:%S')}]  Цена: {a['price']:.3f}")
            print(f"  EMA9: {a['ema9']:.3f} | EMA21: {a['ema21']:.3f} | RSI: {a['rsi']:.0f}")
            print(f"  Объём: {a['vol_now']:.0f} (средний {a['vol_avg']:.0f})")
            print(f"  {a['signal']}")
            for why in a["reasons"]:
                print(f"     • {why}")
            if "ПОКУПКУ" in a["signal"]:
                beep()  # звуковой сигнал
                print(f"  📌 Если входишь: цель ~{tp:.3f} (+{BREAKEVEN_PCT+0.5:.1f}%), стоп ~{sl:.3f} (-0.7%)")
                print(f"     Рискуй НЕ больше ${DEPOSIT_USD*0.02:.2f} (2% депозита) на сделку!")
        except Exception as e:
            print(f"  Ошибка: {e}")
        time.sleep(REFRESH_SEC)


if __name__ == "__main__":
    main()
