import asyncio
import json
from collections.abc import Callable, Iterator
from typing import Any

import fakeredis
import pytest
from fastapi.testclient import TestClient
from redis import ConnectionError as RedisConnectionError
from redis import RedisError

import main
from modules import download_queue as dq
from settings.config import settings


@pytest.fixture
def client(fake_redis: fakeredis.FakeRedis, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """ワーカーを起動しないTestClient。

    エンドポイント自体はキューへ積む/読むだけでダウンロードには関与しないため、
    download_workers=0 にしてワーカーを止めておく。こうするとPOSTしたタスクが
    テストの最中に勝手に processing へ進まず、アサーションが安定する。
    ワーカーの検証は test_download_queue.py 側で行う。
    """
    monkeypatch.setattr(settings, "download_workers", 0)
    monkeypatch.setattr(main, "RedisConnector", lambda: _StubConnector(fake_redis))
    with TestClient(main.app) as test_client:
        yield test_client


class _StubConnector:
    def __init__(self, conn: fakeredis.FakeRedis) -> None:
        self._conn = conn
        self.closed = False

    def get_connection(self) -> fakeredis.FakeRedis:
        return self._conn

    def close(self) -> None:
        self.closed = True


class TestLifespan:
    def test_starts_the_configured_number_of_workers(
        self, fake_redis: fakeredis.FakeRedis, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "download_workers", 2)
        monkeypatch.setattr(settings, "queue_pop_timeout_seconds", 1)
        monkeypatch.setattr(main, "RedisConnector", lambda: _StubConnector(fake_redis))

        started: list[str] = []
        monkeypatch.setattr(main, "run_worker", _recording_worker(started))

        with TestClient(main.app):
            pass

        assert len(started) == 2

    def test_closes_redis_on_shutdown(self, fake_redis: fakeredis.FakeRedis, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "download_workers", 0)
        connector = _StubConnector(fake_redis)
        monkeypatch.setattr(main, "RedisConnector", lambda: connector)

        with TestClient(main.app):
            assert connector.closed is False

        assert connector.closed is True

    def test_exposes_the_connection_on_app_state(
        self, fake_redis: fakeredis.FakeRedis, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "download_workers", 0)
        monkeypatch.setattr(main, "RedisConnector", lambda: _StubConnector(fake_redis))

        with TestClient(main.app) as test_client:
            assert test_client.app.state.redis is fake_redis  # type: ignore[attr-defined]


def _recording_worker(started: list[str]) -> Callable[..., Any]:
    """起動されたワーカー名を記録し、停止フラグが立つまで待つだけのダミーワーカー。"""

    async def _worker(_conn: object, stop_event: asyncio.Event, name: str) -> None:
        started.append(name)
        await stop_event.wait()

    return _worker


class TestDownloadEndpoint:
    def test_enqueues_and_returns_task_id(self, client: TestClient, fake_redis: fakeredis.FakeRedis) -> None:
        res = client.post("/download", json={"url": "https://example.test/v"})

        assert res.status_code == 200
        task_id = res.json()["task_id"]
        raw = fake_redis.hget(dq.REDIS_STATUS_KEY, task_id)
        assert isinstance(raw, str)
        assert json.loads(raw)["status"] == "queued"
        assert fake_redis.llen(dq.REDIS_QUEUE_KEY) == 1

    def test_rejects_payload_without_url(self, client: TestClient) -> None:
        assert client.post("/download", json={}).status_code == 422

    def test_returns_503_when_redis_is_unreachable(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(dq, "enqueue", _raiser(RedisConnectionError("接続できません")))

        res = client.post("/download", json={"url": "https://example.test/v"})

        assert res.status_code == 503
        assert res.json()["error"] == "Redisに接続できません"

    def test_returns_500_on_other_redis_errors(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(dq, "enqueue", _raiser(RedisError("boom")))

        assert client.post("/download", json={"url": "https://example.test/v"}).status_code == 500


class TestStatusEndpoint:
    def test_returns_all_statuses(self, client: TestClient, fake_redis: fakeredis.FakeRedis) -> None:
        dq.write_status(fake_redis, "task-1", "done", title="サンプル動画")

        res = client.get("/download/status")

        assert res.status_code == 200
        assert res.json() == {"task-1": {"status": "done", "error": None, "title": "サンプル動画"}}

    def test_returns_empty_object_when_no_tasks(self, client: TestClient) -> None:
        assert client.get("/download/status").json() == {}

    def test_returns_503_when_redis_is_unreachable(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(dq, "fetch_statuses", _raiser(RedisConnectionError("接続できません")))

        assert client.get("/download/status").status_code == 503

    def test_returns_500_on_unexpected_error(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(dq, "fetch_statuses", _raiser(ValueError("壊れたJSON")))

        res = client.get("/download/status")

        assert res.status_code == 500
        assert res.json()["error"] == "不明なエラー"


class TestDeleteAllEndpoint:
    def test_clears_statuses_and_queue(self, client: TestClient, fake_redis: fakeredis.FakeRedis) -> None:
        client.post("/download", json={"url": "https://example.test/v"})

        res = client.delete("/download/all")

        assert res.status_code == 200
        assert fake_redis.hgetall(dq.REDIS_STATUS_KEY) == {}
        assert fake_redis.llen(dq.REDIS_QUEUE_KEY) == 0

    def test_returns_503_when_redis_is_unreachable(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(dq, "clear_all", _raiser(RedisConnectionError("接続できません")))

        assert client.delete("/download/all").status_code == 503


class TestOperationCheckEndpoints:
    def test_root_redirects_to_docs(self, client: TestClient) -> None:
        res = client.get("/", follow_redirects=False)

        assert res.status_code == 307
        assert res.headers["location"].endswith("/docs")

    def test_operation_returns_hello_world(self, client: TestClient) -> None:
        assert client.get("/operation").json() == {"Hello": "World"}

    def test_operation_ip_returns_hostname_and_ip(self, client: TestClient) -> None:
        payload = client.get("/operation/ip").json()

        assert set(payload) == {"hostname", "ip"}

    def test_gzip_test_returns_large_payload(self, client: TestClient) -> None:
        assert len(client.get("/operation/gzip-test").json()["data"]) == 10000


class TestOpenApi:
    def test_schema_is_served(self, client: TestClient) -> None:
        assert client.get("/openapi.json").status_code == 200

    def test_redoc_is_disabled(self, client: TestClient) -> None:
        assert client.get("/redoc").status_code == 404


def _raiser(exc: Exception) -> Callable[..., Any]:
    """呼ばれると必ず指定の例外を送出する関数を返す(Redis障害の再現用)。"""

    def _raise(*_args: object, **_kwargs: object) -> Any:
        raise exc

    return _raise
