from .base import LLMError, LLMProvider

def get_llm(provider: str, model: str = "") -> LLMProvider:
    if provider == "gemini":
        from .gemini import GeminiLLM
        return GeminiLLM(model)
    if provider == "openai":
        from .openai_llm import OpenAILLM
        return OpenAILLM(model)
    raise LLMError(f"Không hỗ trợ LLM {provider!r}")

__all__ = ["LLMError", "LLMProvider", "get_llm"]
