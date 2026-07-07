"""Fixtures for the mrx_analyst test suite.

The parent tests/conftest.py still applies here (module-level pymrx/httpx_auth
stubs, FakeChatLLM/FakeStructuredLLM, fake_pymrx). This conftest overrides
`tmp_catalog` to target the NEW package's storage (the parent's targets the old
mrx.pipeline.catalog), so mrx_analyst tests never touch a real catalog dir.
"""

import pytest


@pytest.fixture(autouse=True)
def tmp_catalog(monkeypatch, tmp_path):
    """Redirect mrx_analyst.storage.catalog to a pytest tmp_path. Autouse for
    the same reason as the parent fixture: fetch/turn paths write to the
    catalog as a side effect, so any test exercising them would otherwise
    pollute the real .mrx_analyst_catalog/ at the repo root."""
    from mrx_analyst.storage import catalog

    catalog_dir = tmp_path / ".mrx_analyst_catalog"
    monkeypatch.setattr(catalog, "CATALOG_DIR", catalog_dir)
    monkeypatch.setattr(catalog, "DB_PATH", catalog_dir / "catalog.sqlite3")
    monkeypatch.setattr(catalog, "DATA_DIR", catalog_dir / "data")
    monkeypatch.setattr(catalog, "CHARTS_DIR", catalog_dir / "charts")
    monkeypatch.setattr(catalog, "ANSWERS_DIR", catalog_dir / "answers")
    return catalog


VALID_URL = (
    "https://market.risk.echonet/Market%20Risk%20Explorer/Market%20Risk%20Explorer.application"
    "?env=Production&viewid=6168&p1=EQDUSNLH&p1021=Current&p1029=Total"
    "&p1217=RowGrpRiskType&p27=2026-06-30&p28=2026-06-01&p13={risk}"
)


class FakeView:
    """A no-pymrx view: counts executions, param-dict fingerprint."""

    name = "fake"

    def __init__(self):
        self.executed = 0

    def validate(self, plan, **kw):
        pass

    def execute(self, plan):
        import pandas as pd
        self.executed += 1
        return pd.DataFrame({"Book": ["A", "B"], "value": [900.0, -150.0]})

    def fingerprint(self, plan):
        from urllib.parse import parse_qsl, urlparse
        return dict(parse_qsl(urlparse(plan.url).query))


@pytest.fixture
def fake_pymrx(monkeypatch):
    """Make pymrx.from_link(...).get_data() return a configurable dataframe
    (or raise), for tests exercising mrx_analyst.mrx.data_fetch. Patches
    from_link IN PLACE on the stubbed module object (data_fetch bound the
    module name at import time)."""
    import sys
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
