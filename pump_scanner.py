#!/usr/bin/env python3
"""
pump.fun 急騰スキャナー

pump.funで作られた銘柄を自動スキャンし、急騰しているものを検出・LINE通知する。
ユニークIDを指定せずに全銘柄を捜査する。

トークン取得: pump.fun API (currently-live / search)
価格変動データ: DexScreener API (priceChange を利用)
通知: LINE Messaging API
"""

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

# 急騰判定の閾値 (%)
SURGE_THRESHOLD = float(os.environ.get("SURGE_THRESHOLD", "10"))

# フィルタ条件
MIN_LIQUIDITY_USD = float(os.environ.get("MIN_LIQUIDITY", "1000"))
MIN_VOLUME_USD = float(os.environ.get("MIN_VOLUME", "500"))

# 価格変動のタイムフレーム: m5(5分), h1(1時間), h6(6時間), h24(24時間)
TIMEFRAME = os.environ.get("TIMEFRAME", "h1")

# スキャン間隔（秒）
SCAN_INTERVAL = int(os.environ.get("SCAN_INTERVAL", "120"))

# 1回のスキャンで取得するトークン数
TOKEN_LIMIT = int(os.environ.get("TOKEN_LIMIT", "200"))

# 通知済みトークンの再通知までの時間（秒）
NOTIFY_COOLDOWN = int(os.environ.get("NOTIFY_COOLDOWN", "3600"))

# API設定
PUMP_API_BASE = "https://frontend-api-v3.pump.fun"
DEXSCREENER_API = "https://api.dexscreener.com"
DEXSCREENER_BATCH_SIZE = 30  # DexScreenerは一度に30アドレスまで

# ======================
# LINE通知
# ======================

def notify_line(message):
    if DEBUG:
        print(f"[DEBUG] LINE通知（送信スキップ）: {message}")
        return

    if not LINE_TOKEN:
        print("[WARN] LINE_TOKEN が未設定です")
        return

    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Authorization": f"Bearer {LINE_TOKEN}"}
    json_data = {
        "to": UID,
        "messages": [{"type": "text", "text": message}],
    }
    try:
        r = requests.post(url, headers=headers, json=json_data)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"[ERROR] LINE通知に失敗: {e}")

# ======================
# pump.fun API: トークン取得
# ======================

def _fetch_pump_page(url, params):
    """pump.fun APIから1ページ分のデータを取得する。"""
    headers = {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0",
    }
    r = requests.get(url, params=params, headers=headers, timeout=15)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, list):
        return data
    # レスポンスがlistでない場合（認証エラー等）
    if DEBUG:
        print(f"[DEBUG] pump.fun response: {str(data)[:200]}")
    return []


def fetch_pump_tokens_live(limit=TOKEN_LIMIT):
    """pump.fun の currently-live エンドポイントからアクティブなトークンを取得。"""
    tokens = []
    offset = 0
    page_size = min(limit, 50)

    while len(tokens) < limit:
        params = {
            "offset": offset,
            "limit": page_size,
            "includeNsfw": "false",
        }
        try:
            page = _fetch_pump_page(f"{PUMP_API_BASE}/coins/currently-live", params)
            if not page:
                break
            tokens.extend(page)
            offset += page_size
            if len(page) < page_size:
                break
            time.sleep(0.3)
        except Exception as e:
            if DEBUG:
                print(f"[DEBUG] pump.fun currently-live error: {e}")
            break

    return tokens[:limit]


def fetch_pump_tokens_search(limit=TOKEN_LIMIT):
    """pump.fun の search エンドポイントから market_cap 順でトークンを取得。"""
    tokens = []
    offset = 0
    page_size = min(limit, 50)

    while len(tokens) < limit:
        params = {
            "sort": "market_cap",
            "order": "DESC",
            "offset": offset,
            "limit": page_size,
            "includeNsfw": "false",
        }
        try:
            page = _fetch_pump_page(f"{PUMP_API_BASE}/coins/search", params)
            if not page:
                break
            tokens.extend(page)
            offset += page_size
            if len(page) < page_size:
                break
            time.sleep(0.3)
        except Exception as e:
            if DEBUG:
                print(f"[DEBUG] pump.fun search error: {e}")
            break

    return tokens[:limit]


def fetch_dexscreener_profiles():
    """DexScreener token-profiles / token-boosts からSolanaトークンを取得（フォールバック用）。"""
    mints = set()
    endpoints = [
        f"{DEXSCREENER_API}/token-profiles/latest/v1",
        f"{DEXSCREENER_API}/token-boosts/latest/v1",
        f"{DEXSCREENER_API}/token-boosts/top/v1",
    ]
    for url in endpoints:
        try:
            r = requests.get(url, timeout=15)
            data = r.json()
            if isinstance(data, list):
                for item in data:
                    if item.get("chainId") == "solana" and item.get("tokenAddress"):
                        mints.add(item["tokenAddress"])
            time.sleep(0.3)
        except Exception as e:
            if DEBUG:
                print(f"[DEBUG] DexScreener profiles error ({url}): {e}")
    return list(mints)


def discover_tokens():
    """トークンのミントアドレスを収集する。pump.fun API → DexScreener フォールバック。"""
    mint_set = set()

    # 方法1: pump.fun API
    print("  pump.fun APIからトークン取得中...")
    live_tokens = fetch_pump_tokens_live(limit=TOKEN_LIMIT)
    print(f"    currently-live: {len(live_tokens)} 件")

    search_tokens = fetch_pump_tokens_search(limit=TOKEN_LIMIT)
    print(f"    search (market_cap順): {len(search_tokens)} 件")

    for t in live_tokens + search_tokens:
        mint = t.get("mint")
        if mint:
            mint_set.add(mint)

    # 方法2: DexScreener フォールバック（pump.funから取得できなかった場合）
    if not mint_set:
        print("  pump.fun API失敗 → DexScreener からトークン取得中...")
        dex_mints = fetch_dexscreener_profiles()
        mint_set.update(dex_mints)
        print(f"    DexScreener profiles: {len(dex_mints)} 件")

    mints = list(mint_set)
    print(f"    ユニーク銘柄数: {len(mints)}")
    return mints

# ======================
# DexScreener API: 価格データ取得
# ======================

def get_dex_data(mints):
    """DexScreener APIからトークンのペアデータを一括取得する。"""
    all_pairs = []

    for i in range(0, len(mints), DEXSCREENER_BATCH_SIZE):
        batch = mints[i:i + DEXSCREENER_BATCH_SIZE]
        url = f"{DEXSCREENER_API}/tokens/v1/solana/{','.join(batch)}"
        try:
            r = requests.get(url, timeout=15)
            data = r.json()
            if isinstance(data, list):
                all_pairs.extend(data)
            elif DEBUG:
                print(f"[DEBUG] DexScreener response: {str(data)[:200]}")
            time.sleep(0.5)
        except Exception as e:
            if DEBUG:
                print(f"[DEBUG] DexScreener error: {e}")

    return all_pairs

# ======================
# 急騰検出
# ======================

def detect_surges(pairs):
    """ペアデータから急騰しているトークンを検出する。"""
    surges = []
    seen = set()

    for pair in pairs:
        base = pair.get("baseToken", {})
        addr = base.get("address", "")

        if addr in seen:
            continue

        # 流動性フィルタ
        liquidity = pair.get("liquidity", {}).get("usd") or 0
        if liquidity < MIN_LIQUIDITY_USD:
            continue

        # 出来高フィルタ
        volume_24h = pair.get("volume", {}).get("h24") or 0
        if volume_24h < MIN_VOLUME_USD:
            continue

        # 価格変動チェック
        price_change = pair.get("priceChange", {}).get(TIMEFRAME) or 0
        if price_change < SURGE_THRESHOLD:
            continue

        seen.add(addr)
        surges.append({
            "symbol": base.get("symbol", "???"),
            "name": base.get("name", "Unknown"),
            "address": addr,
            "price_usd": pair.get("priceUsd", "0"),
            "price_change": price_change,
            "liquidity_usd": liquidity,
            "volume_24h": volume_24h,
            "market_cap": pair.get("marketCap") or 0,
            "dex_id": pair.get("dexId", ""),
            "pair_url": pair.get("url", ""),
        })

    surges.sort(key=lambda x: x["price_change"], reverse=True)
    return surges

# ======================
# メイン
# ======================

def parse_args():
    parser = argparse.ArgumentParser(description="pump.fun 急騰スキャナー")
    parser.add_argument("--debug", action="store_true", help="デバッグモードで起動")
    parser.add_argument("--once", action="store_true", help="1回だけスキャンして終了")
    parser.add_argument("--timeframe", choices=["m5", "h1", "h6", "h24"],
                        help="価格変動のタイムフレーム")
    parser.add_argument("--threshold", type=float,
                        help="急騰判定の閾値（%%）")
    parser.add_argument("--limit", type=int,
                        help="取得するトークン数")
    return parser.parse_args()


def main():
    global DEBUG, SURGE_THRESHOLD, TIMEFRAME, TOKEN_LIMIT

    args = parse_args()
    DEBUG = args.debug or os.environ.get("DEBUG", "false").lower() in ("true", "1", "yes")

    if args.timeframe:
        TIMEFRAME = args.timeframe
    if args.threshold:
        SURGE_THRESHOLD = args.threshold
    if args.limit:
        TOKEN_LIMIT = args.limit

    print("=" * 55)
    print("  pump.fun 急騰スキャナー")
    print("=" * 55)
    print(f"  閾値       : +{SURGE_THRESHOLD}% 以上")
    print(f"  タイムフレーム : {TIMEFRAME}")
    print(f"  最低流動性   : ${MIN_LIQUIDITY_USD:,.0f}")
    print(f"  最低出来高   : ${MIN_VOLUME_USD:,.0f}")
    print(f"  取得トークン数 : {TOKEN_LIMIT}")
    print(f"  スキャン間隔  : {SCAN_INTERVAL}秒")
    if DEBUG:
        print("  モード      : デバッグ")
    print("=" * 55)

    # 通知済みトークン {address: timestamp}
    notified = {}

    while True:
        try:
            now = time.time()
            print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] スキャン開始")

            # Step 1: pump.fun からトークン取得
            mints = discover_tokens()

            if not mints:
                print("  [WARN] トークンが取得できませんでした")
                if args.once:
                    break
                time.sleep(SCAN_INTERVAL)
                continue

            # Step 2: DexScreener で価格データ取得
            print(f"  DexScreener からペアデータ取得中...")
            pairs = get_dex_data(mints)
            print(f"    取得ペア数: {len(pairs)}")

            # Step 3: 急騰検出
            surges = detect_surges(pairs)

            if surges:
                print(f"\n  {'='*50}")
                print(f"  急騰検出: {len(surges)} 銘柄 (閾値: +{SURGE_THRESHOLD}%, {TIMEFRAME})")
                print(f"  {'='*50}")

                for s in surges:
                    addr = s["address"]
                    is_cooldown = addr in notified and (now - notified[addr]) < NOTIFY_COOLDOWN
                    status = " [通知済]" if is_cooldown else ""

                    print(f"  {s['symbol']:>10s} | "
                          f"+{s['price_change']:>7.1f}% | "
                          f"${float(s['price_usd']):>14.8f} | "
                          f"流動性 ${s['liquidity_usd']:>10,.0f} | "
                          f"MC ${s['market_cap']:>10,.0f}"
                          f"{status}")

                    if DEBUG:
                        print(f"             DEX: {s['dex_id']} | {s['pair_url']}")
                        print(f"             Mint: {addr}")

                    # 未通知 or クールダウン経過のもののみ通知
                    if not is_cooldown:
                        dex_url = f"https://dexscreener.com/solana/{addr}"
                        msg = (
                            f"\npump.fun 急騰検出!\n"
                            f"銘柄: {s['symbol']} ({s['name']})\n"
                            f"変動率: +{s['price_change']:.1f}% ({TIMEFRAME})\n"
                            f"価格: ${float(s['price_usd']):.8f}\n"
                            f"流動性: ${s['liquidity_usd']:,.0f}\n"
                            f"出来高(24h): ${s['volume_24h']:,.0f}\n"
                            f"時価総額: ${s['market_cap']:,.0f}\n"
                            f"{dex_url}"
                        )
                        notify_line(msg)
                        notified[addr] = now

                print(f"  {'='*50}")
            else:
                print(f"  急騰なし (閾値: +{SURGE_THRESHOLD}%, {TIMEFRAME})")

            # 期限切れの通知記録をクリーンアップ
            expired = [a for a, t in notified.items() if (now - t) > NOTIFY_COOLDOWN * 2]
            for a in expired:
                del notified[a]

            if args.once:
                break

            next_scan = datetime.fromtimestamp(now + SCAN_INTERVAL)
            print(f"\n  次回スキャン: {next_scan.strftime('%H:%M:%S')}")

        except KeyboardInterrupt:
            print("\n停止しました")
            break
        except Exception as e:
            print(f"[ERROR] スキャンエラー: {e}")
            if DEBUG:
                import traceback
                traceback.print_exc()

        if args.once:
            break

        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    main()
