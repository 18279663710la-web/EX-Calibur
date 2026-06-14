from datetime import datetime, timezone
from typing import Any


class Envelope:
    @staticmethod
    def success(data: Any = None, message: str = "success", code: int = 200) -> dict:
        return {
            "code": code,
            "message": message,
            "data": data,
            "meta": {
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        }

    @staticmethod
    def error(code: int, message: str, data: Any = None) -> dict:
        return {
            "code": code,
            "message": message,
            "data": data,
            "meta": {
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        }
