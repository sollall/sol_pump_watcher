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

# GeckoTerminal OHLCV timeframe: CANDLE_MINUTES -> (endpoint_timeframe, aggregate)
TIMEFRAME_MAP = {
    5: ("minute", 5),
    15: ("minute", 15),
    60: ("hour", 1),
    240: ("hour", 4),
    360: ("hour", 6),
    1440: ("day", 1),
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
# GeckoTerminal API
# ======================

GECKOTERMINAL_BASE = "https://api.geckoterminal.com/api/v2"


def _gecko_get(url, params=None, max_retries=3):
    """GeckoTerminal APIを429リトライ付きで呼び出す。"""
    for attempt in range(max_retries):
        r = requests.get(url, params=params, timeout=10)
        if r.status_code == 429:
            wait = 2 ** (attempt + 1)  # 2, 4, 8秒
            print(f"[WARN] Rate limited, {wait}秒待機中...")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r.json()
    raise Exception(f"Rate limit: {max_retries}回リトライ後も429")


def resolve_pools(tokens):
    """各トークンのトップ・プールアドレスをGeckoTerminalから取得する。"""
    pools = {}
    for symbol, mint in tokens.items():
        try:
            url = f"{GECKOTERMINAL_BASE}/networks/solana/tokens/{mint}/pools"
            data = _gecko_get(url, params={"page": 1})
            pool_list = data.get("data", [])
            if pool_list:
                pool_addr = pool_list[0].get("attributes", {}).get("address")
                if pool_addr:
                    pools[symbol] = pool_addr
                    if DEBUG:
                        name = pool_list[0].get("attributes", {}).get("name", "")
                        print(f"[DEBUG] {symbol}: pool={pool_addr} ({name})")
            else:
                print(f"[WARN] {symbol}: プールが見つかりません")
        except Exception as e:
            print(f"[ERROR] {symbol} プール取得失敗: {e}")
        time.sleep(2)  # rate limit 対策
    return pools


def get_confirmed_candle(pool_address):
    """確定済みの最新ローソク足（1つ前の足）をGeckoTerminalから取得する。

    ohlcv_list は新しい順。index 0 = 形成中の足、index 1 = 確定済みの足。
    """
    tf, agg = TIMEFRAME_MAP[CANDLE_MINUTES]
    url = f"{GECKOTERMINAL_BASE}/networks/solana/pools/{pool_address}/ohlcv/{tf}"
    params = {"aggregate": agg, "limit": 2, "currency": "usd"}
    data = _gecko_get(url, params=params)

    ohlcv_list = data.get("data", {}).get("attributes", {}).get("ohlcv_list", [])
    if len(ohlcv_list) < 2:
        return None

    # index 1 = 確定済みの足: [timestamp, open, high, low, close, volume]
    c = ohlcv_list[1]
    return {
        "timestamp": int(c[0]),
        "open": float(c[1]),
        "high": float(c[2]),
        "low": float(c[3]),
        "close": float(c[4]),
        "volume": float(c[5]),
    }

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

    if CANDLE_MINUTES not in TIMEFRAME_MAP:
        supported = ", ".join(str(m) for m in sorted(TIMEFRAME_MAP))
        print(f"[ERROR] CANDLE_MINUTES={CANDLE_MINUTES} は未対応です（対応: {supported}）")
        return

    if DEBUG:
        print("[DEBUG] デバッグモードで起動")
        print(f"[DEBUG] CHECK_INTERVAL={CHECK_INTERVAL}秒, CANDLE_MINUTES={CANDLE_MINUTES}, PUMP_THRESHOLD={PUMP_THRESHOLD*100:.0f}%")
    else:
        print(f"本番モード: {CANDLE_MINUTES}分足 / 閾値 {PUMP_THRESHOLD*100:.0f}%")

    print("プールアドレスを取得中...")
    pools = resolve_pools(TOKENS)
    if not pools:
        print("[ERROR] プールが1つも取得できませんでした")
        return
    print(f"{len(pools)}/{len(TOKENS)} トークンのプールを取得しました")

    print("Solana Pump Watcher 起動しました")

    alerted = {}      # symbol -> アラート済み足の timestamp
    candle_cache = {}  # symbol -> 確定足データ
    next_fetch = 0     # 次にOHLCVを取得する時刻（unix timestamp）

    while True:
        now = time.time()

        # 足の境界を超えたら全トークンのOHLCVを再取得
        if now >= next_fetch:
            print(f"OHLCV取得中... ({len(pools)}トークン)")
            for symbol in list(pools.keys()):
                pool = pools[symbol]
                try:
                    candle = get_confirmed_candle(pool)
                except Exception as e:
                    print(f"[ERROR] {symbol} OHLCV取得失敗: {e}")
                    continue
                if candle:
                    candle_cache[symbol] = candle
                time.sleep(2)  # rate limit 対策

            # 次の足の境界 + 5秒バッファ
            candle_seconds = CANDLE_MINUTES * 60
            next_fetch = ((now // candle_seconds) + 1) * candle_seconds + 5

            if DEBUG:
                from datetime import datetime
                next_dt = datetime.fromtimestamp(next_fetch)
                print(f"[DEBUG] 次回取得: {next_dt.strftime('%H:%M:%S')}")

        # キャッシュされた確定足でアラート判定
        for symbol, candle in candle_cache.items():
            body = (candle["close"] - candle["open"]) / candle["open"]

            if DEBUG:
                print(
                    f"[DEBUG] {symbol}: O={candle['open']:.6f} H={candle['high']:.6f} "
                    f"L={candle['low']:.6f} C={candle['close']:.6f} ({body*100:+.2f}%)"
                )

            if body >= PUMP_THRESHOLD and alerted.get(symbol) != candle["timestamp"]:
                msg = (
                    f"\n{symbol} 急騰！\n"
                    f"O: {candle['open']:.6f} → C: {candle['close']:.6f}\n"
                    f"変動率: {body*100:+.2f}%"
                )
                print(msg)
                notify_line(msg)
                alerted[symbol] = candle["timestamp"]

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
