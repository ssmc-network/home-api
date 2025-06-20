import json
import logging
import sys

from settings.config import settings


class LogJSONFormatter(logging.Formatter):
    """アプリケーションログのフォーマットクラス"""

    def format(self, record: logging.LogRecord) -> str:
        """アプリケーションログのフォーマットを指定"""
        log_data = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "message": record.getMessage(),
            "function": record.funcName,
        }

        return json.dumps(log_data, ensure_ascii=False)


def log_application(name: str) -> logging.Logger:
    """アプリケーションログのログ出力部"""
    logger = logging.getLogger(name)

    handler = logging.StreamHandler(stream=sys.stdout)
    formatter = LogJSONFormatter()
    handler.setFormatter(formatter)
    # ログレベルの選別
    logger.setLevel(settings.loglevel)
    logger.addHandler(handler)

    return logger
