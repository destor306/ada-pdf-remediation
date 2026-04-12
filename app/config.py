import os
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent

# Storage
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
LOG_DIR = BASE_DIR / "logs"

for d in (UPLOAD_DIR, OUTPUT_DIR, LOG_DIR):
    d.mkdir(exist_ok=True)

# AI backends
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
LOCAL_MODEL = os.environ.get("LOCAL_MODEL", "qwen2-vl")

# Stripe
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

# Pricing (USD)
PRICE_PER_PAGE = 0.05
FREE_PAGES_PER_MONTH = 3

# App
APP_URL = os.environ.get("APP_URL", "http://localhost:8000")
MAX_UPLOAD_MB = 50
MAX_PAGES_FREE = 3
MAX_PAGES_HARD = 500
LARGE_DOC_THRESHOLD = 50
