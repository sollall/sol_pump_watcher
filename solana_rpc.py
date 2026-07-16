"""Solana JSON-RPC 呼び出し処理（共通ユーティリティ）"""

from dotenv import load_dotenv
load_dotenv()

import os

import requests

# Solana RPC エンドポイント（Alchemy固定）
ALCHEMY_API_KEY = os.getenv("ALCHEMY_API_KEY", "")
SOLANA_RPC_URL = f"https://solana-mainnet.g.alchemy.com/v2/{ALCHEMY_API_KEY}"


def rpc_call(method, params):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    r = requests.post(SOLANA_RPC_URL, json=payload, timeout=60)
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError(f"RPC error: {data['error']}")
    return data["result"]
