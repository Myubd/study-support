# study-support

学習支援プラグインの最小実装。「新しいアプリを追加する手順そのものを検証する」
ステップ1として作られており、意図的に**学習ログを1件記録する機能だけ**を持つ。

`local_ai_core`を共通基盤として使う、このエコシステムで最初に確立した3つのパターン
(memory書き込み・schedule書き込み・権限が無くても本体機能は落とさない設計)を
そのまま踏襲しており、新しい設計パターンは追加していない。

## これが解決すること

科目ごとの学習時間・理解度を記録するだけの、小さな学習ログアプリ。ただし記録するだけでなく、
記録内容を他アプリ・共通基盤に還元する2つの仕組みを持つ。

- **苦手分野の推測**: 理解度が低い(2以下)科目が2回以上記録されたら、
  `memory:write:study.*`スコープで`study.weak_subjects`として共通メモリーに書き込む。
  条件を満たさなくなった場合(記録を消した等)は`forget()`で古い値を残さず消す。
- **復習予定の共有**: ログ登録時に復習日を指定すると、共通の`schedule_items`へ登録する。
  新しいオートメーショントリガーは追加しておらず、既存の`schedule_due_soon`が
  そのまま使える。

教材ファイルの添付(`documents:write`)はこのステップ1では未実装。最初から機能を
広げすぎない、というエコシステム全体の方針に沿っている。

## 権限(`plugin_manifest.json`)

| スコープ | 用途 |
|---|---|
| `schedule_items:read` | 他アプリの予定と重複しないよう復習予定を確認するため |
| `schedule_items:write` | 復習日を共通の予定表に登録するため |
| `memory:write:study.*` | 苦手分野の推測を他アプリと共有するため |
| `memory:read:study.*` | 過去の苦手分野を記録時の参考にするため |

いずれも未許可の状態でもログ記録そのものは失敗しない(該当機能だけが静かにスキップされ、
`schedule_synced`が`false`で返る)。gatewayの統合コンソール(「01 権限」)で許可・取り消しができる。

## エンドポイント

| メソッド | パス | 内容 |
|---|---|---|
| GET | `/` | 学習ログの記録・一覧画面(`static/index.html`) |
| GET | `/health` | ヘルスチェック(`{"ok": true, "profile_id": ...}`) |
| POST | `/logs` | ログを1件登録。`subject` `minutes` `understanding`(1〜5)`note` `review_date`(任意) |
| GET | `/logs` | 登録済みログの一覧(新しい順) |
| DELETE | `/logs/{id}` | ログを削除。復習予定があればあわせてキャンセル扱いにする |

## 起動方法

**単体で起動する場合**

```bash
pip install -r requirements.txt
pip install /path/to/local-ai-core   # local_ai_coreを別途インストールしておくこと
uvicorn main:app --port 8100
```

**docker-composeの一部として起動する場合**

umbrella repo(`life-support-os`)の`docker-compose.yml`に定義済み。

```bash
docker compose up -d study_support
```

`http://localhost:8100/` で単体アクセス、または`http://localhost:3000/`(gateway)に
ログインした上で`/api/study/*`経由でもアクセスできる。

環境変数(すべて任意):

| 変数名 | 意味 | 既定値 |
|---|---|---|
| `STUDY_DB_PATH` | このアプリ専用のSQLite DBパス(学習ログ本体) | `/app/data/study.db` |
| `LOCAL_AI_CORE_DB_PATH` | 共通`core.db`のパス。gateway等と必ず同じ値にする | OS既定の共有ディレクトリ |
| `LOCAL_AI_CORE_DEVICE_IDENTITY_PATH` | 共通`device_identity.json`のパス | 同上 |

## 制約(現時点)

- 教材ファイルの添付(`documents:write`)は未実装
- 専用フロントエンドはこの`static/index.html`のみ。gateway側に埋め込むマウントは
  無く、直接ポート(8100)でアクセスする運用
- `study_logs`テーブルは`schedule_synced`カラムの追加をPRAGMAベースの簡易マイグレーションで
  行っている。本格的なマイグレーション機構は`local_ai_core`側にのみ存在する
