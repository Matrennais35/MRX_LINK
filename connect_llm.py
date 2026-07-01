import os
import httpx
from httpx_auth import OAuth2ClientCredentials
from langchain_openai import AzureChatOpenAI


def get_llm(model: str):
        AZURE_AOAI_API_VERSION = "2024-10-21"
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

        return AzureChatOpenAI(
            azure_deployment=model,
            api_version=AZURE_AOAI_API_VERSION,
            azure_endpoint=APIGEE_ENDPOINT,
            api_key="FAKE_KEY",
            http_client=httpx.Client(auth=auth_sync, verify=False),
            http_async_client=httpx.AsyncClient(auth=auth_async, verify=False),
            temperature=0,
            seed=1,
            timeout=360,
            max_retries=3,
            max_tokens=16384,
        )