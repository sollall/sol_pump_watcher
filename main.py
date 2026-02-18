import argparse
import os
import time
from datetime import datetime

import requests

# ======================
# 設定
# ======================

DEBUG = False

LINE_TOKEN = os.environ.get("LINE_NOTIFY_TOKEN", "")

# 監視するトークン
TOKENS = {
    "BONK": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
    "WIF": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
    "POPCAT": "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr",
    "MEW": "MEW1gQWJ3nEXg2qgERiKu7FAFj79PHvQVREQUzScPP5",
    "BOME": "ukHH6c7mMyiWCf1b9pnWe25TSpkDDt3H5pQZgZ74J82",
    "MYRO": "HhJpBhRRn4g56VsyLuT8DL5Bv31HkXqsrahTTUCZeZg4",
    "SAMO": "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
    "PONKE": "5z3EqYQo9HiCEs3R84RCDMu2n7anpDMxRhdK8PSWmrRC",
}

CHECK_INTERVAL = 30  # 秒（デバッグ時は10秒に短縮）
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
# 価格取得（DexScreener API）
# ======================

def get_prices(tokens):
    """全トークンの価格を一括取得する。mintアドレス→USD価格の辞書を返す。"""
    mints = list(tokens.values())
    url = f"https://api.dexscreener.com/tokens/v1/solana/{','.join(mints)}"
    r = requests.get(url, timeout=10)
    data = r.json()

    if not isinstance(data, list):
        if DEBUG:
            print(f"[DEBUG] API response: {data}")
        return {}

    # mintアドレスごとに最初のペア（最も流動性が高い）の価格を取得
    prices = {}
    for pair in data:
        addr = pair.get("baseToken", {}).get("address")
        if addr and addr in mints and addr not in prices:
            price_usd = pair.get("priceUsd")
            if price_usd:
                prices[addr] = float(price_usd)

    if DEBUG:
        for symbol, mint in tokens.items():
            if mint in prices:
                print(f"[DEBUG] {symbol}: {prices[mint]:.10f} USD")
            else:
                print(f"[DEBUG] {symbol}: 価格取得できず")

    return prices

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


def parse_args():
    parser = argparse.ArgumentParser(description="Solana Pump Watcher")
    parser.add_argument("--debug", action="store_true", help="デバッグモードで起動")
    return parser.parse_args()


def main():
    global DEBUG, CHECK_INTERVAL
    args = parse_args()
    DEBUG = args.debug or os.environ.get("DEBUG", "false").lower() in ("true", "1", "yes")
    if DEBUG:
        CHECK_INTERVAL = 10

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

        try:
            prices = get_prices(TOKENS)
        except Exception as e:
            print(f"[ERROR] 価格取得失敗: {e}")
            time.sleep(CHECK_INTERVAL)
            continue

        for symbol, mint in TOKENS.items():
            price = prices.get(mint)
            if price is None:
                continue

            if DEBUG:
                # デバッグ: 毎サイクルで即時アラート判定
                check_and_alert(symbol, price, base_prices)
                base_prices[symbol] = price
            else:
                # 本番: N分足の更新タイミングでアラート判定
                if current_candle != last_candle:
                    check_and_alert(symbol, price, base_prices)
                    base_prices[symbol] = price
                elif symbol not in base_prices:
                    base_prices[symbol] = price

        if not DEBUG and current_candle != last_candle:
            print(f"{CANDLE_MINUTES}分足更新: {last_candle.strftime('%H:%M')} → {current_candle.strftime('%H:%M')}")
            last_candle = current_candle

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
