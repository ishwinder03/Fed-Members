"""Google Gemini via the google-genai SDK: throttled, retries 429/5xx with backoff."""
import json
import random
import re
import time

from google import genai
from google.genai import errors, types

from analysis.providers.base import Provider, QuotaExhausted
from analysis.settings import CONFIG, api_key


class GeminiProvider(Provider):
    name = "gemini"

    def __init__(self, model, log=print):
        super().__init__(model, log)
        self.client = genai.Client(api_key=api_key("GEMINI_API_KEY"))

    def list_models(self):
        return sorted(m.name.removeprefix("models/") for m in self.client.models.list())

    def generate_json(self, system, user, schema, temperature=0):
        lim = CONFIG["limits"]
        config = types.GenerateContentConfig(
            system_instruction=system, temperature=temperature,
            response_mime_type="application/json", response_json_schema=schema)
        for attempt in range(lim["max_retries"] + 1):
            self._throttle(lim["requests_per_minute"])
            try:
                r = self.client.models.generate_content(model=self.model, contents=user, config=config)
                self.calls += 1
                u = r.usage_metadata
                usage = {"tokens_in": getattr(u, "prompt_token_count", None),
                         "tokens_out": getattr(u, "candidates_token_count", None)}
                return json.loads(r.text), usage
            except errors.APIError as e:
                self.calls += 1
                retryable = e.code == 429 or (e.code or 0) >= 500
                if e.code == 429 and "PerDay" in str(e):
                    raise QuotaExhausted(f"{self.model}: daily request quota used up") from e
                if not retryable or attempt == lim["max_retries"]:
                    raise
                m = re.search(r"retryDelay['\"]?:\s*['\"]?(\d+)", str(e))
                wait = int(m[1]) + 1 if m else 15 * 2 ** attempt
                wait += random.uniform(0, 3)
                self.log(f"  {e.code} from {self.model}; retrying in {wait:.0f}s")
                time.sleep(wait)
