from types import SimpleNamespace as NS

import pytest

from bioagent.billing import UsageLedger
from bioagent.desktop_service import DesktopService
from bioagent.safety import SafetyError


def test_missing_balance_is_unknown_instead_of_zero_and_never_live():
    value = UsageLedger().snapshot()
    assert value['balance'] is None and value['live_balance'] is False
    assert value['needs_confirmation'] is True


@pytest.mark.parametrize('amount', ['NaN', 'Infinity', '-1', '1e4', '1000000000', '1.1234567', '', 12, None])
def test_invalid_amounts_are_rejected(amount):
    with pytest.raises(SafetyError):
        UsageLedger().confirm_balance(amount)


def test_balance_remains_an_exact_snapshot_and_becomes_stale_after_requests():
    ledger = UsageLedger()
    ledger.confirm_balance('123.456789')
    assert ledger.snapshot()['needs_confirmation'] is False
    ledger.request_started()
    ledger.record_usage(NS(input_tokens=1000, output_tokens=300))
    value = ledger.snapshot()
    assert value['balance'] == '123.456789'
    assert value['input_tokens'] == 1000 and value['output_tokens'] == 300
    assert value['needs_confirmation'] and value['requests_since_confirmation'] == 1
    assert value['requests_without_usage'] == 0
    assert ledger.confirm_balance('0')['balance'] == '0'


def test_failed_requests_are_not_treated_as_free():
    ledger = UsageLedger()
    ledger.request_started()
    ledger.record_usage(None)
    value = ledger.snapshot()
    assert value['requests'] == 1 and value['requests_without_usage'] == 1


def test_changing_api_key_discards_other_account_balance_and_usage():
    broker = DesktopService()
    broker.api_key, broker.models = 'offline-placeholder', ('mock-model',)
    broker.dispatch('set_balance', {'amount': '200'})
    with pytest.raises(SafetyError):
        broker.dispatch('connect', {'api_key': 'bad'})
    assert broker.dispatch('billing', {})['balance'] is None
    with pytest.raises(SafetyError):
        broker.dispatch('set_balance', {'amount': '200'})


def test_service_test_request_counts_actual_returned_usage(monkeypatch):
    broker = DesktopService()
    broker.api_key, broker.models = 'offline-placeholder', ('mock-model',)
    class Client:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        responses = NS(create=lambda **_: NS(status='completed', usage=NS(input_tokens=12, output_tokens=3)))
    monkeypatch.setattr('bioagent.desktop_service.openai_client', lambda _: Client())
    broker.dispatch('test_model', {'model':'mock-model'})
    value = broker.dispatch('billing', {})
    assert value['requests'] == 1 and value['input_tokens'] == 12 and value['output_tokens'] == 3
