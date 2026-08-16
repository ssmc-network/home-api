import io
import json
import logging

from core.log_modules import LogApplicationJSONFormatter, TimeStampFormatter, log_application


def _make_logger(name: str) -> tuple[logging.Logger, io.StringIO]:
    stream = io.StringIO()
    logger = logging.getLogger(name)
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler(stream)
    handler.setFormatter(LogApplicationJSONFormatter())
    logger.addHandler(handler)
    logger.propagate = False
    return logger, stream


class TestTimeStampFormatter:
    def test_format_time_uses_configured_timezone(self) -> None:
        formatter = TimeStampFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname=__file__, lineno=1, msg="msg", args=(), exc_info=None
        )
        record.created = 0

        # settings.tz のデフォルトは Asia/Tokyo (UTC+9) のため、epoch は 09:00 になる。
        # OS側のtzdataではなくPythonのtzdataパッケージで解決されるため、
        # 最小構成のコンテナイメージでもこの結果は変わらない。
        assert formatter.formatTime(record).startswith("1970-01-01T09:00:00")


class TestLogApplicationJSONFormatter:
    def test_emits_valid_json_with_expected_fields(self) -> None:
        logger, stream = _make_logger("test.log_modules.basic")

        logger.info("こんにちは")

        payload = json.loads(stream.getvalue())
        assert payload["level"] == "INFO"
        assert payload["message"] == "こんにちは"
        assert payload["service"] == "home-api"
        assert payload["tag"] == "application"
        assert payload["details"]["error_message"] is None
        assert payload["details"]["stacktrace"] is None

    def test_includes_exception_details(self) -> None:
        logger, stream = _make_logger("test.log_modules.exception")

        try:
            raise ValueError("boom")
        except ValueError:
            logger.exception("失敗しました")

        payload = json.loads(stream.getvalue())
        assert payload["level"] == "ERROR"
        assert payload["details"]["error_message"] == "boom"
        assert "ValueError: boom" in payload["details"]["stacktrace"]

    def test_message_is_not_escaped_to_ascii(self) -> None:
        logger, stream = _make_logger("test.log_modules.unicode")

        logger.info("日本語のメッセージ")

        # ensure_ascii=False で出力しているため、生の日本語がそのまま載る
        assert "日本語のメッセージ" in stream.getvalue()


class TestLogApplication:
    def test_returns_logger_that_does_not_propagate(self) -> None:
        logger = log_application("test.log_modules.factory")

        assert logger.propagate is False
        assert logger.handlers
