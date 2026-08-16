import fakeredis
import pytest


@pytest.fixture
def fake_redis() -> fakeredis.FakeRedis:
    """テストごとに独立したインメモリRedis。

    decode_responses=True は本番の RedisConnector と揃えている(揃えないと
    bytes と str の差でテストだけ通る/落ちるという食い違いが起きる)。
    """
    return fakeredis.FakeRedis(decode_responses=True)
