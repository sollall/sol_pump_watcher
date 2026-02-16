import time
import requests

# ======================
# 設定
# ======================

LINE_TOKEN = "YOUR_LINE_NOTIFY_TOKEN"

# 監視するトークン（例：BONK）
TOKENS = {
    "BONK": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
}

CHECK_INTERVAL = 30        # 秒
PUMP_THRESHOLD = 0.10      # 10%

# ======================
# LINE通知
# ======================

def notify_line(message):
    url = "https://notify-api.line.me/api/notify"
    headers = {
        "Authorization": f"Bearer {LINE_TOKEN}"
    }
    data = {"message": message}
    requests.post(url, headers=headers, data=data)

# ======================
# 価格取得（Jupiter）
# ======================

def get_price(mint):
    url = "https://price.jup.ag/v4/price"
    params = {"ids": mint}
    r = requests.get(url, params=params, timeout=10)
    data = r.json()

    if mint not in data["data"]:
        return None

    return data["data"][mint]["price"]


# ======================
# メイン監視ロジック
# ======================

def main():
    last_prices = {}

    print("🚀 Solana Pump Watcher 起動しました")

    while True:
        for symbol, mint in TOKENS.items():
            try:
                price = get_price(mint)
                if price is None:
                    continue

                if symbol in last_prices:
                    prev = last_prices[symbol]
                    change = (price - prev) / prev

                    if change >= PUMP_THRESHOLD:
                        print(
                            f"🔥 {symbol} 急騰！\n"
                            f"価格: {price:.6f}\n"
                            f"変動率: +{change*100:.2f}%"
                        )

                last_prices[symbol] = price

            except Exception as e:
                print(f"Error ({symbol}):", e)

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
