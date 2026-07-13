# mac-mini-refurb-watch

Apple公式の[整備済製品ページ](https://www.apple.com/jp/shop/refurbished/mac/mac-mini)を30分ごとにチェックして、**Mac miniが出品されたらDiscordに通知**します。

GitHub Actionsで動くので、サーバー不要・完全無料です。

![Discord通知のデモ](docs/demo.png)
*（通知イメージ）*

## 仕組み

```
GitHub Actions (30分ごとのcron)
  └─ check.py
       ├─ Appleの整備済製品ページを取得
       ├─ 埋め込みJSON (REFURB_GRID_BOOTSTRAP) からMac miniを抽出
       ├─ state.json（前回の出品リスト）と比較
       ├─ 新着があれば Discord Webhook に通知
       └─ state.json を更新してリポジトリにコミット
```

依存ライブラリなし（Python標準ライブラリのみ）。

## セットアップ

### 1. Discord Webhookを作る

通知を受け取りたいDiscordチャンネルで：
**チャンネル設定（⚙️）→ 連携サービス → ウェブフック → 新しいウェブフック → URLをコピー**

### 2. GitHubリポジトリを作ってプッシュ

```sh
gh repo create mac-mini-refurb-watch --private --source . --push
```

### 3. Webhook URLをSecretに登録

```sh
gh secret set DISCORD_WEBHOOK_URL --body "https://discord.com/api/webhooks/..."
```

（またはリポジトリの Settings → Secrets and variables → Actions から `DISCORD_WEBHOOK_URL` を登録）

### 4. 動作確認

Actionsタブ → **Check refurbished Mac mini** → **Run workflow** で手動実行。
ログに `tiles: NNN, Mac mini: N, new: N` と出れば動いています。

## ローカルでの動作確認

```sh
python check.py                 # DISCORD_WEBHOOK_URL 未設定ならドライラン（通知内容をprintするだけ）
```

## 注意

- GitHub Actionsのcronは負荷状況で数分〜十数分遅れることがあります。
- **リポジトリに60日間コミットがないと、GitHubがスケジュール実行を自動停止します**（メールが来るのでActionsタブから再有効化すればOK）。在庫変動があるたびに `state.json` がコミットされるので、実際にはほぼ止まりません。
- 監視対象を変えたい場合は `check.py` の `URL` と `extract_minis()` のフィルタ（`refurbClearModel`）を変更してください（例：`macstudio`, `macbookair` など）。
