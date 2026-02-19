import argparse
import os
import time

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

# DexScreenerのpriceChangeフィールドに対応する時間足
TIMEFRAME_MAP = {
    5: "m5",
    60: "h1",
    360: "h6",
    1440: "h24",
}

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

def get_token_data(tokens):
    """全トークンの価格と変動率を一括取得する。"""
    mints = list(tokens.values())
    url = f"https://api.dexscreener.com/tokens/v1/solana/{','.join(mints)}"
    r = requests.get(url, timeout=10)
    data = r.json()

    if not isinstance(data, list):
        if DEBUG:
            print(f"[DEBUG] API response: {data}")
        return {}

    tf_key = TIMEFRAME_MAP.get(CANDLE_MINUTES, "h1")
    result = {}
    for pair in data:
        addr = pair.get("baseToken", {}).get("address")
        if addr and addr in mints and addr not in result:
            price_usd = pair.get("priceUsd")
            change_pct = pair.get("priceChange", {}).get(tf_key)
            if price_usd and change_pct is not None:
                result[addr] = {
                    "price": float(price_usd),
                    "change": float(change_pct) / 100,
                }

    if DEBUG:
        for symbol, mint in tokens.items():
            d = result.get(mint)
            if d:
                print(f"[DEBUG] {symbol}: {d['price']:.10f} USD (変動: {d['change']*100:+.2f}%)")
            else:
                print(f"[DEBUG] {symbol}: データ取得できず")

    return result

# ======================
# メイン監視ロジック
# ======================

def check_and_alert(symbol, price, change, alerted):
    """変動率が閾値を超えていればアラートを送信する（同一足内での重複防止付き）。"""
    if change < PUMP_THRESHOLD:
        alerted.pop(symbol, None)
        return

    now = time.time()
    last_alert = alerted.get(symbol, 0)
    if now - last_alert < CANDLE_MINUTES * 60:
        return

    msg = (
        f"\n{symbol} 急騰！\n"
        f"価格: {price:.6f}\n"
        f"変動率: {change*100:+.2f}%"
    )
    print(msg)
    notify_line(msg)
    alerted[symbol] = now


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

    tf_key = TIMEFRAME_MAP.get(CANDLE_MINUTES)
    if tf_key is None:
        supported = ", ".join(str(m) for m in sorted(TIMEFRAME_MAP))
        print(f"[ERROR] CANDLE_MINUTES={CANDLE_MINUTES} は未対応です（対応: {supported}）")
        return

    alerted = {}  # symbol -> 最後にアラートした時刻

    if DEBUG:
        print("[DEBUG] デバッグモードで起動")
        print(f"[DEBUG] CHECK_INTERVAL={CHECK_INTERVAL}秒, 時間足={tf_key}, PUMP_THRESHOLD={PUMP_THRESHOLD*100:.0f}%")
    else:
        print(f"本番モード: {CANDLE_MINUTES}分足 / 閾値 {PUMP_THRESHOLD*100:.0f}%")

    print("Solana Pump Watcher 起動しました")

    while True:
        try:
            token_data = get_token_data(TOKENS)
        except Exception as e:
            print(f"[ERROR] データ取得失敗: {e}")
            time.sleep(CHECK_INTERVAL)
            continue

        for symbol, mint in TOKENS.items():
            d = token_data.get(mint)
            if d is None:
                continue
            check_and_alert(symbol, d["price"], d["change"], alerted)

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
