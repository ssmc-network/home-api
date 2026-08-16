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
- 型チェック: `mypy .`(**兄弟リポジトリと同じくCIでは実行していない**ため、ローカルで随時実行すること)
- テスト: `pytest`(**現時点でテストファイルは1件も無い**。pytest/pytest-cov と `[tool.pytest.ini_options]` は用意済みなので、`app/tests/` を作れば動く。CI(`test.yaml`)の `[ -d tests ]` ガードにより、`tests/` が無い間はスキップされる)
- 依存関係インストール(コンテナ内): `poetry install`(開発用)または `poetry install --without dev`(本番用)
- 本番ビルド: `docker build --target prd .` / `docker compose -f compose.prd.yml up`

## ブランチ運用とCI/CD

**ブランチモデル: GitHub Flow**(2026年8月に `main`/`release/<バージョン>` の2層モデルから移行した。移行の方針は兄弟リポジトリ `ssmc-network/home-discord-bot` に合わせている)。長期ブランチは `main` のみ(保護ブランチ、直pushは不可、常にデプロイ可能な状態を維持)。開発ブランチ(`feature/...`、`claude/...` など)は `main` から切り、PRで `main` へ直接マージする。

- **releaseブランチという中間ステージは廃止した**。以前は `release/<バージョン>` ブランチへのPRでテストが走り、そのブランチへのpushでDocker Hubへの公開まで行っていたため、「マージした瞬間に公開される」「バージョン番号がブランチ名に埋まっている」という運用上の窮屈さがあった。
- **「いつコードがmainに入るか」と「いつバージョンとして公開するか」を分離**している。`main` への継続的なマージ自体はDocker Hubへの公開を伴わない。公開したいタイミングで `release.yaml` を手動実行(`workflow_dispatch`)すると、`vX.Y.Z` 形式のgitタグ作成・GitHub Release作成・`build.yaml` の起動までを一括で行う(詳細は後述)。

**Claude CodeはPRのマージを実施しないこと。** PR(開発ブランチ→`main`)の作成はしてよいが、実際のマージ操作はユーザー側が行う。CIの確認・レビュー・不具合修正はこれまで通り主体的に行ってよいが、マージ自体は必ずユーザーの実施に委ねること。同様に、バージョンを公開するためのgitタグ作成もユーザー側の判断で行う(Claude Codeが独断でタグを切らない、`release.yaml` をClaude Codeが自発的に実行することもしない)。

**CI(`.github/workflows/`)** — home-discord-botの構成をベースに、このリポジトリの事情(ffmpegの取得元が `docker.io` にあるためログイン順序に制約がある — 後述)へ合わせて調整している:

- `test.yaml` — `main` へのPRで実行(`workflow_dispatch` でも手動実行可)。`dev` ターゲットのDockerイメージをビルドし、その中で `ruff check .` / `ruff format --check .` / (`tests/` があれば)`pytest` を実行する。続けて `prd` ターゲットもpushせずローカルビルドし、Docker Hub OIDCでログインした上で Docker Scout(`docker scout cves`)による脆弱性スキャンを行う。結果はcritical/high のみに絞った上でそのPRへ固定マーカー(`<!-- docker-scout-report -->`)付きコメントとして投稿し、再実行時は新規コメントを増やさず上書きする(medium/lowを含む全件は `docker-scout-report-pr-<PR番号>` という名前のArtifactとして90日保持)。この脆弱性スキャンは意図的に `main` マージ前に置いている — マージ後(=Docker Hub公開後)に気づくのではなく、公開前に気づけるようにするため。`workflow_dispatch` での手動実行時は `context.issue.number` が無いためPRコメントはスキップし、結果はジョブの実行サマリー(`core.summary`)にのみ出力する。**移行前は `ruff format` を `--check` 無しで実行していたため、整形されていないコードがあっても常に成功する無意味なステップになっていた**(移行時に修正済み)。
- `build.yaml` — `v*.*.*` 形式のgitタグのpushで実行する(`main` へのpushではない)ほか、`workflow_dispatch`(`version` 入力、省略可)でも手動実行できる。バージョン番号は、`version` 入力があればそれを、無ければ `GITHUB_REF`(`refs/tags/vX.Y.Z`)から `v` プレフィックスを取り除いて得る(以前のような、ブランチ名 `release/<バージョン>` から切り出す方式はやめた)。`prd` ターゲットのイメージを `latest` とそのバージョンタグの両方でDocker Hubへpushする。脆弱性スキャンは `test.yaml` 側(PRの時点)に一本化しており、ここでは行わない(移行前はpush後にTrivyでスキャンしていた=公開後にしか気づけなかった)。
- `release.yaml` — `workflow_dispatch` のみ(`version` 必須、`target` 省略時は `main`、`dry_run` 省略時は `true`)。バージョン形式(`vX.Y.Z`)の検証、`target` のSHA解決、同名タグの重複チェックを行った上で `$GITHUB_STEP_SUMMARY` にリリース計画を出力する。`dry_run=true`(デフォルト)ではここで停止し、実際には何も作成しない。`dry_run=false` の場合のみ、annotated tagを作成・push → `gh release create --generate-notes` でGitHub Releaseを自動生成(リリースノートは前回タグからのマージ済みPRベースで自動生成されるため、手動で文章を用意する必要はない)→ `gh workflow run build.yaml --ref <version> -f version=<version>` で `build.yaml` を明示的に起動、の順で実行する。**`GITHUB_TOKEN` によるgit pushはGitHubの無限連鎖防止の仕様上 `push: tags:` トリガーを起動しない**ため、`build.yaml` を直接dispatchするこの最後のステップが必須(`workflow_dispatch`/`repository_dispatch` はこの防止策の対象外として明示的に許可されている)。

**Docker Hub認証(OIDC)**: 静的PAT(`secrets.DOCKER_TOKEN`)は使用しない。`docker/oidc-action@v1`(`with: connection-id: ${{ vars.DOCKERHUB_OIDC_CONNECTIONID }}`)でGitHub ActionsのOIDCトークンをDocker Hubで検証させ、短命アクセストークンを取得してから `docker/login-action` の `password` に渡す2段階構成(`username` はDocker Hub Organization名 `ssmcnetwork` 固定)。`DOCKERHUB_OIDC_CONNECTIONID` はリポジトリのActions **Variable**(Secretではない)。Dockerfileのベースイメージが `dhi.io` から取得されるため、`dhi.io` へも同じOIDCトークンでログインしている(DHIはDocker Hubアカウントの認証情報をそのまま使う仕様のため、同一トークンで通る)。**`docker scout cves` はpush/pull先に関係なくローカルのみのイメージに対してもDocker Hubへのログインを要求する**ため、`test.yaml`(pushしない `prd` イメージのスキャン)にも `docker.io` へのログインステップが入っている。

**`docker.io` へのログインは必ずビルドより「後」に置くこと(重要・ハマりどころ)**: 兄弟リポジトリは `docker.io` と `dhi.io` の両方へビルド前にログインしているが、**このリポジトリで同じ順序にすると必ずビルドが落ちる**。`docker login docker.io` に成功すると、以降buildxは `docker.io` へのpull全てでその資格情報を使うようになるが、OIDC connectionのルールが権限を与えているのは `ssmcnetwork` 名前空間配下のリポジトリだけなので、名前空間外の公開イメージのpullが `401 Unauthorized: access token has insufficient scopes` で弾かれる(**匿名なら問題なく引けるイメージが、権限の狭いトークンで認証しに行ったせいで失敗する**)。兄弟リポジトリではベースイメージがすべて `dhi.io` 由来でビルド中に `docker.io` から何もpullしないためこの問題が表面化しないが、こちらは後述のffmpeg取得元(`mwader/static-ffmpeg`)を `docker.io` から引くため直撃する。そのため両ワークフローとも、ビルド前にログインするのは `dhi.io` のみとし、`docker.io` へのログインはビルド完了後(`test.yaml` ではDocker Scoutの直前、`build.yaml` ではpushの直前)に置いている。`build.yaml` が `docker/build-push-action` の `push: true` を使わず「`push: false, load: true` でビルド → ログイン → `docker push`」の3ステップに分かれているのはこのためで、意味もなく冗長にしているわけではない。

**イメージ名が `ssmcnetwork/home-api` に変わった点に注意(重要)**: 移行前の `build.yaml` は `${{ github.repository }}` をそのままイメージ名に使っていたが、リポジトリがOrganizationへTransferされた結果それは `ssmc-network/home-api` となり、**Docker Hubの名前空間はハイフンを許容しないためpushできない状態だった**(GitHub Organization名 `ssmc-network` とDocker Hub Organization名 `ssmcnetwork` は完全一致しない — Docker Hub側の制約であり是正不可能)。移行にあたり、兄弟リポジトリと同じく `${{ github.repository }}` に依存させず `ssmcnetwork/home-api` 固定にした。Transfer以前の実績のある公開先は個人アカウント配下の `goegoe0212/home-api`(リポジトリのHomepageもそこを指したまま)なので、**このイメージを参照しているKubernetesのマニフェスト等がある場合は `ssmcnetwork/home-api` への追従が必要**。

**Docker Hub側の設定(このリポジトリではまだ未作成 — Docker Hubの管理画面はこのセッションから操作できないため、ユーザー側での設定が必要)**:

- Docker Hub OIDC connectionを**このリポジトリ専用に1つ**作成する(他リポジトリと使い回さない — ルールセットが1 connectionあたり最大5本までのため、および用途ごとに権限を絞りやすくするため)。connection名はリポジトリ名に合わせて `home-api` を推奨。
- ルールを2本設定する: `v*.*.*` タグのpush用(scope: `Image Push`)、`main` 向けPR(Docker Scout用、scope: `Image Pull`のみ)。
- **Subject claimは名前ベースではなくID埋め込み形式で登録すること(重要・ハマりどころ)**: 素直に `repo:ssmc-network/home-api:ref:refs/tags/v1.0.0` のような名前ベースで登録すると、実際にGitHub Actionsが発行するOIDCトークンとマッチせずログインに失敗する。[2026年7月15日のGitHubの仕様変更](https://github.blog/changelog/2026-04-23-immutable-subject-claims-for-github-actions-oidc-tokens/)以降、新規作成・リネーム・**Transfer**されたリポジトリではsub claimがOrganization ID・Repository IDを埋め込んだ「immutable形式」になる(このリポジトリは個人アカウントからOrganizationへTransfer済みのため該当する)。Organization ID(`ssmc-network`)は `174979090`、Repository ID(`home-api`)は `999545465` なので、2本のルールは次の値で登録する:
  - `v*.*.*` タグのpush用(scope: `Image Push`): `repo:ssmc-network@174979090/home-api@999545465:ref:refs/tags/*`
  - `main` 向けPR用(scope: `Image Pull`): `repo:ssmc-network@174979090/home-api@999545465:*`
- `DOCKERHUB_OIDC_CONNECTIONID` をリポジトリのActions Variables(Settings → Secrets and variables → Actions → Variables)に登録する。
- Docker Hub上に `ssmcnetwork/home-api` リポジトリが無ければ作成しておく。
- Docker Hardened Images (DHI) はTeamライセンスの無料枠を利用する前提(エンタープライズ限定のミラーレジストリ機能は使わない)。ベースイメージは `dhi.io/python:3-debian-dev`(ビルド/開発用、pip・poetryが使える)と `dhi.io/python:3`(本番ランタイム用、最小構成)の2種類を使い分けている。
- 不要になった `secrets.DOCKER_TOKEN` は、他に参照箇所が無ければ削除してよい。

**イメージ更新の検知(digest固定 + Renovate)**: `dhi.io/python:3-debian-dev`・`dhi.io/python:3` はいずれも浮動タグ(タグ名は変わらないまま中身だけDocker側で更新される)なので、Dockerfileの `ARG PYTHON_DEV_IMAGE`/`PYTHON_PRD_IMAGE` は `@sha256:...` でdigest固定している。固定するだけだと更新に気づけないため、`renovate.json` でRenovateにDockerfileを監視させ、DHI側で新しいビルドが出るたびに「digestを更新するPR」が自動生成されるようにしている。`enabledManagers` は `["dockerfile", "poetry", "github-actions"]`(Dockerfileのベースイメージとffmpegイメージ、`app/pyproject.toml`/`app/poetry.lock` のPython依存関係、`.github/workflows/*.yaml` 内の各アクション(`actions/checkout`等)のバージョン)。GitHub Flowのため、Renovateは特別な設定(`baseBranches`等)なしにデフォルトブランチ(`main`)へPRを送るだけでよい。RenovateのPRも`main`へのPRである以上 `test.yaml` が通常通りDocker Scoutの再スキャンも走らせるので、そのPR上で脆弱性が直ったかどうかも一緒に確認できる。

**ARGにはバージョン番号ではなくイメージ参照そのものを入れること**: `python:${PYTHON_VERSION}-slim-trixie` のようにタグを組み立てる書き方だとRenovateのdockerfileマネージャーが依存として認識できない(`# renovate:` インラインアノテーションはcustom regexマネージャー用の機能であり、dockerfileマネージャー単体では効かない)。ffmpegイメージも同じ理由で `ARG FFMPEG_IMAGE` に完全な参照を入れ、`FROM ${FFMPEG_IMAGE} AS ffmpeg` として一度ステージ化してから `COPY --from=ffmpeg` している。

`dhi.io` のdigest確認にはRenovate側にもDocker Hubの静的な資格情報が必要(OIDCはRenovateからは使えないため)で、`renovate.json` の `hostRules` は `{{ secrets.DHI_IO_DOCKERHUB_PAT }}` というRenovateのシークレット参照になっている。**さらに、`hostRules` だけでは不十分で `registryAliases: { "dhi.io": "dhi.io" }` も必須**(重要・ハマりどころ): これが無いと、Renovateは `dhi.io/python` を「Docker Hubのユーザー `dhi.io` が持つ `python` イメージ」と誤解釈し、`dhi.io` ではなく素の `index.docker.io` へ問い合わせてしまい `Failed to look up docker package dhi.io/python: no-result` で失敗する(兄弟リポジトリで実際に踏んで確認済み)。**運用にはユーザー側で以下の設定が必要**(このセッションからは操作不可):

- Mend Renovate GitHub Appをこのリポジトリにインストールする(GitHub Marketplaceから)。
- MendのダッシュボードでこのリポジトリにRepository Secret `DHI_IO_DOCKERHUB_PAT`(Docker Hubの読み取り専用PAT、Organization Access Token推奨)を登録する。
- リポジトリ設定(Settings → Dependencies)の **Silent mode をOFFにする** — ONのままだとRenovateは更新内容を計算するだけでDependency Dashboard IssueもPRも一切作成しない(兄弟リポジトリで実際に踏んだハマりどころ)。
- 現在Dockerfileに埋め込まれている `dhi.io` のdigestは兄弟リポジトリで検証済みの値をそのまま流用している(同じレジストリの同じタグを参照しているため流用して問題ない)。手元で最新化する場合は `docker buildx imagetools inspect <image>` をCI経由(dhi.ioへログイン済みの環境)で実行して確認できる。

## アーキテクチャ

- **FastAPIアプリ**: `main.py` の `lifespan` がRedis接続を `app.state.redis` へ格納し、ダウンロードワーカーを起動し、2つのrouterを `settings.prefix_url` 付きで登録する。`redoc_url=None`(ReDocは無効、Swagger UIのみ)。
  - `routers/operation_check.py` — 疎通確認用。`/`(docsへリダイレクト)、`/operation`、`/operation/ip`、`/operation/gzip-test`。
  - `routers/youtube_download_router.py` — HTTP層のみ。`POST /download`、`GET /download/status`、`DELETE /download/all` の3エンドポイントで、Redis操作は `modules/download_queue.py` 越しに行う。
  - `modules/download_queue.py` — キュー(リスト)とステータス(ハッシュ)の読み書き、および常駐ワーカー(`run_worker`)。
  - `modules/youtube_module.py` — yt-dlpの呼び出し(`download_youtube`/`get_youtube_title`)。
- **キューの消化は常駐ワーカーが行う**: `lifespan` が `settings.download_workers` 本(既定1)のワーカータスクを起動し、各ワーカーが `blpop` でキューを待ち受ける。`POST /download` はキューへ積むだけで、ダウンロード自体には関与しない。**ワーカーの本数がそのまま同時ダウンロード数の上限**になる。Redisの `blpop` もyt-dlpのダウンロードもブロッキングなので、どちらも `asyncio.to_thread` でスレッドへ逃がしイベントループを止めない。**移行前は `POST /download` が `BackgroundTasks` で `process_queue` を起動する方式だったため、POSTが来ないと積まれたジョブが処理されず、逆に同時POSTの分だけ無制限に並列ダウンロードが走っていた**。
- **ワーカーの停止**: `lifespan` の終了時に停止フラグ(`asyncio.Event`)を立て、処理中のダウンロードが終わるのを `settings.worker_shutdown_timeout_seconds` まで待ってから、待ち切れなかったワーカーだけキャンセルする。ワーカーが `blpop` で待機している場合は最大 `settings.queue_pop_timeout_seconds` 秒で停止に反応する。最後に `RedisConnector.close()` でプールを切断する。
- **ワーカーは1件の失敗では止まらない**: ジョブ処理中の例外はステータスを `error` にした上で握り潰し、Redisの接続エラーは `settings.queue_error_backoff_seconds` 待ってから再試行する。**常駐ワーカーがループを抜けると以降のジョブが一切消化されなくなる**ため、意図的に広く捕捉している(移行前の `process_queue` はRedisエラーで `break` していたが、リクエスト毎に起動し直されるため問題にならなかった)。
- **マルチステージDockerfile**: `ffmpeg` / `base`(`dhi.io/python:3-debian-dev`) → `dependencies` → `dev-dependencies` → `dev` / `prd`。OpenShift向けのUBIベースイメージではなく、通常のKubernetes環境向けにDocker Hardened Images (DHI) を使用している。ビルド系のステージ(`base`/`dependencies`/`dev-dependencies`/`dev`)は開発ツール入りの `-debian-dev` バリアントを使うが、`prd` だけは `base` を継承せず最小構成の `dhi.io/python:3` から独立して作っている(実行時イメージに開発ツールを含めないため)。ステージ名は兄弟リポジトリに合わせて `dev`/`prd` に統一している(以前は `develop`/`production`)。
- **ffmpegは静的ビルドのバイナリを `mwader/static-ffmpeg` からCOPYする**: yt-dlpが映像と音声を別々に取得してmp4へマージするためにffmpegが必須だが、本番用の `dhi.io/python:3` は最小構成でパッケージマネージャを持たないため `apt-get install ffmpeg` ができない。このイメージが提供する `/ffmpeg`・`/ffprobe` は外部依存を持たない静的PIEバイナリなので、共有ライブラリを持ち込むことなくバイナリ2個のCOPYだけで済む。`dev`/`prd` の両ステージへ入れている。**このイメージは `docker.io` 由来のため、ワークフローのログイン順序に制約が生まれている**(前述の「`docker.io` へのログインは必ずビルドより後」を参照)。
- **Poetryの依存関係はプロジェクト内 `.venv` に分離**(`POETRY_VIRTUALENVS_CREATE=true` + `POETRY_VIRTUALENVS_IN_PROJECT=true`)。`dependencies` ステージで `poetry config virtualenvs.options.no-pip true` を設定し、`.venv` に `pip` 自体を含めない(本番イメージにpip由来の脆弱性が紛れ込むのを防ぐため)。`dev`/`prd` はいずれも `dependencies`/`dev-dependencies` ステージから `.venv` の中身だけを `COPY --from` で引き継ぎ、poetry自身やビルド専用の依存(setuptoolsなど)は最終イメージに含めない。`dev` は `dev-dependencies`(devグループ込み)から、`prd` は `dependencies`(本番依存のみ)から `.venv` をコピーする。**移行前は `poetry config virtualenvs.create false` でシステムのsite-packagesへ直接インストールし、poetry本体を `goegoe0212/poetry-image:latest` という個人アカウントの浮動タグから持ち込んでいた**が、DHI移行に伴いどちらも解消した。
- **`prd` は非rootユーザーで動作する**(DHIの最小イメージの仕様)。`settings.output_dir`(既定 `/data`)への書き込みが必要なので、**このイメージをKubernetes等へデプロイする際はボリュームが非rootのUIDから書き込める必要がある**(`fsGroup` の指定など)。移行前の `python:slim` ベースはrootで動いていたため、ここは運用上の非互換点。
- **`prd` にはシェルが無い**ため、`CMD` はexec形式で指定する必要がある(`python -m uvicorn ...`)。`docker compose exec` などでシェルに入ることもできないので、調査は `dev` イメージで行うこと。
- **Poetryのpackage-modeは無効化**(`app/pyproject.toml` の `package-mode = false`)— 配布可能なパッケージではなく、単なるアプリケーションとして扱っている。
- **Ruff/mypy/pytestの設定**: `app/pyproject.toml`。兄弟リポジトリと同一の内容に揃えている。Ruffは `select = ["ALL"]` + 広範な `ignore` リストではなく `select = ["B", "E", "F", "I", "N", "W", "C90", "PL", "RUF", "UP"]` という絞り込んだルールセット(line-length 119、`target-version = "py313"`)。mypyは `disallow_untyped_defs` / `warn_return_any` などを有効にした比較的厳格な設定。pytestは `testpaths = ["tests"]` / `pythonpath = ["."]`。**ruff/mypy自体のバージョンは揃えていない**(このリポジトリは ruff `^0.15.1` / mypy `^1.16.0`、兄弟は `^0.16.0` / `^2.0.0`)— 設定を新たに導入するタイミングでツールのメジャーバージョンまで同時に動かすと切り分けが難しくなるため、バージョンの追随はRenovateのPRに委ねている。
- **JSON形式のアプリケーションログ**(`app/core/log_modules.py` の `log_application(name)`): `TimeStampFormatter` が `settings.tz`(既定 `Asia/Tokyo`、compose の `TZ` 環境変数と揃える)を使ってタイムスタンプをローカル時刻のISO8601で出力し、`LogApplicationJSONFormatter` が `timestamp`/`level`/`message`/`service`/`tag`/`details`(`function`/`argument`/`error_message`/`stacktrace`)のJSONを1行で出力する。`routers/youtube_download_router.py` は素の `logging.basicConfig` ではなくこの `log_application(__name__)` を使うこと。**`zoneinfo` がタイムゾーンデータを解決できるよう `tzdata` を明示的に依存関係へ追加している** — これによりイメージ側のOS tzdata(`/usr/share/zoneinfo`)の有無に左右されなくなり、最小構成の `dhi.io/python:3` でもJSTで出力される(`PYTHONTZPATH=""` でOS側を無効化した状態でも `+09:00` で出ることを確認済み)。**移行前は `logging.Formatter.formatTime`(= libcのローカル時刻)に依存していたため、DHI移行によってログのタイムスタンプが黙ってUTCへ変わる懸念があった**が、この移行で解消している。
- 両方のcomposeファイルで `TZ=Asia/Tokyo` を指定している — スケジューリングや時刻を扱う機能を追加する際もこれを維持すること。

## 既知の技術的負債(未対応)

基盤(ブランチ運用・CI/CD・Renovate・Dockerfile・ログモジュール・Ruff/mypy/pytest設定)の移行を先に済ませたため、以下は**意図的に手つかずのまま残している**。着手する際はこの順序を目安にすること。

1. **テストファイルが1件も無い** — pytest/pytest-cov と `[tool.pytest.ini_options]` は導入済みなので、あとは `app/tests/` 配下にユニットテストを置くだけ。`test.yaml` の `[ -d tests ]` ガードにより、`tests/` が出来た時点で自動的にCIで走り始める。兄弟リポジトリの `app/tests/`(`test_main.py`/`test_redis_module.py`/`test_log_modules.py`)が参考になる。
2. **uvicorn側のログ設定が無い** — アプリケーションログ(`core/log_modules.py`)はJSON化したが、uvicornが出すアクセスログ・起動ログは素のままなので、1つのコンテナから2種類のフォーマットのログが出ている状態。`log_config.yaml` を用意してアクセスログもJSON化し、ヘルスチェックの除外フィルタを入れるとよい。**これはASGIサーバーを持たない兄弟リポジトリには存在しない、このリポジトリ固有の作業**(兄弟の `core/log_modules.py` にも対応物が無い)。
3. **mypyをCIで実行していない** — `[tool.mypy]` の設定自体は入っており `mypy .` はクリーンに通るが、`test.yaml` にステップが無いためローカルでしか実行されない。これは兄弟リポジトリと同じ状態(揃ってはいる)だが、CIで実行しないと徐々に壊れていくため、両リポジトリ揃ってステップを足すのが望ましい。
4. **複数レプリカ運用時の同時ダウンロード数** — 同時実行数はワーカー本数で制御しているが、これは**1プロセス内での上限**でしかない。レプリカを増やすとその数だけ並列度も倍加する(`blpop` によりジョブ自体の重複処理は起きない)。全体で上限を設けたい場合はRedis側にセマフォを持たせるなどの仕組みが要る。
5. **ダウンロード中にプロセスが落ちるとタスクが `processing` のまま残る** — `blpop` でキューから取り出した後にプロセスが停止すると、そのジョブはキューにもワーカーにも存在しないまま、ステータスだけ `processing` で残留する。厳密にやるなら処理中ジョブを別のリストへ退避する信頼性キュー(`lmove` を使うパターン)が必要。現状は `DELETE /download/all` で手動リセットする運用。
