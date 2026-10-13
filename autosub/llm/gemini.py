import json
from .. import config
from .base import LLMError, to_gemini_schema, with_retry

class GeminiLLM:
    name = "gemini"

    def __init__(self, model: str = ""):
        self.model = model or config.GEMINI_MODEL
        self._client = None

    def client(self):
        if self._client is None:
            if not config.GCP_PROJECT:
                raise LLMError("Thiếu GOOGLE_CLOUD_PROJECT trong file .env")
            from google import genai
            self._client = genai.Client(vertexai=True, project=config.GCP_PROJECT, location=config.GCP_LOCATION)
        return self._client

    def generate_json(self, prompt: str, schema: dict, temperature: float = 0.3) -> dict:
        from google.genai import errors, types
        cfg = types.GenerateContentConfig(response_mime_type="application/json",
                                          response_schema=to_gemini_schema(schema), temperature=temperature)

        def retryable(e):
            code = getattr(e, "code", None) or 0
            return isinstance(e, errors.APIError) and (code == 429 or code >= 500)

        try:
            resp = with_retry(lambda: self.client().models.generate_content(model=self.model, contents=prompt, config=cfg),
                              retryable)
        except errors.APIError as e:
            raise LLMError(f"Gemini lỗi: {e}") from e
        except Exception as e:  # noqa: BLE001  (auth errors from google-auth etc.)
            if isinstance(e, LLMError):
                raise
            raise LLMError(f"Gemini lỗi: {e}. Nếu lỗi xác thực, chạy: gcloud auth application-default login") from e
        try:
            return json.loads(resp.text)
        except (TypeError, ValueError) as e:
            raise LLMError(f"Gemini trả về JSON không hợp lệ: {str(resp.text)[:200]}") from e
