"""
ЖУРНАЛ СДЕЛОК — дисциплина важнее сигналов.
Записывает твои реальные сделки в trades.csv, считает прибыль
с учётом комиссии Bybit и показывает статистику (винрейт, итог).

Запуск:  python journal.py

Команды в меню:
  1 — записать новую сделку
  2 — показать статистику
  3 — показать все сделки
  0 — выход
"""

import os
import csv
import sys
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

CSV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trades.csv")
FEE_ONE_WAY = 0.001  # комиссия спот тейкер за одну сторону
HEADER = ["дата", "пара", "сумма_usd", "цена_входа", "цена_выхода",
          "комиссия_usd", "результат_usd", "результат_pct"]


def ensure_file():
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(HEADER)


def ask_float(prompt):
    while True:
        try:
            return float(input(prompt).replace(",", "."))
        except ValueError:
            print("   Введи число, например 73.55")


def add_trade():
    pair  = input("  Пара (например SOLUSDT): ").strip().upper() or "SOLUSDT"
    usd   = ask_float("  Сколько $ вложил в сделку: ")
    entry = ask_float("  Цена входа (покупки): ")
    exit_ = ask_float("  Цена выхода (продажи): ")

    coins = usd / entry
    gross_out = coins * exit_
    fee = usd * FEE_ONE_WAY + gross_out * FEE_ONE_WAY  # комиссия на вход и на выход
    result = gross_out - usd - fee
    result_pct = result / usd * 100

    with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M"), pair, f"{usd:.2f}",
            f"{entry:.6f}", f"{exit_:.6f}", f"{fee:.4f}",
            f"{result:.4f}", f"{result_pct:.2f}",
        ])

    mark = "✅ ПЛЮС" if result > 0 else "❌ МИНУС"
    print(f"\n  {mark}: {result:+.2f}$ ({result_pct:+.2f}%)  | комиссия съела ${fee:.2f}")
    if result <= 0:
        print("  Это нормально — даже у профи 40% сделок в минус. Главное держать стопы.")


def show_stats():
    ensure_file()
    rows = list(csv.DictReader(open(CSV_FILE, encoding="utf-8")))
    if not rows:
        print("  Сделок пока нет.")
        return
    total = sum(float(r["результат_usd"]) for r in rows)
    fees  = sum(float(r["комиссия_usd"]) for r in rows)
    wins  = [r for r in rows if float(r["результат_usd"]) > 0]
    n = len(rows)
    winrate = len(wins) / n * 100

    print("\n  " + "=" * 40)
    print(f"  Всего сделок:      {n}")
    print(f"  В плюс / в минус:  {len(wins)} / {n - len(wins)}")
    print(f"  Винрейт:           {winrate:.0f}%")
    print(f"  Отдано комиссий:   ${fees:.2f}")
    print(f"  ИТОГ:              {total:+.2f}$")
    print("  " + "=" * 40)
    if total > 0:
        print("  В плюсе — но не расслабляйся, дисциплина важнее одной серии.")
    else:
        print("  В минусе — пересмотри: режешь ли убытки быстро, не жадничаешь ли с прибылью?")


def show_all():
    ensure_file()
    rows = list(csv.DictReader(open(CSV_FILE, encoding="utf-8")))
    if not rows:
        print("  Сделок пока нет.")
        return
    print(f"\n  {'ДАТА':<17}{'ПАРА':<10}{'$':>7}{'РЕЗУЛЬТАТ':>12}{'%':>8}")
    print("  " + "-" * 52)
    for r in rows:
        res = float(r["результат_usd"])
        mark = "✅" if res > 0 else "❌"
        print(f"  {r['дата']:<17}{r['пара']:<10}{r['сумма_usd']:>7}"
              f"{mark}{res:>+9.2f}{float(r['результат_pct']):>+8.2f}")


def main():
    ensure_file()
    print("=" * 44)
    print("  ЖУРНАЛ СДЕЛОК  |  файл: trades.csv")
    print("=" * 44)
    while True:
        print("\n  1 — записать сделку")
        print("  2 — статистика")
        print("  3 — все сделки")
        print("  0 — выход")
        choice = input("  > ").strip()
        if choice == "1":
            add_trade()
        elif choice == "2":
            show_stats()
        elif choice == "3":
            show_all()
        elif choice == "0":
            print("  Удачи. Дисциплина > эмоции.")
            break
        else:
            print("  Не понял. Введи 1, 2, 3 или 0.")


if __name__ == "__main__":
    main()
