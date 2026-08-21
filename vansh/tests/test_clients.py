from engine.llm.client import LLMClient
from engine.llm.ollama_client import OllamaClient
from engine.llm.api_client import APIClient


def test_ollama_client_implements_interface():
    client = OllamaClient()

    assert isinstance(client, LLMClient)


def test_api_client_implements_interface():
    client = APIClient(
        endpoint="https://example.com/api",
        api_key="test-key",
        model="test-model",
    )

    assert isinstance(client, LLMClient)


def test_clients_have_generate_method():
    ollama_client = OllamaClient()

    api_client = APIClient(
        endpoint="https://example.com/api",
        api_key="test-key",
        model="test-model",
    )

    assert callable(ollama_client.generate)
    assert callable(api_client.generate)