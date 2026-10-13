import copy
import time
from typing import Callable, Protocol

class LLMError(Exception):
    pass

class LLMProvider(Protocol):
    name: str
    model: str
    def generate_json(self, prompt: str, schema: dict, temperature: float = 0.3) -> dict: ...

def with_retry(fn: Callable, is_retryable: Callable[[Exception], bool], attempts: int = 4, sleep=time.sleep):
    """Call fn(); on retryable errors wait 2, 4, 8 s between attempts."""
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            if attempt < attempts - 1 and is_retryable(e):
                sleep(2 ** attempt * 2)
                continue
            raise

def to_gemini_schema(schema: dict) -> dict:
    """Standard JSON Schema -> the OpenAPI subset google-genai expects (upper-case types)."""
    def conv(s):
        out = {}
        for k, v in s.items():
            if k == "additionalProperties":
                continue
            if k == "type":
                out[k] = v.upper()
            elif k == "properties":
                out[k] = {name: conv(sub) for name, sub in v.items()}
            elif k == "items":
                out[k] = conv(v)
            else:
                out[k] = v
        return out
    return conv(schema)

def to_openai_strict(schema: dict) -> dict:
    """Strict structured outputs: every object closed and every property required."""
    s = copy.deepcopy(schema)
    def walk(node):
        if node.get("type") == "object":
            node["additionalProperties"] = False
            node["required"] = list(node.get("properties", {}))
            for sub in node.get("properties", {}).values():
                walk(sub)
        elif node.get("type") == "array":
            walk(node["items"])
    walk(s)
    return s
