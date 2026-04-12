# Hero AI 🤖

A Django-based intelligent AI assistant featuring multi-model fallback, voice chat, web search, file handling, and per-user API key management.

## Features

- 💬 **Multi-model AI chat** — primary + automatic fallback across OpenRouter models
- 🔍 **Web search** — LLM-powered query rewriting and answer synthesis
- 🎙️ **Voice chat** — speech-to-text input with intelligent routing
- 📄 **File upload** — image OCR, PDF parsing, and document analysis
- 🔐 **Per-user encrypted API keys** — each user brings their own Gemini / OpenRouter key
- 👤 **Google OAuth** — sign in with Google supported
- 🗂️ **Persistent chat history** — conversation context stored per session

## Tech Stack

- **Backend**: Django 5.2, PostgreSQL (Neon), `python-dotenv`, `cryptography`
- **AI**: Google Gemini API, OpenRouter (multi-model fallback)
- **NLP**: spaCy-based intent detection
- **OCR**: Tesseract via `pytesseract`
- **Frontend**: Vanilla JS + CSS (no framework)

## Getting Started

### Prerequisites

- Python 3.11+
- PostgreSQL (or a [Neon](https://neon.tech) database)
- Tesseract OCR installed on your system

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/Hudsonmathew1910/hero-ai.git
cd hero-ai/hero_ai

# 2. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate   # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up environment variables
copy .env.example .env
# Then edit .env with your actual credentials

# 5. Apply database migrations
python manage.py migrate

# 6. Collect static files (needed for production)
python manage.py collectstatic --noinput

# 7. Run the development server
python manage.py runserver
```

### Environment Variables

Copy `.env.example` to `.env` and fill in the values:

| Variable | Description |
|---|---|
| `SECRET_KEY` | Django secret key — generate a new one for production |
| `DEBUG` | `True` for development, `False` for production |
| `ALLOWED_HOSTS` | Comma-separated list of allowed hosts |
| `NEON_DB_*` | PostgreSQL connection details |
| `ENCRYPTION_KEY` | Fernet key for encrypting stored API keys |
| `GOOGLE_CLIENT_ID` | Google OAuth client ID (optional) |
| `GOOGLE_CLIENT_SECRET` | Google OAuth client secret (optional) |

## Project Structure

```
hero_ai/
├── backend/           # Django app — models, views, AI logic
│   ├── hero_model.py  # Baymax AI dispatcher + model fallback
│   ├── views.py       # API endpoints
│   ├── Nlp.py         # Intent detection (NLP routing)
│   ├── handle_file.py # File upload & OCR handling
│   └── models_task/   # Specialized task handlers (web search, etc.)
├── hero_ai/           # Django project settings
├── static/            # CSS, JS, images
├── templates/         # HTML templates
├── logs/              # Application logs (gitignored)
└── manage.py
```

## Security Notes

- **Never commit `.env`** — it is gitignored by default
- Generate a fresh `SECRET_KEY` and `ENCRYPTION_KEY` for production
- Set `DEBUG=False` and configure `ALLOWED_HOSTS` before deploying
- Use HTTPS in production and set `SESSION_COOKIE_SECURE=True`

## License

MIT
