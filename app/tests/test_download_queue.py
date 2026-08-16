import asyncio
import json
from collections.abc import Callable
from typing import Any

import fakeredis
import pytest
from redis import RedisError

from modules import download_queue as dq
from settings.config import settings


def _loads(raw: object) -> Any:
    """Redisから読んだ値をJSONとして解釈する(Noneでないことも併せて検査する)。"""
    assert isinstance(raw, str)
    return json.loads(raw)


def _status(fake_redis: fakeredis.FakeRedis, task_id: str) -> dict[str, Any]:
    payload: dict[str, Any] = _loads(fake_redis.hget(dq.REDIS_STATUS_KEY, task_id))
    return payload


async def _wait_until(predicate: Callable[[], bool], timeout: float = 5.0) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return False


class TestWriteStatus:
    def test_queued_payload_has_no_title_key(self, fake_redis: fakeredis.FakeRedis) -> None:
        dq.write_status(fake_redis, "task-1", "queued")

        # home-discord-bot は title が無いとき「タイトル取得中」へフォールバックする。
        # ここで title: null を書いてしまうとボットの表示が壊れるため、キーごと省く。
        assert _status(fake_redis, "task-1") == {"status": "queued", "error": None}

    def test_payload_keys_match_the_bot_contract(self, fake_redis: fakeredis.FakeRedis) -> None:
        dq.write_status(fake_redis, "task-1", "done", title="サンプル動画")

        assert _status(fake_redis, "task-1") == {"status": "done", "error": None, "title": "サンプル動画"}

    def test_error_payload_carries_message_and_title(self, fake_redis: fakeredis.FakeRedis) -> None:
        dq.write_status(fake_redis, "task-1", "error", title="サンプル動画", error="boom")

        assert _status(fake_redis, "task-1") == {"status": "error", "error": "boom", "title": "サンプル動画"}

    def test_status_is_overwritten_in_place(self, fake_redis: fakeredis.FakeRedis) -> None:
        dq.write_status(fake_redis, "task-1", "queued")
        dq.write_status(fake_redis, "task-1", "processing", title="サンプル動画")

        assert fake_redis.hlen(dq.REDIS_STATUS_KEY) == 1
        assert _status(fake_redis, "task-1")["status"] == "processing"


class TestEnqueue:
    def test_registers_status_and_queue_entry(self, fake_redis: fakeredis.FakeRedis) -> None:
        task_id = dq.enqueue(fake_redis, "https://example.test/v")

        assert _status(fake_redis, task_id)["status"] == "queued"
        assert fake_redis.llen(dq.REDIS_QUEUE_KEY) == 1
        assert _loads(fake_redis.lindex(dq.REDIS_QUEUE_KEY, 0)) == {
            "task_id": task_id,
            "url": "https://example.test/v",
        }

    def test_task_ids_are_unique(self, fake_redis: fakeredis.FakeRedis) -> None:
        ids = {dq.enqueue(fake_redis, "https://example.test/v") for _ in range(5)}

        assert len(ids) == 5

    def test_queue_preserves_fifo_order(self, fake_redis: fakeredis.FakeRedis) -> None:
        first = dq.enqueue(fake_redis, "https://example.test/1")
        dq.enqueue(fake_redis, "https://example.test/2")

        assert dq.pop_job(fake_redis) == {"task_id": first, "url": "https://example.test/1"}


class TestFetchStatuses:
    def test_returns_all_tasks_as_parsed_dicts(self, fake_redis: fakeredis.FakeRedis) -> None:
        dq.write_status(fake_redis, "task-1", "queued")
        dq.write_status(fake_redis, "task-2", "done", title="サンプル動画")

        statuses = dq.fetch_statuses(fake_redis)

        assert set(statuses) == {"task-1", "task-2"}
        assert statuses["task-2"]["title"] == "サンプル動画"

    def test_returns_empty_dict_when_no_tasks(self, fake_redis: fakeredis.FakeRedis) -> None:
        assert dq.fetch_statuses(fake_redis) == {}


class TestClearAll:
    def test_removes_both_statuses_and_pending_queue(self, fake_redis: fakeredis.FakeRedis) -> None:
        dq.enqueue(fake_redis, "https://example.test/v")

        dq.clear_all(fake_redis)

        # ステータスだけ消すとキューのジョブが「状態の無いジョブ」として
        # 後から処理されてしまうため、キューも必ず一緒に消す。
        assert fake_redis.hgetall(dq.REDIS_STATUS_KEY) == {}
        assert fake_redis.llen(dq.REDIS_QUEUE_KEY) == 0

    def test_is_noop_when_already_empty(self, fake_redis: fakeredis.FakeRedis) -> None:
        dq.clear_all(fake_redis)

        assert fake_redis.hgetall(dq.REDIS_STATUS_KEY) == {}


class TestPopJob:
    def test_returns_none_when_queue_is_empty(
        self, fake_redis: fakeredis.FakeRedis, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "queue_pop_timeout_seconds", 1)

        assert dq.pop_job(fake_redis) is None

    def test_removes_the_job_from_the_queue(self, fake_redis: fakeredis.FakeRedis) -> None:
        dq.enqueue(fake_redis, "https://example.test/v")

        dq.pop_job(fake_redis)

        assert fake_redis.llen(dq.REDIS_QUEUE_KEY) == 0


class TestProcessJob:
    def test_transitions_to_done(self, fake_redis: fakeredis.FakeRedis, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(dq, "get_youtube_title", lambda _url: "サンプル動画")
        monkeypatch.setattr(dq, "download_youtube", lambda _url, _dir: None)

        dq.process_job(fake_redis, {"task_id": "task-1", "url": "https://example.test/v"})

        assert _status(fake_redis, "task-1") == {"status": "done", "error": None, "title": "サンプル動画"}

    def test_writes_processing_before_downloading(
        self, fake_redis: fakeredis.FakeRedis, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[str] = []

        def _download(_url: str, _dir: str) -> None:
            seen.append(_status(fake_redis, "task-1")["status"])

        monkeypatch.setattr(dq, "get_youtube_title", lambda _url: "サンプル動画")
        monkeypatch.setattr(dq, "download_youtube", _download)

        dq.process_job(fake_redis, {"task_id": "task-1", "url": "https://example.test/v"})

        assert seen == ["processing"]

    def test_download_failure_keeps_resolved_title(
        self, fake_redis: fakeredis.FakeRedis, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _download(_url: str, _dir: str) -> None:
            raise RuntimeError("ダウンロード失敗")

        monkeypatch.setattr(dq, "get_youtube_title", lambda _url: "サンプル動画")
        monkeypatch.setattr(dq, "download_youtube", _download)

        dq.process_job(fake_redis, {"task_id": "task-1", "url": "https://example.test/v"})

        assert _status(fake_redis, "task-1") == {
            "status": "error",
            "error": "ダウンロード失敗",
            "title": "サンプル動画",
        }

    def test_failure_before_title_is_resolved_falls_back_to_unknown(
        self, fake_redis: fakeredis.FakeRedis, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _title(_url: str) -> str:
            raise RuntimeError("タイトル取得に失敗")

        monkeypatch.setattr(dq, "get_youtube_title", _title)

        dq.process_job(fake_redis, {"task_id": "task-1", "url": "https://example.test/v"})

        # 旧実装が locals() を覗いて判定していた分岐に相当する
        assert _status(fake_redis, "task-1")["title"] == "unknown"
        assert _status(fake_redis, "task-1")["status"] == "error"

    def test_does_not_raise_on_failure(self, fake_redis: fakeredis.FakeRedis, monkeypatch: pytest.MonkeyPatch) -> None:
        def _title(_url: str) -> str:
            raise RuntimeError("boom")

        monkeypatch.setattr(dq, "get_youtube_title", _title)

        # 呼び出し元(ワーカー)を落とさないこと
        dq.process_job(fake_redis, {"task_id": "task-1", "url": "https://example.test/v"})


class TestRunWorker:
    """常駐ワーカーの検証。

    ワーカーはキューが空でも回り続けるので、テストごとに停止フラグを立てて
    確実に終了させる。blpop の待ち時間は短く上書きし、テストが遅くならない
    ようにしている。
    """

    @staticmethod
    def _drive(fake_redis: fakeredis.FakeRedis, predicate: Callable[[], bool], timeout: float = 5.0) -> bool:
        async def _scenario() -> bool:
            stop_event = asyncio.Event()
            task = asyncio.create_task(dq.run_worker(fake_redis, stop_event, "test-worker"))
            try:
                return await _wait_until(predicate, timeout)
            finally:
                stop_event.set()
                await asyncio.wait_for(task, timeout=10)

        return asyncio.run(_scenario())

    def test_processes_a_job_already_in_the_queue(
        self, fake_redis: fakeredis.FakeRedis, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "queue_pop_timeout_seconds", 1)
        monkeypatch.setattr(dq, "get_youtube_title", lambda _url: "サンプル動画")
        monkeypatch.setattr(dq, "download_youtube", lambda _url, _dir: None)
        task_id = dq.enqueue(fake_redis, "https://example.test/v")

        # 起動時点で既に積まれていたジョブが、POSTを一切受けずに処理されること。
        # 旧実装(BackgroundTasks)ではPOSTが来るまで処理されなかった。
        done = self._drive(fake_redis, lambda: _status(fake_redis, task_id)["status"] == "done")

        assert done

    def test_keeps_running_after_a_failing_job(
        self, fake_redis: fakeredis.FakeRedis, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "queue_pop_timeout_seconds", 1)
        monkeypatch.setattr(dq, "download_youtube", lambda _url, _dir: None)
        monkeypatch.setattr(
            dq,
            "get_youtube_title",
            lambda url: (_ for _ in ()).throw(RuntimeError("boom")) if "bad" in url else "サンプル動画",
        )
        bad = dq.enqueue(fake_redis, "https://example.test/bad")
        good = dq.enqueue(fake_redis, "https://example.test/good")

        # 1件目の失敗でワーカーが抜けると2件目が永久に処理されない
        finished = self._drive(
            fake_redis,
            lambda: _status(fake_redis, bad)["status"] == "error" and _status(fake_redis, good)["status"] == "done",
        )

        assert finished

    def test_retries_after_a_redis_error(
        self, fake_redis: fakeredis.FakeRedis, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "queue_pop_timeout_seconds", 1)
        monkeypatch.setattr(settings, "queue_error_backoff_seconds", 0.05)
        monkeypatch.setattr(dq, "get_youtube_title", lambda _url: "サンプル動画")
        monkeypatch.setattr(dq, "download_youtube", lambda _url, _dir: None)

        calls = {"count": 0}
        real_pop = dq.pop_job

        def _flaky_pop(client: fakeredis.FakeRedis) -> dict | None:
            calls["count"] += 1
            if calls["count"] == 1:
                raise RedisError("接続できません")
            return real_pop(client)

        monkeypatch.setattr(dq, "pop_job", _flaky_pop)
        task_id = dq.enqueue(fake_redis, "https://example.test/v")

        # Redisエラーでループを抜けてしまうと、以降のジョブが一切消化されなくなる
        done = self._drive(fake_redis, lambda: _status(fake_redis, task_id)["status"] == "done")

        assert done
        assert calls["count"] >= 2

    def test_stops_when_the_stop_event_is_set(
        self, fake_redis: fakeredis.FakeRedis, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "queue_pop_timeout_seconds", 1)

        async def _scenario() -> None:
            stop_event = asyncio.Event()
            task = asyncio.create_task(dq.run_worker(fake_redis, stop_event, "test-worker"))
            await asyncio.sleep(0.1)
            stop_event.set()
            # blpop のタイムアウト内に自力で終了すること(キャンセル不要)
            await asyncio.wait_for(task, timeout=10)
            assert task.done()
            assert not task.cancelled()

        asyncio.run(_scenario())
