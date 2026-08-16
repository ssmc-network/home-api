# CLAUDE.md

このファイルは、このリポジトリで作業する Claude Code (claude.ai/code) へのガイダンスを提供します。

## プロジェクトの状態

YouTubeの動画をダウンロードするためのFastAPI製REST API(`app/main.py`)。`POST /download` でURLを受け取ってRedisのキュー(`youtube_download_queue`)へ積み、バックグラウンドで yt-dlp を使って `settings.output_dir`(既定 `/data`)へmp4として保存する。タスクの進捗は `youtube_download_statuses` ハッシュへ `queued` → `processing` → `done`/`error` と書き込まれ、`GET /download/status` で参照できる。

**この `youtube_download_statuses` ハッシュが、通知ボット(`ssmc-network/home-discord-bot`)との唯一の連携点**であり、実質的なプロセス間の契約になっている。ボット側はこのハッシュをポーリングして状態変化をDiscordへ通知し、`done`/`error` になったタスクをRedisから削除する。値は `{"status": ..., "error": ..., "title": ...}` というJSON文字列で、ボット側は `status`/`error`/`title` の3キーを読む。**このスキーマを変更する場合は必ずボット側と同時に更新すること**(片方だけ変えると通知が壊れる)。なお、ボットが重複通知防止のために使う `youtube_download_notified_statuses` ハッシュはボット側の管轄で、このリポジトリからは触らない。

## コマンド

依存関係はPoetryで管理し、`dev` ターゲットのDockerコンテナ内(Python 3.13)で実行する。ローカルvenvのワークフローは用意されていない — コンテナを使うこと。

- 開発コンテナ起動: `docker compose up -d`(`compose.yml` を使用、`dev` ターゲットをビルドし `/bin/bash` に入る。Redis(`redis-service`)も一緒に起動する)
- コンテナ内でコマンド実行: `docker compose exec app <command>`、例: `docker compose exec app ruff check .`
- Lint: `ruff check .`(コンテナ内、`/usr/src/app` から実行)
- フォーマット: `ruff format .`
- 型チェック: `mypy .`(ただし後述の通り `[tool.mypy]` 設定が未整備で、CIでも実行していない)
- テスト: `pytest`(**現時点でテストは1件も無く、pytest自体が依存に入っていない**。CI(`test.yaml`)の `[ -d tests ]` ガードにより、`tests/` が無い間はスキップされる)
- 依存関係インストール(コンテナ内): `poetry install`(開発用)または `poetry install --without dev`(本番用)
- 本番ビルド: `docker build --target prd .` / `docker compose -f compose.prd.yml up`

## ブランチ運用とCI/CD

**ブランチモデル: GitHub Flow**(2026年8月に `main`/`release/<バージョン>` の2層モデルから移行した。移行の方針は兄弟リポジトリ `ssmc-network/home-discord-bot` に合わせている)。長期ブランチは `main` のみ(保護ブランチ、直pushは不可、常にデプロイ可能な状態を維持)。開発ブランチ(`feature/...`、`claude/...` など)は `main` から切り、PRで `main` へ直接マージする。

- **releaseブランチという中間ステージは廃止した**。以前は `release/<バージョン>` ブランチへのPRでテストが走り、そのブランチへのpushでDocker Hubへの公開まで行っていたため、「マージした瞬間に公開される」「バージョン番号がブランチ名に埋まっている」という運用上の窮屈さがあった。
- **「いつコードがmainに入るか」と「いつバージョンとして公開するか」を分離**している。`main` への継続的なマージ自体はDocker Hubへの公開を伴わない。公開したいタイミングで `release.yaml` を手動実行(`workflow_dispatch`)すると、`vX.Y.Z` 形式のgitタグ作成・GitHub Release作成・`build.yaml` の起動までを一括で行う(詳細は後述)。

**Claude CodeはPRのマージを実施しないこと。** PR(開発ブランチ→`main`)の作成はしてよいが、実際のマージ操作はユーザー側が行う。CIの確認・レビュー・不具合修正はこれまで通り主体的に行ってよいが、マージ自体は必ずユーザーの実施に委ねること。同様に、バージョンを公開するためのgitタグ作成もユーザー側の判断で行う(Claude Codeが独断でタグを切らない、`release.yaml` をClaude Codeが自発的に実行することもしない)。

**CI(`.github/workflows/`)** — home-discord-botの構成をベースに、このリポジトリの事情(ffmpegが必要、Dockerfileが未移行)へ合わせて調整している:

- `test.yaml` — `main` へのPRで実行(`workflow_dispatch` でも手動実行可)。`dev` ターゲットのDockerイメージをビルドし、その中で `ruff check .` / `ruff format --check .` / (`tests/` があれば)`pytest` を実行する。続けて `prd` ターゲットもpushせずローカルビルドし、Docker Hub OIDCでログインした上で Docker Scout(`docker scout cves`)による脆弱性スキャンを行う。結果はcritical/high のみに絞った上でそのPRへ固定マーカー(`<!-- docker-scout-report -->`)付きコメントとして投稿し、再実行時は新規コメントを増やさず上書きする(medium/lowを含む全件は `docker-scout-report-pr-<PR番号>` という名前のArtifactとして90日保持)。この脆弱性スキャンは意図的に `main` マージ前に置いている — マージ後(=Docker Hub公開後)に気づくのではなく、公開前に気づけるようにするため。`workflow_dispatch` での手動実行時は `context.issue.number` が無いためPRコメントはスキップし、結果はジョブの実行サマリー(`core.summary`)にのみ出力する。**移行前は `ruff format` を `--check` 無しで実行していたため、整形されていないコードがあっても常に成功する無意味なステップになっていた**(移行時に修正済み)。
- `build.yaml` — `v*.*.*` 形式のgitタグのpushで実行する(`main` へのpushではない)ほか、`workflow_dispatch`(`version` 入力、省略可)でも手動実行できる。バージョン番号は、`version` 入力があればそれを、無ければ `GITHUB_REF`(`refs/tags/vX.Y.Z`)から `v` プレフィックスを取り除いて得る(以前のような、ブランチ名 `release/<バージョン>` から切り出す方式はやめた)。`prd` ターゲットのイメージを `latest` とそのバージョンタグの両方でDocker Hubへpushする。脆弱性スキャンは `test.yaml` 側(PRの時点)に一本化しており、ここでは行わない(移行前はpush後にTrivyでスキャンしていた=公開後にしか気づけなかった)。
- `release.yaml` — `workflow_dispatch` のみ(`version` 必須、`target` 省略時は `main`、`dry_run` 省略時は `true`)。バージョン形式(`vX.Y.Z`)の検証、`target` のSHA解決、同名タグの重複チェックを行った上で `$GITHUB_STEP_SUMMARY` にリリース計画を出力する。`dry_run=true`(デフォルト)ではここで停止し、実際には何も作成しない。`dry_run=false` の場合のみ、annotated tagを作成・push → `gh release create --generate-notes` でGitHub Releaseを自動生成(リリースノートは前回タグからのマージ済みPRベースで自動生成されるため、手動で文章を用意する必要はない)→ `gh workflow run build.yaml --ref <version> -f version=<version>` で `build.yaml` を明示的に起動、の順で実行する。**`GITHUB_TOKEN` によるgit pushはGitHubの無限連鎖防止の仕様上 `push: tags:` トリガーを起動しない**ため、`build.yaml` を直接dispatchするこの最後のステップが必須(`workflow_dispatch`/`repository_dispatch` はこの防止策の対象外として明示的に許可されている)。

**Docker Hub認証(OIDC)**: 静的PAT(`secrets.DOCKER_TOKEN`)は使用しない。`docker/oidc-action@v1`(`with: connection-id: ${{ vars.DOCKERHUB_OIDC_CONNECTIONID }}`)でGitHub ActionsのOIDCトークンをDocker Hubで検証させ、短命アクセストークンを取得してから `docker/login-action` の `password` に渡す2段階構成(`username` はDocker Hub Organization名 `ssmcnetwork` 固定)。`DOCKERHUB_OIDC_CONNECTIONID` はリポジトリのActions **Variable**(Secretではない)。**`docker scout cves` はpush/pull先に関係なくローカルのみのイメージに対してもDocker Hubへのログインを要求する**ため、`test.yaml`(pushしない `prd` イメージのスキャン)にも `build.yaml` と同じOIDCログインステップが入っている。

**イメージ名が `ssmcnetwork/home-api` に変わった点に注意(重要)**: 移行前の `build.yaml` は `${{ github.repository }}` をそのままイメージ名に使っていたが、リポジトリがOrganizationへTransferされた結果それは `ssmc-network/home-api` となり、**Docker Hubの名前空間はハイフンを許容しないためpushできない状態だった**(GitHub Organization名 `ssmc-network` とDocker Hub Organization名 `ssmcnetwork` は完全一致しない — Docker Hub側の制約であり是正不可能)。移行にあたり、兄弟リポジトリと同じく `${{ github.repository }}` に依存させず `ssmcnetwork/home-api` 固定にした。Transfer以前の実績のある公開先は個人アカウント配下の `goegoe0212/home-api`(リポジトリのHomepageもそこを指したまま)なので、**このイメージを参照しているKubernetesのマニフェスト等がある場合は `ssmcnetwork/home-api` への追従が必要**。

**Docker Hub側の設定(このリポジトリではまだ未作成 — Docker Hubの管理画面はこのセッションから操作できないため、ユーザー側での設定が必要)**:

- Docker Hub OIDC connectionを**このリポジトリ専用に1つ**作成する(他リポジトリと使い回さない — ルールセットが1 connectionあたり最大5本までのため、および用途ごとに権限を絞りやすくするため)。connection名はリポジトリ名に合わせて `home-api` を推奨。
- ルールを2本設定する: `v*.*.*` タグのpush用(scope: `Image Push`)、`main` 向けPR(Docker Scout用、scope: `Image Pull`のみ)。
- **Subject claimは名前ベースではなくID埋め込み形式で登録すること(重要・ハマりどころ)**: 素直に `repo:ssmc-network/home-api:ref:refs/tags/v1.0.0` のような名前ベースで登録すると、実際にGitHub Actionsが発行するOIDCトークンとマッチせずログインに失敗する。[2026年7月15日のGitHubの仕様変更](https://github.blog/changelog/2026-04-23-immutable-subject-claims-for-github-actions-oidc-tokens/)以降、新規作成・リネーム・**Transfer**されたリポジトリではsub claimがOrganization ID・Repository IDを埋め込んだ「immutable形式」になる(このリポジトリは個人アカウントからOrganizationへTransfer済みのため該当する)。Organization ID(`ssmc-network`)は `174979090`、Repository ID(`home-api`)は `999545465` なので、2本のルールは次の値で登録する:
  - `v*.*.*` タグのpush用(scope: `Image Push`): `repo:ssmc-network@174979090/home-api@999545465:ref:refs/tags/*`
  - `main` 向けPR用(scope: `Image Pull`): `repo:ssmc-network@174979090/home-api@999545465:*`
- `DOCKERHUB_OIDC_CONNECTIONID` をリポジトリのActions Variables(Settings → Secrets and variables → Actions → Variables)に登録する。
- Docker Hub上に `ssmcnetwork/home-api` リポジトリが無ければ作成しておく。
- **この設定が済むまで `test.yaml` はOIDCログインのステップで失敗する**(Docker Scoutがログインを要求するため)。移行直後の最初のPRでCIが赤くなるのはこれが原因。
- 不要になった `secrets.DOCKER_TOKEN` は、他に参照箇所が無ければ削除してよい。

**依存関係の更新検知(Renovate)**: `renovate.json` でRenovateに監視させている。`enabledManagers` は `["dockerfile", "poetry", "github-actions"]`(Dockerfileのベースイメージ、`app/pyproject.toml`/`app/poetry.lock` のPython依存関係、`.github/workflows/*.yaml` 内の各アクション(`actions/checkout`等)のバージョン)。GitHub Flowのため、Renovateは特別な設定(`baseBranches`等)なしにデフォルトブランチ(`main`)へPRを送るだけでよい。RenovateのPRも`main`へのPRである以上 `test.yaml` が通常通りDocker Scoutの再スキャンも走らせるので、そのPR上で脆弱性が直ったかどうかも一緒に確認できる。

Dockerfileのベースイメージは `ARG PYTHON_IMAGE=python:3.13.12-slim-trixie` + `FROM ${PYTHON_IMAGE}` という形にしている。**バージョン番号だけをARGに入れて `python:${PYTHON_VERSION}-slim-trixie` のようにタグを組み立てる書き方だと、Renovateのdockerfileマネージャーが依存として認識できない**(`# renovate:` インラインアノテーションはcustom regexマネージャー用の機能であり、dockerfileマネージャー単体では効かない)ため、イメージ参照そのものをARGへ入れる兄弟リポジトリと同じ形に揃えた。なお `prd` ステージの `COPY --from=dependencies /usr/local/lib/python3.13/site-packages ...` はこのイメージのマイナーバージョンと結びついているので、python 3.14系へ上げる際はここも追従が必要(追従漏れはCOPY元が存在せずビルドエラーになるため、CIで気づける)。

**運用にはユーザー側で以下の設定が必要**(このセッションからは操作不可):

- Mend Renovate GitHub Appをこのリポジトリにインストールする(GitHub Marketplaceから)。
- リポジトリ設定(Settings → Dependencies)の **Silent mode をOFFにする** — ONのままだとRenovateは更新内容を計算するだけでDependency Dashboard IssueもPRも一切作成しない(兄弟リポジトリで実際に踏んだハマりどころ)。
- 兄弟リポジトリにある `hostRules`/`registryAliases`(`dhi.io` 用のDocker Hub資格情報)は、このリポジトリがまだ `dhi.io` を使っていないため入れていない。後述のDHI移行を行う際に、`DHI_IO_DOCKERHUB_PAT` の登録と併せて追加すること。

## アーキテクチャ

- **FastAPIアプリ**: `main.py` が `lifespan` で `RedisConnector().get_connection()` を `app.state.redis` に格納し、2つのrouterを `settings.prefix_url` 付きで登録する。`redoc_url=None`(ReDocは無効、Swagger UIのみ)。
  - `routers/operation_check.py` — 疎通確認用。`/`(docsへリダイレクト)、`/operation`、`/operation/ip`、`/operation/gzip-test`。
  - `routers/youtube_download_router.py` — 本体。`POST /download`、`GET /download/status`、`DELETE /download/all` と、yt-dlpを叩く処理(`process_queue`/`download_youtube`/`get_youtube_title`)。
- **キュー処理はリクエスト駆動**: `POST /download` が `BackgroundTasks` で `process_queue` を起動し、Redisのリスト(`youtube_download_queue`)が空になるまで `lpop` し続ける。**常駐ワーカーではないため、POSTが来ないと積まれたジョブは処理されない**(下記「既知の負債」参照)。
- **マルチステージDockerfile**: `base`(`python:3.13.12-slim-trixie`) → `dependencies` / `dev` / `prd`。`base` でffmpegをインストールしている(yt-dlpが映像と音声を別々に取得してmp4へマージするために必須)。ステージ名は兄弟リポジトリに合わせて `dev`/`prd` に統一している(以前は `develop`/`production`)。
- **Poetryの依存関係はシステムのsite-packagesへ直接インストール**(`poetry config virtualenvs.create false`)。poetry本体は `goegoe0212/poetry-image:latest` から `COPY --from` で持ち込んでいる。`prd` ステージは `dependencies` ステージから site-packages と `/usr/local/bin` を丸ごとコピーする。
- **Poetryのpackage-modeは無効化**(`app/pyproject.toml` の `package-mode = false`)— 配布可能なパッケージではなく、単なるアプリケーションとして扱っている。
- **JSON形式のアプリケーションログ**(`app/modules/log_module.py` の `log_application(name)`): `timestamp`/`level`/`message`/`function` の4キーを1行のJSONで出力する。`routers/youtube_download_router.py` は素の `logging.basicConfig` ではなくこの `log_application(__name__)` を使うこと。
- 両方のcomposeファイルで `TZ=Asia/Tokyo` を指定している — スケジューリングや時刻を扱う機能を追加する際もこれを維持すること。

## 既知の技術的負債(未対応)

基盤(ブランチ運用・CI/CD・Renovate)の移行を先に済ませたため、以下は**意図的に手つかずのまま残している**。着手する際はこの順序を目安にすること。

1. **テストが1件も無い** — pytest/pytest-cov自体が `app/pyproject.toml` の依存に入っていない。`test.yaml` の `[ -d tests ]` ガードにより現状はスキップされる。兄弟リポジトリと同様、`app/tests/` 配下にユニットテストを置き、`[tool.pytest.ini_options]` に `testpaths = ["tests"]` / `pythonpath = ["."]` を追加する。
2. **mypyの設定とCIステップが無い** — mypyはdev依存に入っているが `[tool.mypy]` セクションが無く、CIでも実行していない。兄弟リポジトリは `disallow_untyped_defs`/`warn_return_any` などを有効にした比較的厳格な設定を持つ。
3. **ruffの設定が兄弟と不一致** — このリポジトリは `select = ["ALL"]` + 巨大な `ignore` リスト、line-length 120、`target-version` 未指定。兄弟は `select = ["B", "E", "F", "I", "N", "W", "C90", "PL", "RUF", "UP"]`、line-length 119、`target-version = "py313"` という絞り込んだ構成。揃える場合はどちらに寄せるかの判断が要る。
4. **ログモジュールが兄弟より古い** — ファイル位置(`modules/log_module.py` vs 兄弟の `core/log_modules.py`)、タイムゾーン非対応(`settings.tz` が無く `formatTime` がUTC基準)、`service`/`tag`/`details`(引数・例外メッセージ・スタックトレース)が出力されない、`logger.propagate = False` 未設定、といった差分がある。加えてこちらはFastAPI/uvicornで動くため、兄弟にはあえて入れていない**uvicorn側のログ設定**(`log_config.yaml`、アクセスログのJSON化、ヘルスチェックの除外フィルタ)が別途必要になる。`zoneinfo` を使うなら `tzdata` の依存追加も併せて行うこと。
5. **DockerfileがDHI(Docker Hardened Images)へ未移行** — 兄弟は `dhi.io/python:3-debian-dev`/`dhi.io/python:3` をdigest固定で使い、`.venv` だけを最終イメージへ引き継ぐことでpoetryやpipを本番イメージから排除している。こちらは `python:3.13.12-slim-trixie` + `virtualenvs.create false` のままなので、**本番イメージにpipやビルド用依存が同梱されている**。また poetry の入手元が `goegoe0212/poetry-image:latest` という個人アカウントの浮動タグに依存している。
   - **移行の障壁: ffmpeg**。このアプリはyt-dlpのマージ処理にffmpegが必要だが、本番用の `dhi.io/python:3` は最小構成でパッケージマネージャを持たない。ビルドステージで用意した静的ビルドのffmpegをコピーする、本番も debian バリアントにする、といった判断が必要で、兄弟の構成をそのまま移植することはできない。
   - 移行時は `renovate.json` への `hostRules`/`registryAliases` 追加(`registryAliases: { "dhi.io": "dhi.io" }` が無いとRenovateは `dhi.io/python` を「Docker Hubのユーザー `dhi.io` のイメージ」と誤解釈して失敗する)と、両ワークフローへの `dhi.io` ログインステップ追加も必要。
6. **アプリ設計上の課題**:
   - キューの消化が `BackgroundTasks` によるリクエスト駆動で、POSTが来ないと処理されない。逆に同時POSTの分だけ並列にダウンロードが走り、同時実行数の制御が無い。
   - バックグラウンド処理へ `Request` オブジェクトをそのまま渡し、レスポンス送出後に `request.app.state.redis` を参照している。
   - `video_title if "video_title" in locals() else "unknown"` という `locals()` を使った実装。
   - `RedisConnector._initialize_pool` が `redis.ConnectionError` を捕まえて `HTTPException` を投げているが、**ConnectionPoolの生成はソケット接続を伴わない**(実際の接続は最初のコマンド発行時)ため、この例外処理は実質デッドコード。兄弟リポジトリでは既に同じ問題を認識して削除・コメント化済み。
   - `lifespan` に終了処理(Redis接続のクローズ)が無い。
   - `DELETE /download/all` はステータスハッシュしか消さないため、キュー(`youtube_download_queue`)に未処理ジョブが残っていると、その後のPOSTを契機に「ステータスの無いジョブ」が処理されうる。
