# ADA PDF Remediation Tool

Convert non-compliant PDFs to ADA / PDF-UA accessible documents using local vision AI.

**Workflow:**
```
Input PDF → Vision AI (page-by-page) → Accessible .docx → Export tagged PDF → PAC 2026 validation
```

---

## Quick Start

### 1. Install system dependencies

```bash
# Python packages
python3 -m pip install --user --break-system-packages -r requirements.txt

# Poppler (PDF rendering) — already on most Linux systems
# sudo apt install poppler-utils

# Java + VeraPDF (optional but recommended for full PDF/UA validation)
sudo apt install default-jre -y
# Then download VeraPDF from: https://docs.verapdf.org/install/
```

### 2. Set up an AI backend (choose one or both)

**Option A — Local (free, requires ~8 GB RAM + GPU)**
```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2-vl
```

**Option B — Claude API (pay-per-use, ~$0.025/page)**
```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

### 3. Configure environment

Copy `.env.example` to `.env` and fill in your keys:
```bash
cp .env.example .env
```

Key variables:
| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | If using Claude | Claude API key |
| `STRIPE_SECRET_KEY` | For paid tiers | Stripe secret key |
| `STRIPE_PUBLISHABLE_KEY` | For paid tiers | Stripe publishable key |
| `STRIPE_WEBHOOK_SECRET` | For production | Stripe webhook signing secret |
| `OLLAMA_HOST` | If Ollama not local | e.g. `http://gpu-server:11434` |
| `LOCAL_MODEL` | Optional | Default: `qwen2-vl` |
| `APP_URL` | Production | e.g. `https://yourapp.com` |

### 4. Run the web app

```bash
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Open: http://localhost:8000

### 5. Run the CLI tools directly

**Convert a single PDF:**
```bash
python3 ada_remediate.py input.pdf output.docx
```

**Check compliance:**
```bash
python3 ada_check.py input.pdf output.docx [output.pdf]
```

---

## Architecture

```
ADA/
├── ada_remediate.py      # Core conversion pipeline (CLI + library)
├── ada_check.py          # Quality & compliance checker (CLI + library)
├── requirements.txt
├── .env.example
│
├── app/
│   ├── main.py           # FastAPI app entry point
│   ├── config.py         # Settings (reads from environment)
│   ├── jobs.py           # In-memory job queue (thread-based)
│   ├── billing.py        # Stripe per-page billing
│   ├── routes/
│   │   ├── api.py        # POST /upload, /process, GET /status, /download
│   │   ├── billing.py    # Stripe success/cancel/webhook
│   │   └── pages.py      # HTML page routes
│   ├── templates/
│   │   └── index.html    # Single-page frontend
│   └── static/           # CSS, JS assets (if any)
│
├── uploads/              # Uploaded PDFs (temp)
├── outputs/              # Processed .docx files
└── logs/
```

### AI Strategy (Hybrid)

| Backend | Cost | When used |
|---------|------|-----------|
| Ollama (qwen2-vl 7B) | $0/page | Primary — all conversions |
| Claude API | ~$0.025/page | Fallback — when Ollama fails or unavailable |

### Quality Validation Stack

| Layer | Tool | What it checks | Cost |
|-------|------|---------------|------|
| 1 | Built-in docx audit | Heading hierarchy, table headers, alt text, language, text coverage | Free |
| 2 | VeraPDF | Full ISO 14289-1 PDF/UA-1 conformance | Free (open source) |
| 3 | Pixel diff | Visual similarity vs. source PDF | Free (Pillow) |

---

## Pricing Model

| Tier | Price | Pages |
|------|-------|-------|
| Free | $0 | 3 pages/month |
| Pay-as-you-go | $0.05/page | No commitment |
| Pro | $19/mo | ~200 pages |
| Business | $79/mo | ~1,000 pages |
| Enterprise | Custom | Volume |

---

## Stripe Setup

1. Create a Stripe account at https://stripe.com
2. Get your API keys from the Stripe dashboard
3. For webhooks (production):
   - Add endpoint: `https://yourapp.com/billing/webhook`
   - Listen for: `checkout.session.completed`
   - Copy the signing secret to `STRIPE_WEBHOOK_SECRET`

For local testing:
```bash
# Install Stripe CLI
stripe listen --forward-to localhost:8000/billing/webhook
```

---

## Production Deployment

### Recommended stack
- **Web server:** Nginx + Gunicorn/Uvicorn
- **Job queue:** Redis + RQ (replace `app/jobs.py` in-memory store)
- **File storage:** S3-compatible (replace local `uploads/` + `outputs/`)
- **GPU worker:** RunPod or Vast.ai spot instance running Ollama

### Scale-out architecture
```
Users → Nginx → FastAPI (cheap VPS)
                    ↓
              Redis job queue
                    ↓
           GPU Worker (RunPod spot)
           ├── Ollama qwen2-vl (primary)
           └── Claude API (fallback)
                    ↓
              S3 file storage
```

---

## Testing

```bash
# Upload and convert the test PDF (requires API key or Ollama)
python3 ada_remediate.py test_fldoe.pdf test_out.docx

# Check compliance
python3 ada_check.py test_fldoe.pdf test_out.docx

# Start server and test API
python3 -m uvicorn app.main:app --reload
curl -X POST http://localhost:8000/api/upload -F "file=@test_fldoe.pdf"
```

---

## Target Customers

- Government agencies (Section 508 compliance)
- Law firms (court filing requirements)
- Hospitals & healthcare (ADA Title III)
- Universities (OCR complaint remediation)

---

## Validation Tools

- **PAC 2026:** https://pac.pdf-accessibility.org (upload exported PDF)
- **VeraPDF:** https://verapdf.org (local CLI, same engine)
- **Word Accessibility Checker:** Review → Check Accessibility
