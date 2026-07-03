# Hero's AI 🤖

**A production-grade, Django-powered AI assistant platform** featuring intelligent multi-model routing, voice capabilities, RAG analytics, and enterprise-grade security.

Baymax (the core AI dispatcher) intelligently routes requests across **3-tier model fallback** (Gemini → OpenRouter → Groq) ensuring **99.9% uptime** with encrypted API key management and persistent chat history.

---

## ✨ Key Features

- 🧠 **Baymax AI Dispatcher** — Intent-aware routing with 3-tier fallback (Gemini → OpenRouter → Groq)
- 💬 **Multi-Model Chat** — Auto-switching between primary and fallback models
- 🎙️ **Voice Chat** — Speech-to-text input with intelligent intent routing  
- 🔍 **Web Search** — LLM-powered query rewriting and real-time answer synthesis
- 📄 **File Handling** — Image OCR, PDF parsing, DOCX analysis, and data extraction
- 🔐 **Encrypted API Keys** — Fernet-based encryption for user credentials
- 👤 **OAuth + Auth** — Google OAuth integration with secure session management
- 💾 **Persistent Chat History** — Per-session conversation context with optional temporary chats
- 📊 **Infinsight RAG Analytics** — Dataset-aware retrieval-augmented generation for analytics
- 🎯 **Intent Detection** — NLP-powered routing for optimal task handling

---

## 🏗️ Tech Stack

| Component | Technology |
|-----------|-----------|
| **Backend** | Django 5.2+ with DRF |
| **Database** | PostgreSQL (Neon) with psycopg2 |
| **AI/LLM** | Google Gemini API, OpenRouter (multi-model), Groq |
| **NLP** | Intent detection & routing engine |
| **OCR** | Tesseract via pytesseract |
| **Frontend** | JavaScript (36.7%), CSS (21.9%), HTML (16.3%) |
| **Security** | Cryptography (Fernet), django-cryptography |
| **Deployment** | Gunicorn, WhiteNoise, Procfile support |

---

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL (or [Neon](https://neon.tech) serverless)
- Tesseract OCR installed
- API keys: Google Gemini, OpenRouter, or Groq

### Installation

```bash
# 1. Clone repository
git clone https://github.com/Hudsonmathew1910/Hero-s-AI.git
cd Hero-s-AI/hero_ai

# 2. Create virtual environment
python -m venv .venv
source .venv/bin/activate          # macOS/Linux
# OR
.venv\Scripts\activate             # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env with your credentials (see below)

# 5. Run migrations
python manage.py migrate

# 6. Start development server
python manage.py runserver
```

Visit `http://localhost:8000`

---

## ⚙️ Environment Variables

Copy `.env.example` to `.env` and configure:

| Variable | Description | Example |
|----------|-----------|---------|
| `NEON_DB_NAME` | PostgreSQL database name | `hero_db` |
| `NEON_DB_USER` | Database user | `neon_user` |
| `NEON_DB_PASSWORD` | Database password | — |
| `NEON_DB_HOST` | Database host | `ep-xxx.neon.tech` |
| `NEON_DB_PORT` | Database port | `5432` |
| `SECRET_KEY` | Django secret key (generate new) | — |
| `DEBUG` | Development mode | `False` (production) |
| `ALLOWED_HOSTS` | Allowed domains | `localhost,yourdomain.com` |
| `ENCRYPTION_KEY` | Fernet key for API key encryption | — |
| `GOOGLE_CLIENT_ID` | Google OAuth client ID | — |
| `GOOGLE_CLIENT_SECRET` | Google OAuth secret | — |
| `SITE_URL` | Your site URL | `https://yourdomain.com` |

**Generate keys:**
```bash
# Django secret key
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"

# Fernet encryption key
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

---

## 📁 Project Structure

```
hero_ai/
├── backend/                    # Django application
│   ├── hero_model.py          # Baymax AI dispatcher & 3-tier fallback
│   ├── Nlp.py                 # Intent detection & routing
│   ├── views.py               # API endpoints
│   ├── handle_file.py         # File upload, OCR, PDF parsing
│   ├── models.py              # Database models
│   ├── models_task/           # Specialized handlers (web search, etc.)
│   ├── migrations/            # Database migrations
│   └── tests.py               # Unit & integration tests
│
├── hero_ai/                   # Django project config
│   ├── settings.py            # Project settings
│   ├── urls.py                # URL routing
│   └── wsgi.py                # WSGI config
│
├── static/                    # CSS, JS, images
├── templates/                 # HTML templates
├── logs/                      # Application logs (gitignored)
├── .env.example               # Environment template
├── requirements.txt           # Python dependencies
├── manage.py                  # Django management
└── Procfile                   # Production deployment config
```

---

## 🔧 Core Components

### Baymax AI Dispatcher (`hero_model.py`)
- **3-Tier Fallback**: Gemini → OpenRouter → Groq
- **Dynamic Prompts**: Different system prompts for text/coding/voice/web-search
- **Token Management**: Intelligent token budgeting per model
- **Session Awareness**: Maintains conversation context

```python
# Example usage
baymax = Baymax()
response = baymax.dispatch(
    user_msg="Explain quantum computing",
    history=[...],
    keys={"gemini": "...", "openrouter": "..."},
    task="text",
    primary_model="gemini-2.5-flash"
)
```

### Intent Detection (`Nlp.py`)
Routes requests to appropriate handlers:
- `text` — General conversation
- `coding` — Code generation & debugging
- `voice` — Voice-to-text responses
- `websearch` — Real-time web information
- `file_analysis` — Document & image processing

---

## 🚀 Production Deployment

### Using Gunicorn

```bash
gunicorn hero_ai.wsgi:application \
  --workers 3 \
  --bind 0.0.0.0:8000 \
  --timeout 120
```

### Using Procfile (Railway, Render, Heroku)

Included `Procfile` automatically deploys with:
```
web: gunicorn hero_ai.wsgi:application
```

### Pre-Deployment Checklist

- [ ] Set `DEBUG=False`
- [ ] Generate new `SECRET_KEY` and `ENCRYPTION_KEY`
- [ ] Configure `ALLOWED_HOSTS`
- [ ] Enable HTTPS and set `SESSION_COOKIE_SECURE=True`
- [ ] Run `python manage.py collectstatic`
- [ ] Set up PostgreSQL backups (Neon has built-in backups)
- [ ] Configure monitoring & error tracking (e.g., Sentry)

```bash
python manage.py collectstatic --noinput
```

---

## 🔒 Security

### Best Practices

- ✅ **Never commit `.env`** — already in `.gitignore`
- ✅ **Encrypt sensitive data** — Fernet encryption for stored API keys
- ✅ **Use environment variables** — All secrets from `.env`
- ✅ **HTTPS only** — Set `SESSION_COOKIE_SECURE=True` in production
- ✅ **Rate limiting** — Django rate limit middleware included
- ✅ **CORS protection** — Configured per deployment

### API Key Encryption

User API keys are encrypted using Fernet before storage:
```python
from cryptography.fernet import Fernet
cipher = Fernet(ENCRYPTION_KEY)
encrypted = cipher.encrypt(api_key.encode())
```

---

## 📦 Dependencies

### Key Libraries
- **Django 5.2+** — Web framework
- **google-genai** — Google Gemini API
- **requests** — HTTP client for OpenRouter/Groq
- **cryptography** — Fernet encryption
- **pandas, numpy, scikit-learn** — Data analysis
- **pypdf, pdfplumber, python-docx** — Document parsing
- **ddgs, wikipedia** — Web search
- **pytesseract** — OCR

See `requirements.txt` for complete list.

---

## 🧪 Testing

Run unit and integration tests:

```bash
python manage.py test backend
```

Tests cover:
- Intent detection accuracy
- Model fallback behavior
- API key encryption/decryption
- File parsing & OCR

---

## 📊 Language Composition

| Language | Percentage |
|----------|-----------|
| JavaScript | 36.7% |
| Python | 25.1% |
| CSS | 21.9% |
| HTML | 16.3% |

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## 📝 License

MIT License — see `LICENSE` file for details

---

## 🙋 Support

For issues, feature requests, or questions:
- 📧 Open an [Issue](https://github.com/Hudsonmathew1910/Hero-s-AI/issues)
- 💬 Start a [Discussion](https://github.com/Hudsonmathew1910/Hero-s-AI/discussions)

---

**Built with ❤️ by Hudson Mathew**
