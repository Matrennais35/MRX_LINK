"""Shared fakes for testing the pipeline without a real LLM or pymrx."""

import sys
import types

import pytest

# mrx.generate_link, mrx.data_fetch, and mrx.connect_llm import pymrx/httpx_auth
# at module load time. Neither is installed in this environment (pymrx is an
# internal package; httpx_auth is environment-provided), so both are stubbed
# here, before any test module imports anything from `mrx`.
if "pymrx" not in sys.modules:
    _pymrx_stub = types.ModuleType("pymrx")
    _pymrx_stub.from_link = lambda url: None
    sys.modules["pymrx"] = _pymrx_stub

if "httpx_auth" not in sys.modules:
    _httpx_auth_stub = types.ModuleType("httpx_auth")
    _httpx_auth_stub.OAuth2ClientCredentials = object
    sys.modules["httpx_auth"] = _httpx_auth_stub


class FakeMessage:
    """Mimics a LangChain AIMessage/response: only `.content` is used."""

    def __init__(self, content):
        self.content = content


class FakeChatLLM:
    """Fake for smart_pandas.ask(), which calls llm.invoke(messages) -> response.content."""

    def __init__(self, responses):
        """`responses` is a list of content strings, one per call to invoke()."""
        self._responses = list(responses)
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)
        content = self._responses.pop(0) if len(self._responses) > 1 else self._responses[0]
        return FakeMessage(content)


class FakeStructuredLLM:
    """Fake for generate_link.get_link(), which calls
    llm.with_structured_output(MRXPlan) -> structured_llm.invoke(messages) -> MRXPlan.
    """

    def __init__(self, plans):
        """`plans` is a list of MRXPlan instances, one per call to invoke()."""
        self._plans = list(plans)
        self.calls = []

    def with_structured_output(self, schema):
        return self

    def invoke(self, messages):
        self.calls.append(messages)
        return self._plans.pop(0) if len(self._plans) > 1 else self._plans[0]


@pytest.fixture
def fake_pymrx(monkeypatch):
    """Make pymrx.from_link(...).get_data() return a configurable dataframe
    (or raise), for tests exercising mrx.data_fetch.

    mrx.data_fetch does `import pymrx` at module load time, which binds the
    name to whatever module object is in sys.modules at that moment.
    Replacing the sys.modules entry afterwards would NOT affect that
    already-bound name — so this patches `from_link` in place on the same
    module object instead of swapping sys.modules.
    """
    state = {"mode": "ok", "df": None}

    class _FakeLink:
        def get_data(self):
            if state["mode"] == "raises":
                raise RuntimeError("MRX API failure")
            if state["mode"] == "empty":
                import pandas as pd
                return pd.DataFrame()
            return state["df"]

    monkeypatch.setattr(sys.modules["pymrx"], "from_link", lambda url: _FakeLink())

    return state
