"""Module stubs required before any mrx_analyst import: pymrx (internal
package) and httpx_auth (environment-provided) are imported at module load by
mrx_analyst.mrx.data_fetch and mrx_analyst.common.llm, and neither exists in
the test environment."""

import sys
import types

if "pymrx" not in sys.modules:
    _pymrx_stub = types.ModuleType("pymrx")
    _pymrx_stub.from_link = lambda url: None
    sys.modules["pymrx"] = _pymrx_stub

if "httpx_auth" not in sys.modules:
    _httpx_auth_stub = types.ModuleType("httpx_auth")
    _httpx_auth_stub.OAuth2ClientCredentials = object
    sys.modules["httpx_auth"] = _httpx_auth_stub
