"""アプリケーションログをJSON形式で出力するためのモジュール。"""

import json
import logging
import sys
import traceback
import zoneinfo
from datetime import datetime
from typing import Any

from settings.config import settings


class TimeStampFormatter(logging.Formatter):
    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:  # noqa: N802
        local_tz = zoneinfo.ZoneInfo(settings.tz)
        ct = datetime.fromtimestamp(record.created, tz=local_tz)
        return ct.isoformat(timespec="milliseconds")


class LogApplicationJSONFormatter(TimeStampFormatter):
    def format(self, record: logging.LogRecord) -> str:
        details: dict[str, Any] = {
            "function": record.funcName,
            "argument": getattr(record, "argument", {}),
            "error_message": None,
            "stacktrace": None,
        }

        if record.exc_info:
            exc_type, exc_value, exc_traceback = record.exc_info
            details["error_message"] = str(exc_value)
            details["stacktrace"] = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))

        log_data = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "message": record.getMessage(),
            "service": settings.service,
            "tag": "application",
            "details": details,
        }
        return json.dumps(log_data, ensure_ascii=False)


def log_application(name: str) -> logging.Logger:
    """JSON形式でアプリケーションログを出力するロガーを返す。"""
    logger = logging.getLogger(name)
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(LogApplicationJSONFormatter())
    logger.setLevel(settings.loglevel)
    logger.addHandler(handler)
    logger.propagate = False
    return logger
