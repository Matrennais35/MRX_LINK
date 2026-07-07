import os
import httpx
from httpx_auth import OAuth2ClientCredentials
from langchain_openai import AzureChatOpenAI


def get_llm(model: str, version: str, reasoning_effort="high"):
    # NOTE: pass reasoning_effort=None to OMIT the parameter — Azure rejects
    # FUNCTION TOOLS combined with reasoning_effort on /v1/chat/completions
    # ("use /v1/responses instead"), so the tool-calling loop client must not
    # send it (the model then uses its default effort). Structured-output
    # calls (Designer/URL-builder/Critic) keep their tiers.
        # verify=False below (on all 4 httpx clients) is a known, deliberate
        # setting, not an oversight — flagged twice now (once earlier in
        # this project, once by a later code audit) and left unchanged both
        # times on explicit user decision, since this likely depends on an
        # internal CA/proxy in the real deployment environment that isn't
        # in this sandbox's trust store. Do not "fix" this without first
        # confirming the actual internal CA bundle path with whoever owns
        # this environment — swapping to verify=True or a wrong CA path
        # would silently break live authentication.
        OIDC_CLIENT_ID = os.getenv("OIDC_CLIENT_ID")
        OIDC_CLIENT_SECRET = os.getenv("OIDC_CLIENT_SECRET")
        OIDC_ENDPOINT = os.getenv("OIDC_ENDPOINT")
        OIDC_SCOPE = os.getenv("OIDC_SCOPE")
        APIGEE_ENDPOINT = os.getenv("APIGEE_ENDPOINT")

        oauth2_httpx_sync_client = httpx.Client(verify=False)
        oauth2_httpx_async_client = httpx.AsyncClient(verify=False)
        auth_sync = OAuth2ClientCredentials(OIDC_ENDPOINT, client_id=OIDC_CLIENT_ID, client_secret=OIDC_CLIENT_SECRET,
                                            scope=OIDC_SCOPE, client=oauth2_httpx_sync_client)
        auth_async = OAuth2ClientCredentials(OIDC_ENDPOINT, client_id=OIDC_CLIENT_ID, client_secret=OIDC_CLIENT_SECRET,
                                             scope=OIDC_SCOPE, client=oauth2_httpx_async_client)

        kwargs = {}
        if reasoning_effort is not None:
            # temperature MUST stay 1 for reasoning models with an effort set.
            kwargs["reasoning_effort"] = reasoning_effort
        return AzureChatOpenAI(
            azure_deployment=model,
            api_version=version,
            azure_endpoint=APIGEE_ENDPOINT,
            api_key="FAKE_KEY",
            http_client=httpx.Client(auth=auth_sync, verify=False),
            http_async_client=httpx.AsyncClient(auth=auth_async, verify=False),
            **kwargs,
            temperature=1,
            seed=1,
            timeout=360,
            max_retries=3,
            max_tokens=16384,
        )