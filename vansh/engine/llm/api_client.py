import httpx

from engine.llm.client import LLMClient


class APIClient(LLMClient):
    """
    Generic HTTP-based LLM API client.

    This is a provider-agnostic fallback client.
    The actual API endpoint and authentication are supplied
    through configuration.
    """

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        model: str,
        timeout: float = 60.0,
    ):
        self.endpoint = endpoint
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def generate(self, prompt: str) -> str:
        """
        Send a prompt to the configured API provider.
        """

        response = httpx.post(
            self.endpoint,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "prompt": prompt,
            },
            timeout=self.timeout,
        )

        response.raise_for_status()

        data = response.json()

        return data["response"]