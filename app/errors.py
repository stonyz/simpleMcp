"""Stable management API errors shared with the administration UI."""
import json
from pathlib import Path

from fastapi import HTTPException

CATALOG = json.loads(Path(__file__).with_name("error_messages.json").read_text(encoding="utf-8"))

def message(code, **params):
    """Render the fixed English API message; language selection belongs to the UI."""
    return CATALOG[code]["en"].format(**params)


class ApiError(HTTPException):
    def __init__(self, status_code, code, **params):
        self.code = code
        self.params = params
        super().__init__(status_code=status_code, detail=message(code, **params))
