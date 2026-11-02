"""Exercise the installed SDK's actual SSE decoder, rather than a fake stream object."""

import json

import httpx
import pytest
from openai import OpenAI

from bioagent.agent import Packet, ResearchAgent
from bioagent.connection import error_details
from bioagent.library import Evidence


def sse(events):
    return b"".join(("event: " + event["type"] + "\ndata: " + json.dumps(event) + "\n\n").encode()
                    for event in events)


def completed_events():
    response = {"id": "resp_offline", "object": "response", "created_at": 1,
                "model": "mock-model", "status": "in_progress", "output": [],
                "error": None, "incomplete_details": None}
    part = {"type": "output_text", "text": "", "annotations": [], "logprobs": []}
    message = {"type": "message", "id": "msg_offline", "role": "assistant",
               "status": "in_progress", "content": []}
    final_message = {**message, "status": "completed", "content": [{**part, "text": "OK"}]}
    return [
        {"type": "response.created", "response": response, "sequence_number": 0},
        {"type": "response.output_item.added", "item": message, "output_index": 0, "sequence_number": 1},
        {"type": "response.content_part.added", "part": part, "item_id": "msg_offline",
         "output_index": 0, "content_index": 0, "sequence_number": 2},
        {"type": "response.output_text.delta", "delta": "OK", "item_id": "msg_offline",
         "output_index": 0, "content_index": 0, "sequence_number": 3, "logprobs": []},
        {"type": "response.completed", "sequence_number": 4,
         "response": {**response, "status": "completed", "output": [final_message],
                      "usage": {"input_tokens": 2, "output_tokens": 1, "total_tokens": 3}}},
    ]


def test_actual_sdk_sse_decoder_and_agent_complete_without_network():
    def handler(request):
        payload = json.loads(request.content)
        assert payload["stream"] is True and payload["store"] is False
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse(completed_events()))
    parts = []
    with OpenAI(api_key="offline-placeholder", max_retries=0,
                http_client=httpx.Client(transport=httpx.MockTransport(handler))) as client:
        result = ResearchAgent(client).run(Packet("q", (), mode="chat"), "mock-model", on_text=parts.append)
    assert result.answer == "OK" and parts == ["OK"]


@pytest.mark.parametrize("code,expected", [("credit_balance_exhausted", "quota"),
                                         ("rate_limit_exceeded", "rate_limit")])
def test_stream_api_errors_keep_their_actual_category(code, expected):
    def handler(_request):
        return httpx.Response(200, headers={"content-type": "text/event-stream", "x-request-id": "req_offline"},
            content=sse([{"type": "error", "error": {"code": code, "type": "insufficient_quota",
                         "message": "private-body-not-for-display"}}]))
    with OpenAI(api_key="offline-placeholder", max_retries=0,
                http_client=httpx.Client(transport=httpx.MockTransport(handler))) as client:
        with pytest.raises(Exception) as error:
            ResearchAgent(client).run(Packet("q", (), mode="chat"), "mock-model", on_text=lambda _: None)
    details = error_details(error.value)
    assert details["kind"] == expected
    assert "private-body" not in str(details)


def test_streamed_tool_call_round_trip_only_reads_approved_evidence():
    calls = []
    def handler(request):
        payload = json.loads(request.content)
        calls.append(payload)
        if len(calls) == 1:
            final = completed_events()[-1]['response']
            response = {**final, 'output': [{'type':'function_call', 'id':'fc_local',
                'call_id':'call_local', 'name':'read_evidence', 'arguments':'{"evidence_id":"S001-C0001"}',
                'status':'completed'}]}
            events = [{'type':'response.completed', 'response':response, 'sequence_number':0}]
        else:
            outputs = [item for item in payload['input'] if item.get('type') == 'function_call_output']
            assert len(outputs) == 1 and outputs[0]['call_id'] == 'call_local'
            assert 'approved fixture' in outputs[0]['output']
            events = completed_events()
        return httpx.Response(200, headers={'content-type':'text/event-stream'}, content=sse(events))
    packet = Packet('summarize', (Evidence('S001-C0001', 'demo.md', '1', 'approved fixture', 'a'*64),))
    from bioagent.billing import UsageLedger
    ledger = UsageLedger()
    with OpenAI(api_key='offline-placeholder', max_retries=0,
                http_client=httpx.Client(transport=httpx.MockTransport(handler))) as client:
        result = ResearchAgent(client).run(packet, 'mock-model', on_text=lambda _:None,
                                          on_request=ledger.request_started, on_usage=ledger.record_usage)
    assert result.calls == ('read_evidence',) and result.answer == 'OK' and len(calls) == 2
    assert ledger.snapshot()['requests'] == 2
    assert ledger.snapshot()['input_tokens'] == 4 and ledger.snapshot()['output_tokens'] == 2


@pytest.mark.parametrize('nested', [False, True])
def test_failed_response_and_flat_error_event_retain_codes(nested):
    def handler(_request):
        if nested:
            final = completed_events()[-1]['response']
            event = {'type':'response.failed', 'sequence_number':0,
                'response':{**final, 'status':'failed', 'error':{'code':'server_error', 'message':'private'}}}
        else:
            event = {'type':'error', 'sequence_number':0, 'code':'server_error', 'message':'private', 'param':None}
        return httpx.Response(200, headers={'content-type':'text/event-stream', 'x-request-id':'req_offline'}, content=sse([event]))
    with OpenAI(api_key='offline-placeholder', max_retries=0,
                http_client=httpx.Client(transport=httpx.MockTransport(handler))) as client:
        with pytest.raises(Exception) as error:
            ResearchAgent(client).run(Packet('q', (), mode='chat'), 'mock-model', on_text=lambda _:None)
    details = error_details(error.value)
    assert details['kind'] == 'server' and details['request_id'] == 'req_offline'
    assert 'private' not in str(details)
