import json
from .. import config
from .base import LLMError, to_openai_strict, with_retry

class OpenAILLM:
    name = "openai"

    def __init__(self, model: str = ""):
        self.model = model or config.OPENAI_MODEL
        self._client = None

    def client(self):
        if self._client is None:
            if not config.OPENAI_API_KEY:
                raise LLMError("Thiếu OPENAI_API_KEY trong file .env")
            from openai import OpenAI
            self._client = OpenAI(api_key=config.OPENAI_API_KEY, max_retries=0, timeout=180)
        return self._client

    def generate_json(self, prompt: str, schema: dict, temperature: float = 0.3) -> dict:
        import openai

        def retryable(e):
            return isinstance(e, (openai.RateLimitError, openai.APIConnectionError, openai.InternalServerError))

        fmt = {"type": "json_schema", "json_schema": {"name": "result", "strict": True, "schema": to_openai_strict(schema)}}
        try:
            resp = with_retry(lambda: self.client().chat.completions.create(
                model=self.model, messages=[{"role": "user", "content": prompt}],
                response_format=fmt, temperature=temperature), retryable)
        except openai.OpenAIError as e:
            raise LLMError(f"OpenAI lỗi: {e}") from e
        text = resp.choices[0].message.content or ""
        try:
            return json.loads(text)
        except ValueError as e:
            raise LLMError(f"OpenAI trả về JSON không hợp lệ: {text[:200]}") from e
