"""Manual billing snapshot only. Never infer an account balance from token counts."""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import config
from pydantic import BaseModel, ConfigDict, Field


class Balance(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    amount: float | None = Field(default=None, ge=0, le=1_000_000)
    currency: Literal["USD", "CNY"] = "USD"


def read_balance():
    try:
        data = json.loads((Path(config.DATA_DIR) / 'bme-balance.json').read_text(encoding='utf-8'))
        validated = Balance.model_validate({k: data[k] for k in ('amount', 'currency')})
        return {**validated.model_dump(), 'recorded_at': str(data.get('recorded_at') or ''), 'source': 'manual'}
    except (OSError, ValueError, KeyError, TypeError):
        return {'amount': None, 'currency': 'USD', 'recorded_at': '', 'source': 'manual'}


def save_balance(value):
    payload = {**value.model_dump(), 'recorded_at': datetime.now(timezone.utc).isoformat(), 'source': 'manual'}
    config.atomic_write_text(Path(config.DATA_DIR) / 'bme-balance.json', json.dumps(payload))
    return payload
