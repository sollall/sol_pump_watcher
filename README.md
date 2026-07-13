# sol_pump_watcher

Solana上のトークンを監視し、LINEに通知するスクリプト集。

## holder_watcher.py — 上位ホルダー変動監視

指定した1銘柄について、上位N人（最大20人。`getTokenLargestAccounts` の
仕様上の上限）のホルダーの顔ぶれを定期チェックし、新規ランクイン/
ランク外脱落があればLINE通知する。ホルダーは `getTokenLargestAccounts`
でその都度動的に取得する（固定リストではない）。

### 必要な環境変数（`.env`）

```
TARGET_TOKEN=<監視したいトークンのmintアドレス>
ALCHEMY_API_KEY=<AlchemyのAPIキー>   # 指定するとAlchemyのSolanaエンドポイントを自動使用
LINE_TOKEN=<LINE Messaging APIのチャネルアクセストークン>
UID=<通知先のLINEユーザーID>

# 任意
TOP_N=20           # 監視する順位（最大20。超過分は丸められる）
CHECK_INTERVAL=300 # チェック間隔（秒）
```

`ALCHEMY_API_KEY` にAlchemyのAPIキーを設定すれば、
`https://solana-mainnet.g.alchemy.com/v2/<APIKEY>` を自動的にRPCエンドポイントとして使用する。
公開RPC (`api.mainnet-beta.solana.com`) はレート制限や拒否をされやすいため非推奨。

Token-2022（拡張付きトークン）には対応していない。

### 実行

```
uv run python holder_watcher.py
uv run python holder_watcher.py --once --debug          # 1回だけ実行（通知はスキップ）
uv run python holder_watcher.py --token <mint> --top 20  # 上位20人を監視
```

初回実行時は現在の上位ホルダーを記録するだけで通知は行わない。
2回目以降のチェックで前回と比較し、変動があれば通知する。

状態は `holder_state_<mint>.json` に保存される（`.gitignore` 対象）。
