"""Placeholder: same interface as GeminiProvider, to be filled in when switching to Claude."""
from analysis.providers.base import Provider


class ClaudeProvider(Provider):
    name = "claude"

    def generate_json(self, system, user, schema, temperature=0):
        raise NotImplementedError("Claude provider not set up yet; set provider = \"gemini\" in config.toml")
