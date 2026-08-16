from unittest.mock import MagicMock, patch

import redis

from modules.redis_module import RedisConnector


class TestRedisConnector:
    def test_get_connection_builds_pool_from_configured_params(self) -> None:
        connector = RedisConnector(host="redis-host", port=6380, max_connections=5)

        with patch("modules.redis_module.redis.ConnectionPool") as mock_pool_cls:
            mock_pool_cls.return_value = MagicMock()
            conn = connector.get_connection()

        mock_pool_cls.assert_called_once_with(
            host="redis-host",
            port=6380,
            max_connections=5,
            decode_responses=True,
        )
        assert isinstance(conn, redis.Redis)

    def test_connection_pool_is_created_only_once(self) -> None:
        connector = RedisConnector()

        with patch("modules.redis_module.redis.ConnectionPool") as mock_pool_cls:
            mock_pool_cls.return_value = MagicMock()
            connector.get_connection()
            connector.get_connection()

        mock_pool_cls.assert_called_once()


class TestClose:
    def test_close_disconnects_the_pool(self) -> None:
        connector = RedisConnector()

        with patch("modules.redis_module.redis.ConnectionPool") as mock_pool_cls:
            pool = MagicMock()
            mock_pool_cls.return_value = pool
            connector.get_connection()
            connector.close()

        pool.disconnect.assert_called_once()

    def test_close_without_connection_is_noop(self) -> None:
        # プールを一度も作っていない状態で呼ばれても落ちないこと
        RedisConnector().close()

    def test_pool_is_rebuilt_after_close(self) -> None:
        connector = RedisConnector()

        with patch("modules.redis_module.redis.ConnectionPool") as mock_pool_cls:
            mock_pool_cls.return_value = MagicMock()
            connector.get_connection()
            connector.close()
            connector.get_connection()

        assert mock_pool_cls.call_count == 2
