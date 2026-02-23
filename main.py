from dotenv import load_dotenv
load_dotenv()

import argparse
import os
import time
from datetime import datetime

import requests

# ======================
# 設定
# ======================

DEBUG = False

UID = os.getenv("UID", "")
LINE_TOKEN = os.getenv("LINE_TOKEN", "")

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

    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Authorization": f"Bearer {LINE_TOKEN}"
    }
    json={
        "to": UID,
        "messages": [{
                        "type": "text",
                        "text": message
                    }]
    }
    try:
        r = requests.post(url, headers=headers, json=json)
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

    prices = {}
    for pair in data:
        addr = pair.get("baseToken", {}).get("address")
        if addr and addr in mints and addr not in prices:
            price_usd = pair.get("priceUsd")
            if price_usd:
                prices[addr] = float(price_usd)
    return prices

# ======================
# メイン監視ロジック
# ======================

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

    if DEBUG:
        print("[DEBUG] デバッグモードで起動")
        print(f"[DEBUG] CHECK_INTERVAL={CHECK_INTERVAL}秒, CANDLE_MINUTES={CANDLE_MINUTES}, PUMP_THRESHOLD={PUMP_THRESHOLD*100:.0f}%")
    else:
        print(f"本番モード: {CANDLE_MINUTES}分足 / 閾値 {PUMP_THRESHOLD*100:.0f}%")

    print("Solana Pump Watcher 起動しました")

    prev_prices = {}  # mint -> 前回の境界での価格
    next_boundary = 0  # 次の足の境界時刻（unix timestamp）

    while True:
        now = time.time()

        # 足の境界を超えたら価格を取得して前回と比較
        if now >= next_boundary:
            try:
                prices = get_prices(TOKENS)
            except Exception as e:
                print(f"[ERROR] 価格取得失敗: {e}")
                time.sleep(CHECK_INTERVAL)
                continue

            if DEBUG:
                for symbol, mint in TOKENS.items():
                    p = prices.get(mint)
                    if p:
                        print(f"[DEBUG] {symbol}: {p:.10f} USD")

            # 前回の価格がある場合、比較してアラート判定
            if prev_prices:
                for symbol, mint in TOKENS.items():
                    curr = prices.get(mint)
                    prev = prev_prices.get(mint)
                    if curr is None or prev is None:
                        continue
                    change = (curr - prev) / prev
                    if change >= PUMP_THRESHOLD:
                        msg = (
                            f"\n{symbol} 急騰！\n"
                            f"前回: {prev:.6f} → 現在: {curr:.6f}\n"
                            f"変動率: {change*100:+.2f}%"
                        )
                        print(msg)
                        notify_line(msg)

            prev_prices = prices

            # 次の足の境界 + 5秒バッファ
            candle_seconds = CANDLE_MINUTES * 60
            next_boundary = ((now // candle_seconds) + 1) * candle_seconds + 5

            boundary_dt = datetime.fromtimestamp(next_boundary)
            print(f"次回チェック: {boundary_dt.strftime('%H:%M:%S')}")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
