"""Provider interface. A provider turns (system, user, schema) into a parsed JSON dict."""
import time


class QuotaExhausted(Exception):
    """The daily request allowance is used up; a later run carries on."""


class Provider:
    name = "base"

    def __init__(self, model, log=print):
        self.model = model
        self.log = log
        self._last = 0.0
        self.calls = 0

    def generate_json(self, system, user, schema, temperature=0):
        """Returns (data: dict, usage: {'tokens_in', 'tokens_out'})."""
        raise NotImplementedError

    def list_models(self):
        raise NotImplementedError

    def _throttle(self, per_minute):
        wait = 60.0 / per_minute - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()
