from analysis.settings import CONFIG


def get(model=None, log=print):
    """The configured provider; every AI call goes through this."""
    if CONFIG["provider"] == "gemini":
        from analysis.providers.gemini import GeminiProvider
        return GeminiProvider(model or CONFIG["model"], log)
    if CONFIG["provider"] == "claude":
        from analysis.providers.claude import ClaudeProvider
        return ClaudeProvider(model or CONFIG["model"], log)
    raise ValueError(f"unknown provider {CONFIG['provider']!r}")
