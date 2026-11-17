# mac-mini-refurb-watch

Apple公式の[整備済製品ページ](https://www.apple.com/jp/shop/refurbished/mac)を5分ごとにチェックして、以下が出品されたら**Discordに通知**します。

- **13インチMacBook Air・M5以降・メモリ32GB・SSD 1TB（US・JISキーボード）**

※ 購入する構成を13インチAir・32GB・1TBに決めたため、通知はこの1構成だけに絞っています（2026-11-17）。メモリ・SSDは「ちょうど一致」で、24GBや512GB・2TBは通知しません。以前の「14インチMacBook Pro・M5以降・メモリ24GB以上」の監視は停止しました（戻す場合はgit履歴の `matches_specs` と `WATCHES` を参照）。

※ リポジトリ名の由来であるMac mini監視は、M6搭載の新型発売に伴い2026-08-26に停止しました（復活させる場合はgit履歴参照）。

GitHub Actionsで動くので、サーバー不要・完全無料です。

![Discord通知のデモ](docs/demo.png)
*（通知イメージ）*

## 仕組み

```
GitHub Actions (5分ごとのcron)
  └─ check.py
       ├─ Appleの整備済製品ページ（MacBook Air）を取得
       ├─ 埋め込みJSON (REFURB_GRID_BOOTSTRAP) から監視対象を抽出
       │    └─ 機種・サイズ・M5以降・メモリ32GB・SSD 1TBで絞り、タイル情報または商品詳細ページで配列を判定（Air: US/JIS）
       ├─ state.json（前回の出品リスト・キーボード判定キャッシュ）と比較
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

Actionsタブ → **Check refurbished MacBook Air 13 (M5+, 32GB, 1TB, US/JIS)** → **Run workflow** で手動実行。
ログに `MacBook Air (USキーボード): tiles: NNN, hit: N, new: N` のような行が監視対象ごとに出れば動いています。

## ローカルでの動作確認

```sh
python check.py                 # DISCORD_WEBHOOK_URL 未設定ならドライラン（通知内容をprintするだけ）
```

## 注意

- GitHub Actionsのcronは負荷状況で数分〜十数分遅れることがあります。
- **リポジトリに60日間コミットがないと、GitHubがスケジュール実行を自動停止します**（メールが来るのでActionsタブから再有効化すればOK）。在庫変動があるたびに `state.json` がコミットされるので、実際にはほぼ止まりません。
- 監視対象を増やしたい場合は `check.py` の `WATCHES` に `model`・`url`・タイル判定関数を指定したエントリを追加してください。`model` はAppleの `refurbClearModel` に対応します。
- MacBook Airは、まず一覧タイル内のUS/JIS表記を確認し、判定できない場合だけ商品詳細ページを取得します。US・JISの両方を通知し、通知の見出しに機種と配列を表示します。対象は13インチ（13.3/13.6インチを含む）・M5以降（M5 Pro/MaxやM6以降も含む）・メモリ32GB・SSD 1TBです。メモリ・SSD容量の目標値は `check.py` の `TARGET_MEMORY_GB` / `TARGET_STORAGE` で、一覧データにメモリやSSD容量の値が無い商品は通知しません。14インチMacBook Proは通知しません。条件外・仕様不明の商品も通知しません。価格による制限はありません。
- 通知は1出品ごとに、タイトル（クリックで商品ページへ）に「画面サイズ・機種｜チップ（CPU/GPUコア数）｜メモリ｜SSD｜キーボード配列｜カラー」を並べ、価格・チップ・メモリ（Apple シリコンはGPUと共用＝VRAM相当）・ストレージ・配列・カラーを項目でも表示します。M5／M5 Pro／M5 Maxやコア数違いも開かずに見分けられます。仕様は一覧ページのデータから取り、取れない項目は「不明」と表示します。
- キーボード配列はpartNumberごとに `us` / `jis` として保存します。不明・取得失敗・US/JIS両方の表記がある商品は通知せず、次回実行で再試行します。旧形式の `true` はUSとして引き継ぎ、`false`（非US）はJISと断定せず再判定します。
- 条件を絞った後の初回実行では、前回の記録（`state.json`）に残っていた条件外の出品（Proや24GBなど）は通知なしで記録から消えます。以後は条件に合うAirの追加・再入荷時に通知します。
- 通知周期はGitHub Actionsのcron（`.github/workflows/check.yml`）で5分に設定しています。publicリポジトリなのでActionsは無料・無制限です（Privateに戻す場合は無料枠の都合で30分以上に戻すこと）。
