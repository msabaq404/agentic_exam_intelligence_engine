from __future__ import annotations

import os
from typing import Optional, Dict, Any

try:
    from google import genai
except Exception as exc:
    raise ImportError("google-genai SDK is required. Install it with: pip install google-genai") from exc


class SDKClient:

    def __init__(self, api_key: str, model: str, timeout: int = 30):
        if not api_key:
            raise RuntimeError("GOOGLE_GENAI_API_KEY must be set in environment")
        if not model:
            raise RuntimeError("GOOGLE_GENAI_MODEL must be set in environment")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        try:
            self.client = genai.Client(api_key=api_key)
        except TypeError:
            # Some SDK versions may not accept api_key in constructor; set env and create client
            os.environ["GOOGLE_GENAI_API_KEY"] = api_key
            self.client = genai.Client()

    def infer(self, prompt: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        config = None
        if params:
            config_kwargs = {}
            if "max_tokens" in params:
                config_kwargs["max_output_tokens"] = params["max_tokens"]
            if "temperature" in params:
                config_kwargs["temperature"] = params["temperature"]
            if "top_p" in params:
                config_kwargs["top_p"] = params["top_p"]
            if config_kwargs:
                try:
                    from google.genai import types

                    config = types.GenerateContentConfig(**config_kwargs)
                except Exception:
                    config = config_kwargs

        try:
            if config is not None:
                response = self.client.models.generate_content(model=self.model, contents=prompt, config=config)
            else:
                response = self.client.models.generate_content(model=self.model, contents=prompt)
        except Exception as exc:
            if config is not None:
                try:
                    response = self.client.models.generate_content(model=self.model, contents=prompt)
                except Exception as fallback_exc:
                    raise RuntimeError(f"google.genai generate_content failed: {fallback_exc}") from fallback_exc
            else:
                raise RuntimeError(f"google.genai generate_content failed: {exc}") from exc

        text = getattr(response, "text", None)
        if text is not None:
            return {"text": text}

        candidates = getattr(response, "candidates", None)
        if candidates:
            first = candidates[0]
            content = getattr(first, "content", None) or (first.get("content") if isinstance(first, dict) else None)
            if content:
                parts = []
                for p in getattr(content, "parts", []) or (content.get("parts") if isinstance(content, dict) else []):
                    t = getattr(p, "text", None) or (p.get("text") if isinstance(p, dict) else None)
                    if t:
                        parts.append(t)
                if parts:
                    return {"text": "\n\n".join(parts)}

        return {"text": str(response)}


def get_gemini_client() -> SDKClient:
    api_key = os.getenv("GOOGLE_GENAI_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_GENAI_API_KEY is required; set it in .env")
    model = os.getenv("GOOGLE_GENAI_MODEL")
    if not model:
        raise RuntimeError("GOOGLE_GENAI_MODEL is required; set it in .env")
    return SDKClient(api_key=api_key, model=model)

   