#!/usr/bin/env python3
"""
Solana 上位ホルダー監視

指定した1銘柄について、上位N人（最大20人。Solana RPCの仕様上の上限）の
ホルダーの顔ぶれを定期的にチェックし、新規ランクイン/ランク外脱落があれば
LINEに通知する。

ホルダー取得: Solana JSON-RPC (getTokenLargestAccounts)
通知: LINE Messaging API

注意:
- getTokenLargestAccounts は最大20件までしか返さない仕様のため、
  TOP_N は20を超えて指定しても20件に丸められる。
- 公開RPCだとレート制限や拒否をされやすいため、Alchemy 等の専用RPCの
  利用を推奨（ALCHEMY_API_KEY にAPIキーを設定するか、SOLANA_RPC_URL
  でエンドポイントを直接指定する）。
- getTokenLargestAccounts はトークンアカウント単位（ATA）の残高を返し、
  ウォレットのowner自体は返さない。1ウォレットにつき同一mintのATAは
  通常1つのため、実質的にウォレット単位のランキングとして扱う。
"""

from dotenv import load_dotenv
load_dotenv()

import argparse
import json
import os
import time
from datetime import datetime

import requests

from line_notify import notify_line

# ======================
# 設定
# ======================

DEBUG = False

# 監視するトークンの mint アドレス
TARGET_TOKEN = os.environ.get("TARGET_TOKEN", "")

# Solana RPC エンドポイント
# ALCHEMY_API_KEY を設定するとAlchemyのSolanaエンドポイントを自動組み立てする。
# SOLANA_RPC_URL を明示指定した場合はそちらを優先する。
ALCHEMY_API_KEY = os.environ.get("ALCHEMY_API_KEY", "")
SOLANA_RPC_URL = os.environ.get("SOLANA_RPC_URL") or (
    f"https://solana-mainnet.g.alchemy.com/v2/{ALCHEMY_API_KEY}"
    if ALCHEMY_API_KEY
    else "https://api.mainnet-beta.solana.com"
)

# getTokenLargestAccounts が返す最大件数（Solana RPCの仕様上の上限）
MAX_TOP_N = 20

# 監視する順位（上位N人）。MAX_TOP_N を超える値は丸められる。
TOP_N = min(int(os.environ.get("TOP_N", str(MAX_TOP_N))), MAX_TOP_N)

# チェック間隔（秒）。ホルダー取得はコストが高いため長めを推奨
CHECK_INTERVAL = int(os.environ.get("CHECK_INTERVAL", "300"))

# 状態保存ファイルの出力先ディレクトリ
STATE_DIR = os.environ.get("STATE_DIR", ".")

# 通知に含める変動の最大表示件数
MAX_LIST_IN_NOTIFY = 10

# ======================
# Solana RPC
# ======================

def _rpc_call(method, params):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    r = requests.post(SOLANA_RPC_URL, json=payload, timeout=60)
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError(f"RPC error: {data['error']}")
    return data["result"]


def get_token_decimals(mint):
    """トークンの decimals を取得する。"""
    result = _rpc_call("getTokenSupply", [mint])
    return int(result["value"]["decimals"])


def get_top_holders(mint, top_n):
    """getTokenLargestAccounts で上位ホルダー（トークンアカウント単位）を動的に取得する。

    最大20件までしか返らない（Solana RPCの仕様上の上限）ため、
    top_n が20を超えていても実際には20件までしか返らない。
    """
    result = _rpc_call("getTokenLargestAccounts", [mint, {"commitment": "confirmed"}])
    accounts = result["value"]
    ranked = sorted(accounts, key=lambda a: int(a["amount"]), reverse=True)[:top_n]
    return [{"owner": a["address"], "amount": int(a["amount"])} for a in ranked]

# ======================
# 状態の保存・読込
# ======================

def state_file_path(mint):
    return os.path.join(STATE_DIR, f"holder_state_{mint}.json")


def load_state(mint):
    path = state_file_path(mint)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"[WARN] 状態ファイルの読込に失敗: {e}")
        return None


def save_state(mint, decimals, holders):
    path = state_file_path(mint)
    state = {
        "mint": mint,
        "decimals": decimals,
        "updated_at": datetime.now().isoformat(),
        "holders": holders,
    }
    with open(path, "w") as f:
        json.dump(state, f, indent=2)

# ======================
# 変動検出
# ======================

def format_amount(amount, decimals):
    return amount / (10 ** decimals) if decimals else amount


def short_addr(addr):
    return f"{addr[:4]}...{addr[-4:]}"


def diff_holders(prev_holders, curr_holders):
    """前回と今回の上位ホルダーリストから新規ランクイン/ランク外を検出する。"""
    prev_owners = {h["owner"]: i + 1 for i, h in enumerate(prev_holders)}
    curr_owners = {h["owner"]: i + 1 for i, h in enumerate(curr_holders)}

    entered = [h for h in curr_holders if h["owner"] not in prev_owners]
    exited = [
        {"owner": owner, "rank": rank}
        for owner, rank in prev_owners.items()
        if owner not in curr_owners
    ]
    return entered, exited


def build_notify_message(symbol_label, entered, exited, curr_holders, decimals, top_n):
    lines = [f"\n{symbol_label} 上位{top_n}ホルダーに変動あり"]

    if entered:
        lines.append(f"\n[新規ランクイン] {len(entered)}件")
        rank_by_owner = {h["owner"]: i + 1 for i, h in enumerate(curr_holders)}
        for h in entered[:MAX_LIST_IN_NOTIFY]:
            rank = rank_by_owner[h["owner"]]
            amt = format_amount(h["amount"], decimals)
            lines.append(f"  #{rank} {short_addr(h['owner'])} ({amt:,.2f})")
        if len(entered) > MAX_LIST_IN_NOTIFY:
            lines.append(f"  ...他 {len(entered) - MAX_LIST_IN_NOTIFY} 件")

    if exited:
        lines.append(f"\n[ランク外] {len(exited)}件")
        for h in exited[:MAX_LIST_IN_NOTIFY]:
            lines.append(f"  元#{h['rank']} {short_addr(h['owner'])}")
        if len(exited) > MAX_LIST_IN_NOTIFY:
            lines.append(f"  ...他 {len(exited) - MAX_LIST_IN_NOTIFY} 件")

    return "\n".join(lines)

# ======================
# メイン監視ロジック
# ======================

def parse_args():
    parser = argparse.ArgumentParser(description="Solana 上位ホルダー監視")
    parser.add_argument("--debug", action="store_true", help="デバッグモードで起動")
    parser.add_argument("--once", action="store_true", help="1回だけチェックして終了")
    parser.add_argument("--token", help="監視するトークンの mint アドレス")
    parser.add_argument("--top", type=int, help=f"監視する順位（上位N人、最大{MAX_TOP_N}）")
    parser.add_argument("--interval", type=int, help="チェック間隔（秒）")
    return parser.parse_args()


def run_check(mint, top_n):
    decimals = get_token_decimals(mint)
    curr_holders = get_top_holders(mint, top_n)

    if not curr_holders:
        print("[WARN] ホルダーを取得できませんでした")
        return

    prev_state = load_state(mint)

    if prev_state is None:
        print(f"[INFO] 初回スキャン: 上位{len(curr_holders)}人を記録しました")
        save_state(mint, decimals, curr_holders)
        return

    prev_holders = prev_state.get("holders", [])
    entered, exited = diff_holders(prev_holders, curr_holders)

    if DEBUG:
        print(f"[DEBUG] 前回ホルダー数: {len(prev_holders)}, 今回: {len(curr_holders)}")
        print(f"[DEBUG] 新規: {len(entered)}, 脱落: {len(exited)}")

    if entered or exited:
        msg = build_notify_message(mint, entered, exited, curr_holders, decimals, top_n)
        print(msg)
        notify_line(msg, debug=DEBUG)
    else:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 変動なし（上位{top_n}人）")

    save_state(mint, decimals, curr_holders)


def main():
    global DEBUG

    args = parse_args()
    DEBUG = args.debug or os.environ.get("DEBUG", "false").lower() in ("true", "1", "yes")

    mint = args.token or TARGET_TOKEN
    top_n = min(args.top, MAX_TOP_N) if args.top else TOP_N
    interval = args.interval or CHECK_INTERVAL

    if not mint:
        print("[ERROR] 監視対象トークンが未指定です。TARGET_TOKEN 環境変数か --token を指定してください")
        return

    print("Solana 上位ホルダー監視 起動しました")
    print(f"  監視トークン: {mint}")
    print(f"  監視順位   : 上位{top_n}人")
    print(f"  RPC        : {SOLANA_RPC_URL}")
    print(f"  チェック間隔 : {interval}秒")
    if DEBUG:
        print("  モード     : デバッグ")

    while True:
        try:
            run_check(mint, top_n)
        except KeyboardInterrupt:
            print("\n停止しました")
            break
        except Exception as e:
            print(f"[ERROR] チェック失敗: {e}")
            if DEBUG:
                import traceback
                traceback.print_exc()

        if args.once:
            break

        time.sleep(interval)


if __name__ == "__main__":
    main()
