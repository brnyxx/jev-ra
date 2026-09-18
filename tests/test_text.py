import json

import httpx
import pytest

from jev_ra import config
from jev_ra.text import NeedsValue, TextHelperError, ValueBinder

FIELD = {"id": "e1", "label": "City", "role": "textbox", "value": "Zurich", "kind": "fill"}
HELPER_ENV = {"JEV_RA_TEXT_MODEL": "writer-mini", "JEV_RA_TEXT_BASE_URL": "https://writer.test/v1"}


def helper_response(content, status=200, calls=None):
    def handler(request):
        if calls is not None:
            calls.append(json.loads(request.read()))
        return httpx.Response(status, json={"choices": [{"message": {"content": content}}], "usage": {"total": 7}})

    return handler


def binder(values=None, env=None, handler=None, calls=None):
    transport = httpx.MockTransport(handler or helper_response('{"text": "helped"}', calls=calls))
    return ValueBinder(values, config=config.load(env or {}), transport=transport)


def test_a_host_value_is_chosen_and_spent_once():
    bound = binder({"city": "London", "email": "a@b.c"})
    value = bound.bind("city", FIELD, "book a flight")
    assert value.text == "London"
    assert bound.used == []
    bound.spend(value)
    assert bound.used == ["city"]
    assert set(bound.available()) == {"email"}
    with pytest.raises(NeedsValue):
        bound.bind("city", FIELD, "book a flight")


def test_a_value_stays_available_until_it_reaches_the_page():
    bound = binder({"city": "London"})
    bound.bind("city", FIELD, "book a flight")
    assert set(bound.available()) == {"city"}
    assert bound.bind("city", FIELD, "book a flight").text == "London"


def test_host_values_are_stringified():
    assert binder({"guests": 2}).bind("guests", FIELD, "goal").text == "2"


def test_no_fitting_value_and_no_helper_needs_a_value_from_the_host():
    with pytest.raises(NeedsValue) as raised:
        binder({"city": "London"}).bind(None, FIELD, "book a flight")
    detail = raised.value.detail
    assert detail["field"] == {"ref": "e1", "label": "City", "role": "textbox", "current_value": "Zurich"}
    assert detail["goal"] == "book a flight"
    assert detail["reason"] == "no supplied value fits this field"


def test_the_helper_is_never_called_when_a_supplied_value_fits():
    calls = []
    bound = binder({"city": "London"}, env=HELPER_ENV, calls=calls)
    assert bound.bind("city", FIELD, "goal").source == "values"
    assert calls == []
    assert bound.calls == []


def test_the_helper_supplies_a_value_when_nothing_fits():
    calls = []
    bound = binder({}, env=HELPER_ENV, calls=calls)
    value = bound.bind(None, FIELD, "book a flight", page={"title": "Booking", "text": "Booking form"})
    assert (value.text, value.source, value.model) == ("helped", "helper", "writer-mini")
    assert value.latency_ms >= 0
    assert bound.calls[0]["field"] == "City"
    assert calls[0]["model"] == "writer-mini"
    context = json.loads(calls[0]["messages"][1]["content"])
    assert context["goal"] == "book a flight"
    assert context["field"] == {"label": "City", "role": "textbox", "value": "Zurich"}


@pytest.mark.parametrize(
    "content",
    ['{"text": null}', '{"text": ""}', '{"text": 12}', '{"text": "x", "extra": 1}', "not json", '{"value": "x"}'],
)
def test_the_helper_json_contract_is_enforced(content):
    with pytest.raises(TextHelperError, match="text helper"):
        binder({}, env=HELPER_ENV, handler=helper_response(content)).bind(None, FIELD, "goal")


def test_an_over_long_helper_value_is_refused():
    handler = helper_response(json.dumps({"text": "x" * 2001}))
    with pytest.raises(TextHelperError, match="no usable field value"):
        binder({}, env=HELPER_ENV, handler=handler).bind(None, FIELD, "goal")


def test_a_failing_helper_still_escalates_as_needs_value():
    handler = helper_response('{"text": "x"}', status=500)
    with pytest.raises(NeedsValue, match="HTTP 500"):
        binder({}, env=HELPER_ENV, handler=handler).bind(None, FIELD, "goal")


def test_an_unreachable_helper_escalates_as_needs_value():
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(NeedsValue, match="unreachable"):
        binder({}, env=HELPER_ENV, handler=handler).bind(None, FIELD, "goal")
