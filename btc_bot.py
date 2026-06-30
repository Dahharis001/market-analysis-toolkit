#!/usr/bin/env python3
import sys
import time
import datetime
import requests

LOG_FILE = "btc.log"

def log(msg):
    line = f"{msg}\n"
    sys.stdout.write(line)
    sys.stdout.flush()
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line)

def fetch_polymarket():
    url = "https://gamma-api.polymarket.com/events"
    params = {
        "series_slug": "btc-up-or-down-5m",
        "limit": 50,
        "order": "endDate",
        "ascending": "false",
    }
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    events = resp.json()

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    cutoff = now_utc + datetime.timedelta(seconds=400)

    candidates = []
    for event in events:
        markets = event.get("markets", [])
        end_date_str = event.get("endDate") or event.get("end_date_iso") or ""
        # parse endDate
        try:
            end_dt = datetime.datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
        except Exception:
            continue
        if end_dt <= now_utc or end_dt > cutoff:
            continue

        for market in markets:
            ltp = market.get("lastTradePrice")
            try:
                ltp = float(ltp)
            except (TypeError, ValueError):
                continue
            if not (0 < ltp < 1):
                continue
            candidates.append((event, market, end_dt))

    if not candidates:
        return None

    # pick soonest ending
    candidates.sort(key=lambda x: x[2])
    event, market, end_dt = candidates[0]

    outcome = market.get("outcome", "").upper()
    metadata = event.get("eventMetadata") or event.get("metadata") or {}
    price_to_beat = metadata.get("priceToBeat") or metadata.get("price_to_beat")

    # gather all markets for this event to find UP and DOWN
    all_markets = event.get("markets", [])
    up_prob = down_prob = None
    up_price = down_price = None

    for m in all_markets:
        o = (m.get("outcome") or "").upper()
        try:
            p = float(m.get("lastTradePrice", 0))
        except (TypeError, ValueError):
            p = None
        if o == "UP":
            up_prob = p
            up_price = p
        elif o == "DOWN":
            down_prob = p
            down_price = p

    return {
        "end_dt": end_dt,
        "price_to_beat": price_to_beat,
        "up_prob": up_prob,
        "down_prob": down_prob,
    }

def fetch_binance():
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": "BTCUSDT", "interval": "1m", "limit": 15}
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    klines = resp.json()
    closes = [float(k[4]) for k in klines]
    volumes = [float(k[5]) for k in klines]
    return closes, volumes

def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calc_signal(closes, volumes):
    rsi = calc_rsi(closes)
    momentum = closes[-1] - closes[-5]
    vol_avg = sum(volumes[-5:]) / 5
    vol_spike = volumes[-1] > vol_avg * 1.5

    score = 0
    details = []

    if rsi > 55:
        score += 2
        details.append(f"RSI={rsi:.1f}(+2)")
    elif rsi < 45:
        score -= 2
        details.append(f"RSI={rsi:.1f}(-2)")
    else:
        details.append(f"RSI={rsi:.1f}(0)")

    if momentum > 15:
        score += 2
        details.append(f"mom={momentum:.1f}(+2)")
    elif momentum < -15:
        score -= 2
        details.append(f"mom={momentum:.1f}(-2)")
    else:
        details.append(f"mom={momentum:.1f}(0)")

    if vol_spike and momentum > 0:
        score += 1
        details.append("vol-spike(+1)")
    elif vol_spike and momentum < 0:
        score -= 1
        details.append("vol-spike(-1)")
    else:
        details.append("vol(0)")

    if score >= 3:
        label = "STRONG UP"
    elif score >= 1:
        label = "WEAK UP"
    elif score <= -3:
        label = "STRONG DOWN"
    elif score <= -1:
        label = "WEAK DOWN"
    else:
        label = "UNCLEAR"

    return label, score, details, rsi, momentum

def multiplier(prob):
    if prob and prob > 0:
        return f"{1/prob:.2f}x"
    return "N/A"

def run():
    log("=== BTC 5-min Polymarket Bot started ===")
    while True:
        try:
            now_utc = datetime.datetime.now(datetime.timezone.utc)

            poly = fetch_polymarket()
            closes, volumes = fetch_binance()

            btc_price = closes[-1]
            signal, score, details, rsi, momentum = calc_signal(closes, volumes)

            log("-" * 60)
            log(f"UTC: {now_utc.strftime('%Y-%m-%d %H:%M:%S')}")
            log(f"BTC Price: ${btc_price:,.2f}")

            if poly:
                end_dt = poly["end_dt"]
                secs_left = int((end_dt - now_utc).total_seconds())
                mm = secs_left // 60
                ss = secs_left % 60
                ptb = poly["price_to_beat"]
                up_p = poly["up_prob"]
                dn_p = poly["down_prob"]

                log(f"Target (priceToBeat): {f'${float(ptb):,.2f}' if ptb else 'N/A'}")
                log(f"Time Remaining: {mm:02d}:{ss:02d}")
                log(f"UP  prob={f'{up_p:.3f}' if up_p else 'N/A'}  mult={multiplier(up_p)}")
                log(f"DOWN prob={f'{dn_p:.3f}' if dn_p else 'N/A'}  mult={multiplier(dn_p)}")
            else:
                log("No active market found within 400s window")

            log(f"Signal: {signal} (score={score:+d})  [{', '.join(details)}]")

        except Exception as e:
            log(f"ERROR: {e}")

        time.sleep(15)

if __name__ == "__main__":
    run()
