"""Offline checks of the real SDK. Fake HTTP transport; no account, network, or user files."""

from __future__ import annotations

import json
import sys


def run_checks():
    import httpx
    import openai
    from .agent import Packet, ResearchAgent
    from .connection import error_details

    def events(values):
        return b"".join(("event: " + value["type"] + "\ndata: " + json.dumps(value) + "\n\n").encode()
                        for value in values)

    base = {"id": "resp_offline", "object": "response", "created_at": 1, "model": "offline-model",
            "status": "in_progress", "output": [], "error": None, "incomplete_details": None}
    final = {**base, "status": "completed", "output": [{"type": "message", "id": "msg_offline",
        "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": "OK",
        "annotations": []}]}], "usage": {"input_tokens": 2, "output_tokens": 1, "total_tokens": 3}}
    checks = {}
    for case in ("completed", "quota_http", "quota_stream", "rate_stream", "failed_response"):
        def handler(_request):
            if case == "quota_http":
                return httpx.Response(429, json={"error": {"code": "credit_balance_exhausted",
                                      "message": "offline fixture"}})
            code = "rate_limit_exceeded" if case == "rate_stream" else "credit_balance_exhausted"
            if case == "completed":
                payload = [{"type": "response.created", "sequence_number": 0, "response": base},
                           {"type": "response.output_text.delta", "sequence_number": 1, "delta": "OK",
                            "item_id": "msg_offline", "output_index": 0, "content_index": 0, "logprobs": []},
                           {"type": "response.completed", "sequence_number": 2, "response": final}]
            elif case == "failed_response":
                payload = [{"type": "response.created", "sequence_number": 0, "response": base},
                           {"type": "response.failed", "sequence_number": 1,
                            "response": {**base, "status": "failed", "error": {"code": code, "message": "offline"}}}]
            else:
                payload = [{"type": "error", "error": {"code": code, "message": "offline fixture"}}]
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=events(payload))
        try:
            with openai.OpenAI(api_key="offline-placeholder-not-a-key", max_retries=0,
                http_client=httpx.Client(trust_env=False, transport=httpx.MockTransport(handler))) as client:
                result = ResearchAgent(client).run(Packet("offline check", (), mode="chat"),
                                                   "offline-model", on_text=lambda _: None)
            checks[case] = case == "completed" and result.answer == "OK"
        except Exception as exc:
            expected = "rate_limit" if case == "rate_stream" else "quota"
            checks[case] = case != "completed" and error_details(exc)["kind"] == expected
    return {"version": "0.5.1", "sdk": openai.__version__, "frozen": bool(getattr(sys, "frozen", False)),
            "network_used": False, "checks": checks, "passed": all(checks.values())}
