"""LINE Messaging API への通知処理（共通ユーティリティ）"""

from dotenv import load_dotenv
load_dotenv()

import os

import requests

UID = os.getenv("UID", "")
LINE_TOKEN = os.getenv("LINE_TOKEN", "")

LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"


def notify_line(message, debug=False):
    if debug:
        print(f"[DEBUG] LINE通知（送信スキップ）: {message}")
        return

    if not LINE_TOKEN:
        print("[WARN] LINE_TOKEN が未設定です")
        return

    headers = {"Authorization": f"Bearer {LINE_TOKEN}"}
    json_data = {
        "to": UID,
        "messages": [{"type": "text", "text": message}],
    }
    try:
        r = requests.post(LINE_PUSH_URL, headers=headers, json=json_data)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"[ERROR] LINE通知に失敗: {e}")
