# 📊 Market Analysis Toolkit

A collection of Python tools for real-time market analysis across **crypto, forex, metals, and stocks**.
Each tool pulls live public market data, calculates professional technical indicators, and generates
trade signals with risk-managed entry plans.

> ⚠️ Educational project. Not financial advice. These tools analyze data and produce signals —
> they do **not** place trades. All trading decisions and risks belong to the user.

---

## ✨ Features

- **Multi-market support** — crypto (Bybit), forex, metals, indices, and US stocks
- **Live data** — pulls public market data from Bybit and Yahoo Finance APIs (no API key required)
- **Professional indicators** — EMA (9/21/50), RSI, MACD, Bollinger Bands, ATR
- **Multi-timeframe analysis** — combines 15m, 1h, and daily trends to filter false signals
- **Risk management** — every signal includes ATR-based stop-loss, take-profit, and position sizing
- **Fee-aware** — calculations account for spread and commission so signals reflect real net profit
- **Sound alerts** — audible notification when a strong signal appears

---

## 🛠 Tools

| File | Market | Description |
|------|--------|-------------|
| `scanner.py` | Crypto (Bybit spot) | Scans all liquid USDT pairs, ranks the strongest buy setups |
| `signal_tool.py` | Single crypto pair | Detailed live monitoring of one pair with entry plan |
| `stock_scanner.py` | US stocks | Scans AAPL, NVDA, MSFT, GOOGL, META, AMZN, TSLA |
| `forex_scanner.py` | Forex | Scans major currency pairs |
| `tradfi_scanner.py` | TradFi overview | Forex + indices + commodities in one view |
| `gold_scanner.py` | Gold (XAU/USD) | Pro multi-timeframe analysis |
| `silver_scanner.py` | Silver (XAG/USD) | Pro multi-timeframe analysis |
| `journal.py` | Trade journal | Logs trades, computes P&L after fees, tracks win rate |

---

## 🚀 Usage

```bash
# Install dependencies
pip install -r requirements.txt

# Run a scanner
python scanner.py          # crypto
python stock_scanner.py    # US stocks
python silver_scanner.py   # silver, full pro analysis
python journal.py          # trade journal
```

Press `Ctrl + C` to stop. Settings (deposit, risk %, timeframe) are at the top of each file.

---

## 🧮 Tech

- **Python 3.10+**
- `requests` for API calls
- All indicators (EMA, RSI, MACD, Bollinger, ATR) implemented from scratch — no TA libraries

---

## 📈 Example output

```
SILVER (XAG/USD)   Price: 60.130

[15m ] trend UP    RSI 58   MACD bearish   score +2
[1h  ] trend UP    RSI 60   MACD bullish   score +4
[1d  ] trend DOWN  RSI 35   MACD bearish   score -3

VERDICT: +3  ->  WEAK BULLISH (caution)

⭐ ENTRY PLAN (ATR-based stop):
   Entry: 60.130 | Stop: 59.874 (-0.43%) | Target: 60.557 (+0.71%)
   Risk/Reward: 1 : 1.2
```

---

## 👤 Author

Built as a learning project while exploring market data APIs and technical analysis in Python.
