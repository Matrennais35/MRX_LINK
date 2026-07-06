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
    return catalog
