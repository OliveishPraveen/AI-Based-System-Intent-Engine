from abc import ABC, abstractmethod


class LLMClient(ABC):
    """
    Common interface for all LLM providers.

    Any LLM backend used by the Intent Engine must implement
    the generate() method.
    """

    @abstractmethod
    def generate(self, prompt: str) -> str:
        """
        Send a prompt to the LLM and return its response.
        """
        pass