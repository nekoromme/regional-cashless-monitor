# 地域キャッシュレス還元モニター

PayPay、楽天ペイ、d払い、au PAYの**公式キャンペーンページ**を、日本時間の毎日9:17・18:17に確認するGitHub Actions用モニターです。実運用では、既存のDiscord・Google Calendar用Secretを公開せず再利用するため、`nekoromme/tcg-box-monitor-public`の中継Workflowがこの公開コードを取得して実行します。

指定地域の還元キャンペーンが新しく掲載されたらDiscordへ通知し、Google Calendarには**開始日の1日だけ**予定を入れます。キャンペーン期間全体を予定で埋めません。

## 監視する決済と公式情報

| 決済 | 監視元 |
|---|---|
| PayPay | 「各自治体のキャンペーン」一覧（ポイント還元だけ。プレミアム商品券は除外） |
| 楽天ペイ | 公式キャンペーン一覧と該当する公式詳細ページ |
| d払い | 「街のお店を応援」一覧と該当する公式詳細ページ |
| au PAY | 公式メディアの自治体キャンペーン検索結果（最新3ページ）と公式記事 |

一覧のタイトルだけでは開始日を取れない場合に限り、対象候補の詳細ページも確認します。1日2回より多く取りに行かず、対象外だと一覧で分かるページは開かない設計です。

## 対象地域

### 県・都の全域キャンペーン

- 東北：青森県、岩手県、宮城県、秋田県、山形県、福島県
- 関東：茨城県、栃木県、群馬県、埼玉県、千葉県、東京都、神奈川県

ここでいう県名は、**県・都全域が対象になるキャンペーン**です。「岩手県の遠野市」「東京都の杉並区」のように県見出しの下へ載るだけの個別自治体は通知しません。

### 指定した市・地域

| 通知上の名前 | 公式ページで拾う表記 |
|---|---|
| 一関市 | 一関市、一関 |
| 奥州市（水沢） | 奥州市、奥州、水沢市、水沢 |
| 北上市 | 北上市、北上 |
| 花巻市 | 花巻市、花巻 |
| 盛岡市 | 盛岡市、盛岡 |
| 登米市（佐沼） | 登米市、登米、佐沼 |
| 気仙沼市 | 気仙沼市、気仙沼 |
| 大崎市 | 大崎市、大崎 |
| 石巻市 | 石巻市、石巻 |
| 仙台市 | 仙台市、仙台、青葉区、宮城野区、若林区、太白区、泉区 |

水沢は現在の自治体名である奥州市、佐沼は登米市として発表されることが多いため、両方の表記を同じ対象へまとめています。

## 通知と重複防止

- 初回の`auto`実行は`baseline`になり、すでに掲載中の案件を通知しません。
- 4社のどれか1社でも初回取得に失敗した場合は初期化を完了せず、全社を正常に読めるまで再試行します。
- 同じ公式URLは重ねて通知しません。
- 開始日、終了日、還元内容、名称、開催状況が変わった時は「更新」としてDiscordへ再通知します。
- すでに終了している案件を遅れて発見しても通知しません。
- 監視状態は`monitor-state`ブランチへ保存し、公開コードのコミット履歴を状態更新で汚しません。
- 状態JSONが壊れた場合は勝手に初期化せず停止します。全件を新着扱いする事故を避けるためです。
- 公式ページ取得が3回連続で失敗するとDiscordへ異常通知し、復旧時にも通知します。

Google Calendarの予定IDは公式URLから作ります。公式側で開始日が変更された場合は、新しい予定を増やさず、同じ予定を新しい日へ移動します。

## GitHubで必要な設定

### 1. Repository secrets

単独で動かす場合は、リポジトリの`Settings` → `Secrets and variables` → `Actions` → `Secrets`へ、Discord通知用のSecretを登録します。所有者環境では既存監視リポジトリの中継Workflowが同名Secretを利用するため、このリポジトリへの再登録は不要です。

| 名前 | 内容 | 用途 |
|---|---|---|
| `DISCORD_WEBHOOK_URL` | 通知先DiscordチャンネルのWebhook URL | Discord通知 |

Google CalendarをGitHub Actionsから直接更新したい場合だけ、次の2件も登録します。

| 名前 | 内容 | 用途 |
|---|---|---|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | GoogleサービスアカウントJSONの全文、またはBase64文字列 | Calendar認証 |
| `GOOGLE_CALENDAR_ID` | 登録先カレンダーのID | Calendar登録先 |

Secretの値は、公開リポジトリのコードや`.env`へ直接書かないでください。GitHubは登録済みSecretの中身を後から表示できないため、別リポジトリから自動コピーもできません。

Google Calendarを使うには、登録先カレンダーをサービスアカウントのメールアドレスへ「予定の変更」権限で共有しておきます。

このリポジトリの所有者環境では、中継Workflowが既存のGoogle用Secret 2件も再利用します。

通知先が未設定でも監視自体は止まりません。DiscordはWebhook追加後に未通知案件を再送し、Calendar直接連携が未設定なら診断ログへ`calendar_deferred`を残します。

### 2. Repository variable

同じ画面の`Variables`へ次を登録します。

| 名前 | 値 |
|---|---|
| `MONITOR_USER_AGENT_CONTACT` | `https://github.com/nekoromme/regional-cashless-monitor` |

取得先のアクセス記録へ、用途と連絡先が分かる名前を出すための設定です。

### 3. 初回実行

`Actions` → `Regional cashless campaign monitor` → `Run workflow`で、`auto`のまま実行します。

結果の`mode`が`baseline(auto)`で、4社すべての`status`が`ok`なら初期化成功です。この回はDiscord通知もカレンダー登録もしません。次から新規掲載だけを通知します。

所有者環境の定期実行と状態保存は`nekoromme/tcg-box-monitor-public`側で行います。このリポジトリのWorkflowは、二重取得を避けるため手動実行だけにしています。

中継Workflowは毎回、既存Discord Webhookへの読み取り確認とGoogle Calendarの参照確認を先に行います。試験メッセージや試験予定を作らず、Secretの失効・権限不足だけを検出します。失敗時の公開ログにはWebhook URLや認証JSONを出しません。

## 手動実行モード

| モード | 用途 |
|---|---|
| `auto` | 通常用。未初期化なら無通知baseline、初期化済みなら通常監視 |
| `dry-run` | 取得と解析だけ。通知、Calendar、状態更新をしない |
| `baseline` | 現在見える案件をすべて既知扱いにする |
| `run` | 通常監視を即時実行。未初期化なら安全のため停止 |

## ログの見方

実行の最後に、次のような集計を出します。

```json
{
  "mode": "run",
  "detected_campaigns": 2,
  "new_campaigns": 1,
  "updated_campaigns": 0,
  "expired_suppressed": 0,
  "discord_notifications": 1,
  "calendar_updates": 1,
  "provider_results": {
    "paypay": {"status": "ok", "campaigns": 1},
    "rakuten_pay": {"status": "ok", "campaigns": 0},
    "dpay": {"status": "ok", "campaigns": 0},
    "au_pay": {"status": "ok", "campaigns": 1}
  },
  "errors": []
}
```

各実行の`Artifacts`には、判定内容を1行1JSONで残した診断ログを30日保存します。Actionsが赤くなった時は、`provider_results`、`errors`、Artifactsの`source_error`と`provider_failed`を先に見てください。

## ローカルで確認する場合

Python 3.11以上で実行します。

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[test]"
python -m pytest
cashless-monitor --mode dry-run
```

`dry-run`はDiscordやGoogle Calendarへ送らず、公式ページを読めるかだけ確認します。

## 注意

公式サイトの構造変更や、JavaScriptだけで配信される掲載形式への変更があると取得に失敗することがあります。そのため、正常に0件なのか、一覧自体を読めなくなったのかを区別し、連続失敗通知と診断ログを備えています。ただし公式APIではなく公開ページの監視なので、将来も無修正で永久に動く保証はありません。
