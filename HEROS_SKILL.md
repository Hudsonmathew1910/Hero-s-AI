# Heros AI — Comprehensive Skill Guide for AI Assistants

**Version:** 5th Gen | Updated: September 29, 2026

---

## Executive Summary

**Heros** is a production-grade, Django-powered AI assistant platform designed for **reliability, security, and extensibility**. It orchestrates multi-model LLM routing with a sophisticated 3-tier fallback system (Gemini → OpenRouter → Groq), intelligent intent detection, and enterprise-grade security features.

**Key Tagline:** *"The platform that never stops talking to you."*

---

## 1. What is Heros?

### Purpose & Problem It Solves

- **Multi-Model AI Assistant Platform**: Routes user requests across multiple LLM providers with automatic failover
- **High Availability**: Ensures **99.9% uptime** by never getting stuck on a single model provider
- **Enterprise Security**: Encrypts API keys using Fernet, supports OAuth, and implements secure session management
- **Production-Ready**: Deployed on real infrastructure (Neon PostgreSQL, Heroku/Railway/Render), with monitoring and logging

### Who Uses It?

- **End Users**: Access via web UI or Chrome/Edge browser extension (Zeno Pro)
- **Developers**: Deploy custom instances with encrypted API key management
- **Organizations**: Dataset analytics via Infinsight RAG (vector search + retrieval-augmented generation)

---

## 2. Core Components & Architecture

### 2.1 Baymax 4.5 AI Dispatcher (`backend/hero_model.py`)

**Purpose**: Central routing engine that intelligently selects which LLM to call.

**Key Features:**
- **3-Tier Fallback**: `Gemini → OpenRouter → Groq`
  - Primary: Google Gemini 2.5 Flash (fast, capable)
  - Secondary: OpenRouter (access to Claude, Llama, etc.)
  - Tertiary: Groq (ultra-fast inference)
- **Dynamic System Prompts**: Switches system prompt based on task type
  - `text` → conversational AI
  - `coding` → code generation & debugging specialist
  - `voice` → concise spoken responses
  - `web_search` → research-focused
- **Parallel API Racing** (Fast Mode): Simultaneously sends requests to multiple providers, returns fastest valid response
- **Token Management**: Budgets tokens per model (different providers have different limits)
- **Session Awareness**: Maintains conversation history for context

**Example Usage (Python)**:
```python
from backend.hero_model import Baymax

baymax = Baymax()
response = baymax.dispatch(
    user_msg="Explain quantum computing",
    history=[{"role": "user", "content": "..."}, ...],
    keys={"gemini": "sk-...", "openrouter": "sk-...", "groq": "sk-..."},
    task="text",
    primary_model="gemini-2.5-flash"
)
# Returns: {"response": "Quantum computing...", "model_used": "gemini-2.5-flash"}
```

### 2.2 NLP Intent Router (`backend/Nlp.py`)

**Purpose**: Analyzes user messages and determines the best handler for the request.

**Supported Intents:**

| Intent | Signals | Handler |
|--------|---------|---------|
| `coding` | "code", "debug", "write python", "fix bug", "git", "docker", "django" | Code generation & debugging |
| `web_search` | "search", "google", "look up", "latest" | Real-time web research |
| `file_analysis` | "analyze file", "read pdf", "extract data", "summarize" | Document/image processing |
| `creative` | "write story", "poem", "compose", "brainstorm" | Creative text generation |
| `math` | "calculate", "solve equation", "statistics" | Mathematical computation |
| `voice_chat` | "hey baymax", "hello", "talk to me" | Voice conversation mode |
| `play_song` | "play music", "listen to song" (via Zuno) | Music control via Zuno app |
| `task` | "remind me", "schedule", "create file", "send email" | Task automation |
| `explain` | "explain", "how does", "why is", "compare" | Educational explanations |
| `chat` | (default fallback) | General conversation |

**NLP Pipeline (5 Steps)**:
1. **Noise Removal**: Strip zero-width chars, collapse repeated punctuation, normalize Unicode
2. **Text Normalization**: Convert to lowercase for analysis (preserves original casing)
3. **Basic Cleaning**: Remove voice filler words ("um", "uh"), strip junk punctuation
4. **Intent Detection**: Match against regex patterns in priority order
5. **Metadata Enrichment**: Attach token estimates, code block flags, URLs, question marks

**Example Usage (Python)**:
```python
from backend.Nlp import preprocess, get_intent

# Get full preprocessing result
result = preprocess("Write a Python function to sort a list", source="text")
# Returns: {
#     "clean_text": "Write a Python function to sort a list",
#     "intent": "coding",
#     "source": "text",
#     "metadata": {"token_estimate": 11, "has_code_block": False, ...}
# }

# Quick intent check
intent = get_intent("Calculate 2 + 2")  # Returns: "math"
```

### 2.3 Halo 3.6 Orchestrator (`backend/halo.py`)

**Purpose**: Manages complex, multi-step operations and parallel task execution.

**Capabilities:**
- **Parallel Task Coordination**: Run multiple operations simultaneously (e.g., web search + file analysis)
- **Advanced Routing**: Intelligently distributes tasks across processing framework
- **Zero-Downtime Failover**: Seamless model/provider switching without conversation drops
- **Context Preservation**: Maintains conversation state across task boundaries

### 2.4 File Handler (`backend/handle_file.py`)

**Purpose**: Processes uploaded files and extracts meaningful content.

**Supported Formats:**
- **Images**: OCR via Tesseract (`pytesseract`) + vision model analysis
- **PDFs**: Text extraction, table detection (`pdfplumber`)
- **Word Docs**: Content parsing (`python-docx`)
- **Spreadsheets**: Data analysis (`pandas`, `openpyxl`)
- **Code Files**: Syntax highlighting + analysis

**Example**: User uploads `quarterly_report.pdf` → Tesseract extracts text + tables → Baymax summarizes

### 2.5 Views & API Endpoints (`backend/views.py`)

**Core Endpoints:**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/chat/` | POST | Send a message, get AI response |
| `/api/upload/` | POST | Upload files for analysis |
| `/api/voice/` | POST | Process voice input (speech-to-text) |
| `/api/search/` | POST | Trigger web search |
| `/api/settings/` | GET/PUT | Manage user API keys, preferences |
| `/api/history/` | GET | Fetch chat history |
| `/api/models/` | GET | List available fallback models |

---

## 3. Technology Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Backend Framework** | Django 5.2+ with DRF | HTTP server, ORM, middleware |
| **Database** | PostgreSQL (Neon serverless) | Persistent storage (chats, users, keys) |
| **Frontend** | JavaScript (28.4%), CSS (26.2%), HTML (18.8%) | Web UI with glassmorphism design |
| **AI/LLM Providers** | Google Gemini, OpenRouter, Groq | Multi-model routing |
| **NLP** | Custom rule-based engine (`Nlp.py`) | Intent detection & routing |
| **Vector DB** | Pinecone (optional) | Infinsight RAG analytics |
| **Security** | Cryptography (Fernet) | Encrypt API keys at rest |
| **OCR** | Tesseract via pytesseract | Image text extraction |
| **Web Search** | DuckDuckGo, Wikipedia, trafilatura | Real-time research |
| **Browser Ext** | Zeno Pro (Chrome, Edge) | Universal AI access in browser |
| **Deployment** | Gunicorn, WhiteNoise, Procfile | Production servers |
| **Voice** | edge-tts (text-to-speech) | Audio output |
| **Music** | ytmusicapi, pywhatkit | Zuno music assistant |

---

## 4. Project Structure

```
Hero-s-AI/
├── backend/                           # Django app (core logic)
│   ├── hero_model.py                 # Baymax dispatcher (3-tier fallback)
│   ├── Nlp.py                        # Intent detection & routing
│   ├── halo.py                       # Orchestrator for parallel tasks
│   ├── handle_file.py                # File upload & OCR
│   ├── encryption.py                 # Fernet encryption for API keys
│   ├── views.py                      # API endpoints
│   ├── models.py                     # Django ORM models (ChatSession, Message, etc.)
│   ├── models_task/                  # Specialized task handlers
│   ├── multiple_task.py              # Multi-task execution
│   ├── usage_tracker.py              # API usage logging
│   ├── utils.py                      # Helper functions
│   ├── tests.py                      # Unit & integration tests
│   └── migrations/                   # Database schema versions
│
├── hero_ai/                          # Django project config
│   ├── settings.py                   # Django configuration (DB, apps, middleware)
│   ├── urls.py                       # URL routing
│   ├── wsgi.py                       # WSGI entry point
│   ├── asgi.py                       # ASGI entry point
│   └── middleware.py                 # Custom middleware (CORS, rate-limit, etc.)
│
├── templates/                        # HTML templates (Django rendering)
├── static/                           # CSS, JavaScript, images
├── infinsight/                       # RAG analytics module (future)
├── zuno/                             # Music assistant integration
│
├── .env.example                      # Environment variables template
├── requirements.txt                  # Python dependencies
├── manage.py                         # Django CLI
├── Procfile                          # Production deployment config
├── runtime.txt                       # Python version specification
└── README.md                         # User documentation
```

---

## 5. Key Features Explained

### 5.1 Multi-Model Chat with Intelligent Fallback

**User sends**: "Explain quantum computing"

**Baymax's decision tree**:
1. Try Gemini 2.5 Flash (primary)
   - ✅ Success → return response
   - ❌ Rate limit / error → try next
2. Try OpenRouter (secondary)
   - ✅ Success → return response
   - ❌ Failure → try next
3. Try Groq (tertiary)
   - ✅ Success → return response
   - ❌ All failed → return error + retry instructions

**Result**: User never sees "API rate limited" or "service unavailable" errors.

### 5.2 Intent-Aware Routing

**User sends**: "Debug my Python script"

**Flow**:
1. NLP detects intent: `coding`
2. Baymax selects coding-specific system prompt (emphasizes debugging, syntax)
3. If file attached → handle_file processes it first
4. Baymax responds with improved code explanation

### 5.3 Encrypted API Key Management

**User adds their Gemini API key**:

```
Raw key: "AIzaSyD..."
        ↓ (Fernet encryption)
Stored: "gAAAAAB8..."  (in database)
        ↓ (decrypt on use)
Used: "AIzaSyD..."     (sent to Gemini API)
```

- **Never stored in plaintext**
- **Encryption key** lives in `.env` (never committed to Git)
- **Per-user keys**: Each user's credentials are isolated

### 5.4 OAuth + Persistent Sessions

**User logs in**:
1. Click "Sign in with Google"
2. Google OAuth flow → user authorized
3. Session created (encrypted, httponly cookie)
4. Chat history persists across sessions
5. Temporary chats (optional): Can create disposable conversations that aren't saved

### 5.5 Voice Chat

**User speaks**: "What's the weather?"

**Flow**:
1. Browser captures audio
2. Frontend sends WAV to `/api/voice/`
3. Backend converts to text (Google Speech-to-Text or edge-tts)
4. NLP detects intent: `voice_chat` or `web_search`
5. Baymax responds with concise, voice-friendly answer
6. Backend converts response to speech (edge-tts)
7. Browser plays audio

### 5.6 Web Search Integration

**User sends**: "Latest AI news today"

**Flow**:
1. NLP detects intent: `web_search`
2. Query rewriting (improve search terms)
3. Search via DuckDuckGo + Wikipedia + trafilatura
4. Results ranked by relevance
5. Baymax synthesizes into coherent answer with citations

### 5.7 Infinsight RAG Analytics

**Use case**: "Analyze our dataset"

**Flow**:
1. User uploads CSV/dataset
2. Files chunked + embedded (HuggingFace)
3. Vectors stored in Pinecone
4. User queries: "What's the revenue trend?"
5. Query embedded → semantic search in Pinecone
6. Top-K results retrieved → passed to Baymax
7. Baymax synthesizes with data-aware context

---

## 6. Security Architecture

### API Key Protection
- **Storage**: Encrypted with Fernet (symmetric encryption)
- **Transmission**: HTTPS only (enforced in production)
- **Access**: Per-user decryption (keys can't be read by other users)

### User Authentication
- **OAuth 2.0**: Google Sign-In integration
- **Session Management**: Cryptographically signed, httponly cookies
- **Rate Limiting**: django-ratelimit (prevents abuse)

### Database Security
- **PostgreSQL**: Uses Neon (serverless, auto-backups)
- **No plaintext secrets**: All `.env` vars validated at startup
- **CORS Protection**: Configurable allowed origins

### Deployment Security
- **DEBUG=False** in production (never exposes stack traces)
- **SECRET_KEY** regenerated per deployment
- **ALLOWED_HOSTS** restricts valid domain names
- **SESSION_COOKIE_SECURE**: Only send over HTTPS

---

## 7. How to Deploy & Run

### Quick Local Start

```bash
# 1. Clone & navigate
git clone https://github.com/Hudsonmathew1910/Hero-s-AI.git
cd Hero-s-AI

# 2. Create virtual env
python -m venv .venv
source .venv/bin/activate  # or: .venv\Scripts\activate on Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Setup environment
cp .env.example .env
# Edit .env with your credentials

# 5. Database migrations
python manage.py migrate

# 6. Run development server
python manage.py runserver
# Visit: http://localhost:8000
```

### Production Deployment (Heroku/Render/Railway)

```bash
# Included Procfile handles this automatically:
# web: gunicorn hero_ai.wsgi:application

# Pre-deployment checklist:
# ✅ Set DEBUG=False
# ✅ Generate new SECRET_KEY & ENCRYPTION_KEY
# ✅ Configure ALLOWED_HOSTS
# ✅ Enable HTTPS
# ✅ Run: python manage.py collectstatic --noinput
```

---

## 8. Key Environment Variables

| Variable | What It Does | Example |
|----------|-------------|---------|
| `SECRET_KEY` | Django security (NEVER expose) | `django-insecure-abc123...` |
| `ENCRYPTION_KEY` | Fernet key for API keys | Paste from `cryptography.fernet.Fernet.generate_key()` |
| `NEON_DB_*` | PostgreSQL connection | `host=ep-xxx.neon.tech, user=...` |
| `GOOGLE_CLIENT_ID/SECRET` | OAuth credentials | From Google Cloud Console |
| `Gemini_K1, Gemini_K2` | Primary model keys | From Google AI Studio |
| `Groq_1, Groq_2` | Fallback model keys | From console.groq.com |
| `PINECONE_API_KEY` | Vector DB (optional) | For Infinsight RAG |
| `DEBUG` | Development mode | `False` (production), `True` (dev) |

---

## 9. Common Tasks & Solutions

### "How does Baymax choose which model to use?"

**Answer**: Sequential priority + fast mode:
1. Check model availability (key exists, provider up)
2. Check rate limits (tokens remaining)
3. Primary model (Gemini) → try it
4. If fails: Secondary (OpenRouter) → try it
5. If fails: Tertiary (Groq) → try it
6. All fail? Return error + suggestions

### "Can users bring their own API keys?"

**Answer**: Yes! The UI has an "API Key Management" panel where users paste their Gemini/OpenRouter/Groq keys. Keys are encrypted before storage.

### "How does it handle long conversations?"

**Answer**: 
- Conversation history stored in PostgreSQL
- Token budgeting: Analyzes message + history length
- Intelligent truncation: Summarizes old messages if hitting token limit
- Session-aware: Each user has isolated chat sessions

### "What if a model fails mid-response?"

**Answer**: Halo orchestrator detects the failure and:
1. Marks provider as temporarily unavailable
2. Retries with next provider
3. User sees: "Switching to [model name]..."
4. Response resumes from the new model

### "How secure is the voice mode?"

**Answer**: 
- Audio → processed locally in browser (optional)
- OR sent to backend via HTTPS (encrypted in transit)
- Backend has native voice processing endpoint
- Responses text-to-speech with edge-tts (privacy-focused)

### "Can I use this for a chatbot on my website?"

**Answer**: Yes! 
- Deploy as API-only (skip frontend)
- Use `/api/chat/` endpoint
- Clients authenticate with JWT or API keys
- Built-in rate-limiting for multi-tenant usage

---

## 10. Code Examples for AI Assistants

### Example 1: Intent Detection in Action

```python
from backend.Nlp import preprocess, resolve_mode

user_input = "Write me a Python function that sorts a list"
source = "text"

# Get preprocessing result
result = preprocess(user_input, source)

# Extract useful info
clean = result["clean_text"]           # "Write me a Python function that sorts a list"
intent = result["intent"]              # "coding"
metadata = result["metadata"]          # {"token_estimate": 11, "is_short": False, ...}

# Determine which mode to use
mode = resolve_mode(result, current_mode="text")  # "coding"

print(f"Intent: {intent}, Mode: {mode}, Clean: {clean}")
# Output: Intent: coding, Mode: coding, Clean: Write me a Python function that sorts a list
```

### Example 2: Dispatching with Baymax

```python
from backend.hero_model import Baymax

# Initialize
baymax = Baymax()

# User context
user_msg = "What's the latest in AI?"
history = [
    {"role": "user", "content": "Tell me about LLMs"},
    {"role": "assistant", "content": "LLMs are large language models..."}
]
keys = {
    "gemini": os.getenv("Gemini_K1"),
    "openrouter": os.getenv("OPENROUTER_KEY"),
    "groq": os.getenv("Groq_1")
}

# Dispatch
response = baymax.dispatch(
    user_msg=user_msg,
    history=history,
    keys=keys,
    task="web_search",  # NLP detected web search
    primary_model="gemini-2.5-flash"
)

print(f"Model used: {response.get('model_used')}")
print(f"Response: {response.get('response')}")
```

### Example 3: File Analysis Workflow

```python
from backend.handle_file import extract_from_file

# User uploaded: quarterly_earnings.pdf
file_path = "uploads/user_123/quarterly_earnings.pdf"
file_type = "pdf"

# Extract content
extracted_content = extract_from_file(file_path, file_type)

print(f"Text: {extracted_content['text'][:500]}...")
print(f"Tables: {extracted_content.get('tables', [])}")
print(f"Images: {extracted_content.get('images', [])}")

# Now pass to Baymax with file context
baymax_input = f"Summarize this document:\n{extracted_content['text']}"
# ... call baymax.dispatch()
```

---

## 11. Testing & Debugging

### Run Tests

```bash
python manage.py test backend
```

**Test Coverage**:
- Intent detection accuracy
- Model fallback behavior
- API key encryption/decryption
- File parsing (PDF, images, etc.)
- Session persistence
- OAuth flow
- Rate limiting

### Enable Debug Logging

In Django shell:
```python
import logging
logging.basicConfig(level=logging.DEBUG)

from backend.Nlp import preprocess
result = preprocess("test", "text")
print(result)
```

### Monitor API Usage

Endpoint: `/api/usage/` (returns user's usage stats)

```json
{
  "gemini_calls": 42,
  "openrouter_calls": 5,
  "groq_calls": 2,
  "total_tokens_used": 15000,
  "period": "this_month"
}
```

---

## 12. Release History

| Version | Release Date | Highlights |
|---------|-------------|-----------|
| **5th Gen** | Sep 29, 2026 | Baymax 4.5 (Fast Mode), Halo 3.6, Glassmorphism UI, Zeno 3.5 |
| **4th Gen** | Jul 27, 2026 | Zeno 3.0 extension, Unbreakable Routing |
| **V2.8** | Jul 9, 2026 | Zeno 2.1 Pro, Zuno Music |
| **V2.6** | Jul 3, 2026 | Zeno extension launch |
| **Infinsight V2.8** | May 6, 2026 | RAG analytics platform |
| **V1.0** | Apr 12, 2026 | Initial Django prototype |

---

## 13. Contact & Support

- **GitHub Issues**: Report bugs → [Issues](https://github.com/Hudsonmathew1910/Hero-s-AI/issues)
- **Discussions**: Ask questions → [Discussions](https://github.com/Hudsonmathew1910/Hero-s-AI/discussions)
- **Live Demo**: https://hero-s-ai.alwaysdata.net/
- **Creator**: Hudson Mathew (@Hudsonmathew1910)

---

## 14. Quick Reference Cheat Sheet

**When users ask "How do I..."**

| Question | Answer |
|----------|--------|
| Add my own API keys? | UI → Settings → API Keys → paste key (encrypted automatically) |
| Use offline? | Not possible (requires API keys from providers) |
| Export chats? | API endpoint: `/api/history/export/` |
| Delete my data? | Account settings → Privacy → Delete account (removes all chats/keys) |
| Use voice mode? | Click microphone icon, speak clearly, wait for text-to-speech response |
| Get faster responses? | Enable "Fast Mode" (Parallel API Racing in settings) |
| Switch models manually? | Chat settings → select model before sending message |
| Use browser extension? | Install Zeno Pro from Chrome Web Store (only Google/OpenRouter keys work) |

---

## 15. For Developers: Key Imports & APIs

```python
# Intent detection
from backend.Nlp import preprocess, get_intent, resolve_mode

# AI dispatcher
from backend.hero_model import Baymax

# File handling
from backend.handle_file import extract_from_file

# Orchestration
from backend.halo import OrchestratorService

# Encryption
from backend.encryption import encrypt_key, decrypt_key

# Models
from backend.models import ChatSession, Message, UserProfile

# Views/API
from backend.views import (
    handle_chat, handle_upload, handle_voice, 
    get_user_api_keys, get_user_settings
)
```

---

## 16. Key Insights for Assistance

When helping users with Heros:

1. **Always mention the 3-tier fallback**: Gemini → OpenRouter → Groq (99.9% uptime)
2. **Security first**: Remind them to keep `.env` files out of Git
3. **Intent-driven**: Explain how NLP routes "code" vs "search" vs "chat"
4. **Multi-modal**: Heros handles text, voice, files, and real-time search
5. **Extensible**: Can add new intents/models by modifying `Nlp.py` and `hero_model.py`
6. **Production-ready**: Uses PostgreSQL, encryption, OAuth, rate limiting

---

**End of Heros AI Skill Guide**

*Built with ❤️ for developers who want AI that never stops working.*
