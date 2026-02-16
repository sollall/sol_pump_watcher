import os
import time
from datetime import datetime

import requests

# ======================
# 設定
# ======================

DEBUG = os.environ.get("DEBUG", "false").lower() in ("true", "1", "yes")

LINE_TOKEN = os.environ.get("LINE_NOTIFY_TOKEN", "")

# 監視するトークン（例：BONK）
TOKENS = {
    "BONK": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
}

CHECK_INTERVAL = 10 if DEBUG else 30  # 秒（デバッグ時は短縮）
CANDLE_MINUTES = int(os.environ.get("CANDLE_MINUTES", "60"))  # N分足（デフォルト60分）
PUMP_THRESHOLD = 0.10  # 10%

# ======================
# LINE通知
# ======================

def notify_line(message):
    if DEBUG:
        print(f"[DEBUG] LINE通知（送信スキップ）: {message}")
        return

    if not LINE_TOKEN:
        print("[WARN] LINE_NOTIFY_TOKEN が未設定です")
        return

    url = "https://notify-api.line.me/api/notify"
    headers = {
        "Authorization": f"Bearer {LINE_TOKEN}"
    }
    data = {"message": message}
    try:
        r = requests.post(url, headers=headers, data=data)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"[ERROR] LINE通知に失敗: {e}")

# ======================
# 価格取得（Jupiter Price API V3）
# ======================

def get_price(mint):
    url = "https://api.jup.ag/price/v3"
    params = {"ids": mint}
    r = requests.get(url, params=params, timeout=10)
    data = r.json()

    if mint not in data:
        return None

    return data[mint]["usdPrice"]

# ======================
# メイン監視ロジック
# ======================

def get_candle_time(dt):
    """現在時刻をN分足の区切りに切り捨てる。"""
    total_minutes = dt.hour * 60 + dt.minute
    candle_start = (total_minutes // CANDLE_MINUTES) * CANDLE_MINUTES
    return dt.replace(hour=candle_start // 60, minute=candle_start % 60, second=0, microsecond=0)


def check_and_alert(symbol, price, base_prices):
    """基準価格と比較し、閾値を超えていればアラートを送信する。"""
    if symbol not in base_prices:
        return
    prev = base_prices[symbol]
    change = (price - prev) / prev
    if change >= PUMP_THRESHOLD:
        msg = (
            f"\n{symbol} 急騰！\n"
            f"価格: {price:.6f}\n"
            f"変動率: +{change*100:.2f}%"
        )
        print(msg)
        notify_line(msg)


def main():
    base_prices = {}
    last_candle = get_candle_time(datetime.now())

    if DEBUG:
        print("[DEBUG] デバッグモードで起動")
        print(f"[DEBUG] CHECK_INTERVAL={CHECK_INTERVAL}秒, PUMP_THRESHOLD={PUMP_THRESHOLD*100:.0f}%")
    else:
        print(f"本番モード: {CANDLE_MINUTES}分足の更新タイミングでアラート判定")

    print("Solana Pump Watcher 起動しました")

    while True:
        now = datetime.now()
        current_candle = get_candle_time(now)

        for symbol, mint in TOKENS.items():
            try:
                price = get_price(mint)
                if price is None:
                    if DEBUG:
                        print(f"[DEBUG] {symbol}: 価格取得できず")
                    continue

                if DEBUG:
                    # デバッグ: 毎サイクルで即時アラート判定
                    print(f"[DEBUG] {symbol}: {price:.10f} USD")
                    check_and_alert(symbol, price, base_prices)
                    base_prices[symbol] = price
                else:
                    # 本番: N分足の更新タイミングでアラート判定
                    if current_candle != last_candle:
                        check_and_alert(symbol, price, base_prices)
                        base_prices[symbol] = price
                    elif symbol not in base_prices:
                        base_prices[symbol] = price

            except Exception as e:
                print(f"[ERROR] {symbol}: {e}")

        if not DEBUG and current_candle != last_candle:
            print(f"{CANDLE_MINUTES}分足更新: {last_candle.strftime('%H:%M')} → {current_candle.strftime('%H:%M')}")
            last_candle = current_candle

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
