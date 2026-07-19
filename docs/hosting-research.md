# ホスティング調査レポート（2026-07-20）

軽量定期実行スクレイパー（Python標準ライブラリのみ、5〜30分間隔cron、1回数十秒、Apple整備済ページ取得→Discord通知）のコスパ最良ホスティング調査。4観点（サーバーレス無料枠／無料VM・格安VPS／AppleのIPブロックリスク／levelsio推奨）を並列調査し統合。

## 結論

- **無料ならこれ: GitHub Actions（publicリポジトリ）— 現構成のまま**。publicならActionsは無料・無制限（[GitHub Docs](https://docs.github.com/en/actions/concepts/billing-and-usage)）。5分間隔化も無料枠の心配なし。移行の必要なし。
- **数百円ならこれ: WebARENA Indigo 768MBプラン（月額上限319円税込・初期費用/縛りなし・クレカ必須）**（[公式料金](https://web.arena.ne.jp/indigo/price/)※抜き取り検査で確認済み）。cron精度・常駐の自由度が欲しくなった場合の移行先。
- **完全無料のVMが欲しければ: Oracle Cloud Always Free（Ampere A1、東京リージョン可）**。ただし2026年6月に枠が2 OCPU/12GBへ半減（[Oracle公式docs](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)※検査済み）しており縮小トレンド。アイドル回収条件（7日間CPU/NW/メモリ全て20%未満）はこの用途なら通常回避可能。

## 各観点の要点

### 1. GitHub Actions・サーバーレス無料枠

- **GitHub Actions**: public=無料無制限。private=月2,000分（5分間隔だと月8,000分超で大幅超過→Public化必須という現方針は正しい）。scheduleは毎時0分付近に数分〜十数分遅延あり（仕様）。**60日間コミットがないとscheduleが自動停止**（[公式](https://docs.github.com/actions/managing-workflow-runs/disabling-and-enabling-a-workflow)※検査済み）— 本リポジトリはstate.json自動コミットでほぼ回避されるが、在庫変動ゼロが60日続くと止まりうる点は既知のとおり。
- Cloudflare Workers Cron: 無料枠は十分（アカウント5 cron・10ms CPU）だがPython WorkersはPyodideベースのBetaで`urllib`が使えず、JS書き直しが必要。
- AWS Lambda+EventBridge / GCP Cloud Run+Scheduler: 無料枠は十分だがクレカ必須＋構成が過剰。
- Val Town: Python非対応。Fly.io（2024年無料枠廃止）/ Railway（2023年廃止）/ Render（cronは最低$1/月）/ Koyeb（強制scale-to-zero）は不適。

### 2. 無料VM・格安VPS

| 候補 | 月額 | 備考 |
|---|---|---|
| Oracle Always Free A1 | ¥0 | クレカ登録必須（請求なし）。東京可。枠縮小トレンド・アイドル回収に注意 |
| GCP e2-micro | ¥0 | **米国3リージョン限定**（東京無料枠なし） |
| WebARENA Indigo 768MB | 最大319円 | 最安。クレカのみ。停止中も課金（削除必要） |
| ConoHa VPS 512MB | 460円〜 | クレカ以外の決済可（唯一）。日本語サポート |
| さくらのVPS 512MB | 590円 | **最低3ヶ月縛り** |
| Hetzner CX23 | €5.49+IPv4≒月900円強 | 2026-06値上げ。本人確認要求例あり・日本語なし |

### 3. AppleのデータセンターIPブロックリスク

- www.apple.com は **Akamai Bot Manager** 保護下。403（Access Denied）を返す実例報告あり（[pixeljets](https://pixeljets.com/blog/scrape-apple-com-for-refurbished-iphones-and-get-alerts/)）。
- ただし「GitHub Actions/AWS等のIPを名指しでブロックした」という直接証拠は**発見できず**（複数クエリで調査、未確認と正直に報告）。AWS Lambdaから低頻度で安定運用しているOSS実例（zmoog/refurbished、1日1回）あり。
- 5〜30分間隔は既存OSS実例（1日1回〜5時間おき）よりかなり高頻度である点は認識しておく。403が出始めたら: 間隔を戻す→指数バックオフ→（最終手段）住宅IP。
- 本リポジトリの実装では、403は`urllib`の例外→ワークフロー失敗として現れる（Actionsの失敗通知メールで気づける）。

### 4. levelsio（Pieter Levels）の2025〜2026年推奨

- 一貫して **Hetzner/DigitalOceanの$5 VPS＋Termius＋サーバー上でClaude Code直接実行**を公言（[2025-08](https://x.com/levelsio/status/1957518592284717558)等多数）。セキュリティはTailscale＋firewall絞り（443=Cloudflareのみ・22=Tailscaleのみ）＋fail2ban＋unattended-upgrades（[2026-03](https://x.com/levelsio/status/2033546675063554213)）。
- ただし本人が「**Hetznerはスクレイピング顧客を歓迎していない**」と2025-10に明言しており（[post](https://x.com/levelsio/status/1981413029754683593)）、スクレイパー用途でのHetzner推しは留保付き。
- 2025〜26年の投稿でcronへの明示的言及は見つからず（2019年の「208 cron jobs, 1 VPS」が最後）。

## 本プロジェクトへの適用

1. **現構成（GitHub Actions）を維持し、Public化→cron 5分化が最適解**。コスト0円・移行作業0。
2. Actionsランナー（Azure系IP）でのブロックが実際に観測されたら、そのとき初めてWebARENA Indigo（319円）またはOracle Always Freeへの移行を検討すればよい。移行してもコードはそのまま動く（標準ライブラリのみ・cron 1行）。

## 調査メタ情報

- 調査日: 2026-07-20。当初Codex CLIで実行したが利用枠切れのため、researcherサブエージェント4並列にフォールバックして実施。
- 抜き取り検査: 3件実施、3件とも一次ソースと一致（GitHub 60日停止規定／Oracle A1 2OCPU・12GB／Indigo 768MB・319円）。
- X投稿の日付はSnowflake IDから算出（本文はWeb検索スニペット経由の確認で確信度中〜高）。
