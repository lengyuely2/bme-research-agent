"""Local balance snapshots and returned token counts; never infer a live account balance."""

import re
from datetime import datetime, timezone
from decimal import Decimal

from .safety import SafetyError


class UsageLedger:
    def __init__(self):
        self.balance = None
        self.confirmed_at = None
        self.confirmed_request = 0
        self.requests = 0
        self.reported_requests = 0
        self.input_tokens = 0
        self.output_tokens = 0

    def confirm_balance(self, value):
        if not isinstance(value, str) or not re.fullmatch(r"\d{1,9}(?:\.\d{1,6})?", value.strip()):
            raise SafetyError("请填写官方账单页显示的非负美元余额，最多保留 6 位小数。")
        self.balance = format(Decimal(value.strip()), "f")
        self.confirmed_at = datetime.now(timezone.utc).isoformat()
        self.confirmed_request = self.requests
        return self.snapshot()

    def request_started(self):
        self.requests += 1

    def record_usage(self, usage):
        if usage is None:
            return
        incoming = getattr(usage, "input_tokens", None)
        outgoing = getattr(usage, "output_tokens", None)
        if any(not isinstance(x, int) or isinstance(x, bool) or x < 0 for x in (incoming, outgoing)):
            return
        self.reported_requests += 1
        self.input_tokens += incoming
        self.output_tokens += outgoing

    def snapshot(self):
        return {"balance": self.balance, "currency": "USD", "confirmed_at": self.confirmed_at,
                "requests_since_confirmation": self.requests - self.confirmed_request if self.balance is not None else None,
                "needs_confirmation": self.balance is None or self.requests > self.confirmed_request,
                "requests": self.requests, "reported_requests": self.reported_requests,
                "requests_without_usage": max(0, self.requests - self.reported_requests),
                "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                "source": "manual_official_billing_snapshot", "live_balance": False}
