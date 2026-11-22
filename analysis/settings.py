"""Loads analysis/config.toml and the API key from .env (never put into os.environ), or from the
environment when there is no .env (the GitHub Actions run passes it as a secret)."""
import hashlib
import hmac
import os
import tomllib
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
CONFIG = tomllib.loads((Path(__file__).parent / "config.toml").read_text())
PROMPTS = Path(__file__).parent / "prompts"
COLLECTOR_DB = ROOT / "data" / "fed.db"
ANALYSIS_DB = ROOT / "data" / "analysis.db"


def api_key(name="GEMINI_API_KEY"):
    key = (dotenv_values(ROOT / ".env").get(name) or os.environ.get(name) or "").strip()
    if not key:
        raise RuntimeError(f"{name} is empty in .env")
    return key


PAID_UNLOCKED = set()  # models unlocked with the paid password for the run in progress


def free_daily(model):
    return CONFIG["limits"]["free_daily"].get(model, CONFIG["limits"]["requests_per_day"])


def daily_cap(model):
    """Calls allowed per Pacific day: the free limit, or the paid ceiling once unlocked with the password."""
    return max(free_daily(model), CONFIG["paid"]["daily_cap"]) if model in PAID_UNLOCKED else free_daily(model)


def password_ok(password):
    digest = hashlib.sha256((password or "").encode()).hexdigest()
    return hmac.compare_digest(digest, CONFIG["paid"]["password_sha256"])


def score_models(model):
    """Models whose scores a reading uses, in order: the chosen one, then the fallback for the default."""
    fb = CONFIG.get("fallback_model")
    return [model, fb] if model == CONFIG["model"] and fb and fb != model else [model]


def prompt(version):
    return (PROMPTS / f"{version.replace('-', '_')}.md").read_text()
