# sol_pump_watcher

Solana上のトークンを監視し、LINEに通知するスクリプト集。

## holder_watcher.py — 上位ホルダー変動監視

指定した1銘柄について、上位N人（デフォルト100人）のホルダーの顔ぶれを
定期チェックし、新規ランクイン/ランク外脱落があればLINE通知する。

### 必要な環境変数（`.env`）

```
TARGET_TOKEN=<監視したいトークンのmintアドレス>
SOLANA_RPC_URL=<Solana RPCエンドポイント>   # 省略時は公開RPC（レート制限に注意）
LINE_TOKEN=<LINE Messaging APIのチャネルアクセストークン>
UID=<通知先のLINEユーザーID>

# 任意
TOP_N=100          # 監視する順位
CHECK_INTERVAL=300 # チェック間隔（秒）
```

`getProgramAccounts` を使うため、公開RPC (`api.mainnet-beta.solana.com`) は
レート制限や拒否をされやすい。Helius / QuickNode 等の専用RPCの利用を推奨。

Token-2022（拡張付きトークン）には対応していない。

### 実行

```
uv run python holder_watcher.py
uv run python holder_watcher.py --once --debug          # 1回だけ実行（通知はスキップ）
uv run python holder_watcher.py --token <mint> --top 50  # 上位50人を監視
```

初回実行時は現在の上位ホルダーを記録するだけで通知は行わない。
2回目以降のチェックで前回と比較し、変動があれば通知する。

状態は `holder_state_<mint>.json` に保存される（`.gitignore` 対象）。
