from types import SimpleNamespace as NS

import httpx
import pytest
from openai import OpenAI, NotFoundError, RateLimitError, AuthenticationError

from bioagent.agent import DEFAULT_MODEL
from bioagent.connection import discover_models, error_details, normalize_key
from bioagent.safety import SafetyError


def test_no_unverified_model_is_hardcoded():
    assert DEFAULT_MODEL == ""


def test_account_models_are_loaded_through_real_sdk_mock_transport():
    def handler(request):
        assert request.method == "GET" and request.url.path == "/v1/models"
        return httpx.Response(200, json={"object": "list", "data": [
            {"id": "gpt-account-model", "object": "model", "created": 2, "owned_by": "openai"},
            {"id": "gpt-account-model-2026-01-01", "object": "model", "created": 2, "owned_by": "openai"},
            {"id": "gpt-image-example", "object": "model", "created": 3, "owned_by": "openai"},
            {"id": "text-embedding-example", "object": "model", "created": 3, "owned_by": "openai"},
        ]})
    with OpenAI(api_key="mock-key-not-used", http_client=httpx.Client(transport=httpx.MockTransport(handler))) as client:
        assert discover_models(client) == ("gpt-account-model", "gpt-account-model-2026-01-01")


@pytest.mark.parametrize("error_type,status,code,expected", [
    (NotFoundError, 404, "model_not_found", "model_not_found"),
    (RateLimitError, 429, "insufficient_quota", "quota"),
    (RateLimitError, 429, "rate_limit_exceeded", "rate_limit"),
    (RateLimitError, 429, "credit_balance_exhausted", "quota"),
    (RateLimitError, 429, "project_spend_limit_exceeded", "spend_limit"),
    (RateLimitError, 429, "organization_spend_limit_exceeded", "spend_limit"),
    (RateLimitError, 429, "organization_usage_limit_exceeded", "usage_limit"),
    (AuthenticationError, 401, "invalid_api_key", "authentication"),
])
def test_api_error_categories_do_not_expose_response_bodies(error_type, status, code, expected):
    response = httpx.Response(status, request=httpx.Request("POST", "https://api.openai.com/v1/responses"),
                              headers={"x-request-id": "req_example"})
    exc = error_type("secret-key-must-not-leak", response=response,
                     body={"code": code, "message": "secret-key-must-not-leak"})
    details = error_details(exc)
    assert details["kind"] == expected
    assert "secret-key-must-not-leak" not in str(details)
    assert details["request_id"] == "req_example"


def test_key_copy_mistakes_and_url_are_handled_without_logging_the_value():
    assert normalize_key(" Bearer mock-key-long-enough ") == "mock-key-long-enough"
    for value in ("https://api.openai.com/v1", "invalid key with spaces", "", 123):
        with pytest.raises(SafetyError):
            normalize_key(value)


def test_offline_diagnostics_contains_no_key_or_reports(service=None):
    from bioagent.desktop_service import DesktopService
    broker = DesktopService()
    broker.api_key = "secret-not-for-diagnostics"
    broker.report = "private experiment record"
    diagnostic = broker.dispatch('diagnostics', {})
    assert diagnostic['local_check']['passed']
    assert diagnostic['local_check']['network_used'] is False
    assert "secret-not-for-diagnostics" not in str(diagnostic)
    assert "private experiment record" not in str(diagnostic)
