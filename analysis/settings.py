"""Loads analysis/config.toml and the API key from .env (never put into os.environ)."""
import tomllib
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
CONFIG = tomllib.loads((Path(__file__).parent / "config.toml").read_text())
PROMPTS = Path(__file__).parent / "prompts"
COLLECTOR_DB = ROOT / "data" / "fed.db"
ANALYSIS_DB = ROOT / "data" / "analysis.db"


def api_key(name="GEMINI_API_KEY"):
    key = (dotenv_values(ROOT / ".env").get(name) or "").strip()
    if not key:
        raise RuntimeError(f"{name} is empty in .env")
    return key


def daily_cap(model):
    """Calls allowed per Pacific day for a model; 0 means the model must not be called."""
    return CONFIG["limits"]["daily_cap"].get(model, CONFIG["limits"]["requests_per_day"])


def score_models(model):
    """Models whose scores a reading uses, in order: the chosen one, then the fallback for the default."""
    fb = CONFIG.get("fallback_model")
    return [model, fb] if model == CONFIG["model"] and fb and fb != model else [model]


def prompt(version):
    return (PROMPTS / f"{version.replace('-', '_')}.md").read_text()
