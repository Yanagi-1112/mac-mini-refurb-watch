# 引継書（2026-07-19 作成）

Apple整備済製品の出品監視→Discord通知ツール。前セッション（Claude Code リモート）からの引き継ぎ用。

## プロジェクト概要

- **リポジトリ**: `Yanagi-1112/mac-mini-refurb-watch`（現在 **Private**）
- **構成**: `check.py`（Python標準ライブラリのみ）を GitHub Actions のcron（30分ごと）で実行。Appleの整備済製品ページの埋め込みJSON（`REFURB_GRID_BOOTSTRAP`）から対象を抽出し、`state.json` と比較して新着をDiscord Webhookに通知（メンション付き）。`state.json` は Actions がリポジトリに自動コミット。
- **Secrets**: `DISCORD_WEBHOOK_URL`（Actionsシークレット。Public化しても非公開のまま）

## 現在の状態

- `main`: Mac mini のみ監視する旧版
- ブランチ `claude/mac-mini-refurb-watch-9mdbmg` → **PR #1（ドラフト・未マージ）**
  https://github.com/Yanagi-1112/mac-mini-refurb-watch/pull/1
- PR #1 の内容:
  - `check.py` を複数監視対象（`WATCHES` リスト）に一般化
  - **Mac mini（全モデル）** に加えて **MacBook Air（USキーボード搭載モデルのみ）** を監視対象に追加
  - US判定は正規表現 `(US|ＵＳ|英語|米国)[^、。]{0,12}キーボード` をタイルJSON全体に適用（タイトル以外に表記があるケースも拾う）。JIS表記は非対象
  - 全ページ取得成功後に通知→state保存の順に変更（片ページ失敗時の誤再通知防止）
  - テスト通知・READMEも両対象向けに更新
  - 模擬タイルデータで検証済み（US表記のみ通知・JIS/MacBook Pro除外・再通知なし）

## 未完了タスク（優先順）

1. **PR #1 のレビュー＆マージ**（ユーザー判断待ち）
2. **リポジトリのPublic化**（ユーザー了承済み・ユーザー操作待ち）
   - GitHub: Settings → General → Danger Zone → Change repository visibility → Public
   - API/MCPからは可視性変更不可のため必ず手動
3. **Public化を確認できたら通知周期を短縮**:
   `.github/workflows/check.yml` の cron を `*/30 * * * *` → `*/5 * * * *` に変更
   - ⚠️ **Privateのまま5分間隔にしないこと**（無料枠 月2,000分を大幅超過し、月の途中でActionsが停止して通知が止まる。30分維持はこの理由でユーザー確認済みの判断）
4. **ホスティングのリサーチはCodexに依頼予定**（ユーザーがCodex側で実行。依頼文は下記）

## 既知の注意点

- **USキーボードAirの実ページ表記は未検証**（出品自体が年数回レベルの稀さ。前セッションの実行環境からapple.comへ到達できず確認不能だった）。実際の出品で通知が漏れた場合、そのときのタイル表記を確認して `check.py` の `US_KEYBOARD_RE` を修正すること。
- リポジトリに60日コミットがないとGitHubがschedule実行を自動停止（state.json更新でほぼ回避される）。
- Actionsのcronは数分〜十数分遅延することがある（仕様）。
- 動作テスト: Actionsタブ → 該当ワークフロー → Run workflow（`test_notify` にチェックでDiscordにテスト通知）。ローカルは `python check.py`（`DISCORD_WEBHOOK_URL` 未設定ならドライラン）。

## Codexへのリサーチ依頼文（コピペ用）

> 軽量な定期実行スクレイパー（Python標準ライブラリのみ、5〜30分間隔のcron、1回数十秒、Apple整備品ページ取得→Discord Webhook通知）を動かす、コスパ最良のホスティングを徹底調査してほしい。日本在住の個人で、理想は完全無料、妥協しても月数百円以内。比較対象：(1) GitHub Actions（publicリポジトリなら無料）、(2) 常時無料枠クラウド（Oracle Cloud Always Free / GCP e2-micro・Cloud Scheduler / AWS Lambda+EventBridge / Cloudflare Workers Cron / Fly.io / Railway / Render / Koyeb / Val Town）、(3) 格安VPS（Hetzner・さくら・ConoHa・Vultr・WebARENA Indigo等の最安プラン）、(4) @levelsio が2025〜2026年にXでポストしたおすすめホスティング。各候補について、無料枠の条件と落とし穴（クレカ必須・アイドル停止・cron精度・無料枠の縮小履歴）、AppleによるデータセンターIPブロックのリスク、日本からの使いやすさを評価し、「無料ならこれ」「数百円ならこれ」の結論を出して。

## 前セッションの後始末（実施済み）

- PR #1 のwebhook監視・1時間ごとのセルフチェック（Public化検知→cron短縮の自動化）は**停止済み**。新セッションで引き継ぐ場合は、PR監視の再購読と「Public化されたら cron を */5 に変更」のタスクを改めて設定すること。
