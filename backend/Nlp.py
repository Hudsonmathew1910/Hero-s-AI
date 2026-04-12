from __future__ import annotations

import re
import unicodedata
from typing import TypedDict


# ══════════════════════════════════════════════════════════════════════════════
# OUTPUT SCHEMA
# ══════════════════════════════════════════════════════════════════════════════

class PreprocessedInput(TypedDict):
    """Structured output produced by the NLP pipeline."""
    clean_text : str          # Cleaned, ready-to-send text
    intent     : str          # Detected intent label
    source     : str          # Original source/mode string
    metadata   : dict         # Token count, flags, language hints, etc.


# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS — INTENT SIGNALS
# ══════════════════════════════════════════════════════════════════════════════

# Each intent maps to a set of trigger keywords / regex patterns.
# Order matters: more specific intents are checked first.
_INTENT_RULES: list[tuple[str, list[str]]] = [
    # ── Code / programming ────────────────────────────────────────────────
    ("coding", [
        r"\bcode\b", r"\bprogram\b", r"\bscript\b", r"\bfunction\b",
        r"\bclass\b", r"\bdebugg?\b", r"\bfix\s+(?:the\s+)?(?:bug|error|issue)\b",
        r"\bwrite\s+(?:a\s+)?(?:python|js|java|c\+\+|typescript|sql|bash|html|css)\b",
        r"\bimplement\b", r"\brefactor\b", r"\boptimize\s+(?:the\s+)?code\b",
        r"\bapi\b", r"\bsyntax\b", r"\balgorithm\b", r"\bdata\s+structure\b",
        r"\bloop\b", r"\brecursion\b", r"\blambda\b", r"\bregex\b",
        r"\bgit\b", r"\bdocker\b", r"\bdjango\b", r"\bflask\b", r"\breact\b",
    ]),

    # ── Web search / research ─────────────────────────────────────────────
    ("web_search", [
        r"\bsearch\s+(?:for\s+)?(?:the\s+)?(?:web|internet|online)?\b",
        r"\bwhat\s+is\s+(?:the\s+)?(?:latest|current|recent|news)\b",
        r"\bfind\s+(?:me\s+)?(?:information|info|data|articles?|results?)\b",
        r"\blook\s+up\b", r"\bwho\s+(?:is|was|are|were)\b",
        r"\bwhere\s+(?:is|can|do)\b", r"\bwhen\s+(?:is|did|was|will)\b",
        r"\bhow\s+much\s+(?:does|is|are|do)\b",
        r"\bprice\s+of\b", r"\bstock\s+(?:price|market)\b",
        r"\bweather\b", r"\bnews\b", r"\btoday\b", r"\blatest\b",
        r"\brecent\b", r"\bcurrent\b", r"\blive\b",
    ]),

    # ── Task automation / actions ─────────────────────────────────────────
    ("task", [
        r"\bremind\b", r"\bschedule\b", r"\bset\s+(?:a\s+)?(?:timer|alarm|reminder)\b",
        r"\bcreate\s+(?:a\s+)?(?:file|folder|document|list|task)\b",
        r"\bsend\s+(?:an?\s+)?(?:email|message|notification)\b",
        r"\bautomate\b", r"\brun\s+(?:a\s+)?(?:script|command|task)\b",
        r"\bdownload\b", r"\bupload\b", r"\bbackup\b",
        r"\borganize\b", r"\bmanage\b",
    ]),

    # ── File / document analysis ──────────────────────────────────────────
    ("file_analysis", [
        r"\banalyze\s+(?:this\s+)?(?:file|document|pdf|image|csv|spreadsheet)\b",
        r"\bread\s+(?:this\s+)?(?:file|document)\b",
        r"\bsummarize\s+(?:this\s+)?(?:file|document|pdf|text)\b",
        r"\bextract\s+(?:data|text|info)\s+from\b",
        r"\bwhat\s+(?:does\s+)?(?:this\s+)?file\s+(?:say|contain|show)\b",
    ]),

    # ── Creative writing ──────────────────────────────────────────────────
    ("creative", [
        r"\bwrite\s+(?:a\s+)?(?:story|poem|essay|blog\s+post|song|lyrics?|script)\b",
        r"\bcompose\b", r"\bcreate\s+(?:a\s+)?(?:story|poem|essay)\b",
        r"\bimagine\b", r"\bbrainstorm\b", r"\bgive\s+me\s+(?:ideas?|suggestions?)\b",
        r"\bhelp\s+me\s+write\b",
    ]),

    # ── Math / calculations ───────────────────────────────────────────────
    ("math", [
        r"\bcalculate\b", r"\bcompute\b", r"\bsolve\b",
        r"\bwhat\s+is\s+\d+", r"\bequation\b", r"\bformula\b",
        r"\bintegral\b", r"\bderivative\b", r"\bstatistics?\b",
        r"\bprobability\b", r"\bmatrix\b",
    ]),

    # ── Voice / conversational ────────────────────────────────────────────
    ("voice_chat", [
        r"\bhey\s+(?:baymax|hero|ai)\b", r"\bhello\b", r"\bhi\b",
        r"\bwhat\'?s\s+up\b", r"\bhow\s+are\s+you\b",
        r"\btalk\s+to\s+me\b", r"\bchat\s+(?:with\s+me)?\b",
        r"\bwho\s+are\s+you\b", r"\bwhat\s+are\s+you\b",
        r"\bwhich\s+model\b", r"\bare\s+you\b",
    ]),

    # ── Explanation / learning ────────────────────────────────────────────
    ("explain", [
        r"\bexplain\b", r"\bwhat\s+(?:is|are|does|do)\b",
        r"\bhow\s+(?:does|do|to|can)\b", r"\bwhy\s+(?:is|are|does|do)\b",
        r"\bteach\s+me\b", r"\bhelp\s+me\s+understand\b",
        r"\bdifference\s+between\b", r"\bcompare\b",
        r"\bdefine\b", r"\bmeaning\s+of\b",
    ]),

    # ── General chat (catch-all) ──────────────────────────────────────────
    ("chat", []),  # Always matches as the final fallback
]

# ── Source → default intent mapping ──────────────────────────────────────────
# Used when the source already tells us the intent unambiguously.
_SOURCE_INTENT_MAP: dict[str, str] = {
    "coding":        "coding",
    "websearch":     "web_search",
    "Voice Chat":    "voice_chat",
    "voice_message": "voice_chat",
    "file_handle":   "file_analysis",
    "live_display":  "task",
    # "text" and "" → run full detection
}


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1 — NOISE REMOVAL
# ══════════════════════════════════════════════════════════════════════════════

def _remove_noise(text: str) -> str:
    """
    Strip characters and patterns that add no semantic value.

    Removes:
    - Zero-width / invisible Unicode characters
    - Repeated punctuation (e.g. '???' → '?', '!!!' → '!')
    - Excessive whitespace (tabs, newlines → single space)
    - Leading / trailing whitespace
    """
    # Normalize Unicode to NFC (canonical composition)
    text = unicodedata.normalize("NFC", text)

    # Remove zero-width and control characters (except newline \n, tab \t)
    text = re.sub(r"[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]", "", text)

    # Collapse repeated punctuation: '???' → '?', '!!!' → '!'
    text = re.sub(r"([!?.]){2,}", r"\1", text)

    # Replace multiple spaces / tabs with a single space
    text = re.sub(r"[ \t]+", " ", text)

    # Replace multiple newlines with a single newline
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Strip leading and trailing whitespace
    text = text.strip()

    return text


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2 — TEXT NORMALIZATION  (lowercase snapshot for analysis only)
# ══════════════════════════════════════════════════════════════════════════════

def _normalize(text: str) -> str:
    """
    Return a lowercase, collapsed version of the text used ONLY
    for intent detection. The original casing is always preserved in
    `clean_text` so code, names, and proper nouns are not mangled.
    """
    return text.lower().strip()


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3 — BASIC CLEANING
# ══════════════════════════════════════════════════════════════════════════════

def _basic_clean(text: str, source: str) -> str:
    """
    Light cleaning that preserves meaningful content.

    - Voice sources: collapse newlines to spaces (speech has no line breaks)
    - All sources: strip leading/trailing punctuation that is clearly junk
    - Preserve code blocks, URLs, and structured text
    """
    is_voice = source in ("Voice Chat", "voice_message")

    if is_voice:
        # Voice transcripts arrive as a single flat string; normalize spaces
        text = re.sub(r"\s+", " ", text).strip()
        # Remove filler words that STT engines commonly inject
        fillers = r"\b(um+|uh+|er+|hmm+|mhm+|ah+|like\s+uh|you\s+know)\b"
        text = re.sub(fillers, "", text, flags=re.IGNORECASE)
        text = re.sub(r" {2,}", " ", text).strip()

    # Strip leading/trailing junk punctuation (but keep sentence-end ones)
    text = re.sub(r"^[\-_=~`•·]+|[\-_=~`•·]+$", "", text).strip()

    return text


# ══════════════════════════════════════════════════════════════════════════════
# STEP 4 — INTENT DETECTION
# ══════════════════════════════════════════════════════════════════════════════

def _detect_intent(text: str, source: str) -> str:
    """
    Determine the user's intent using a two-pass approach:

    Pass 1 — Source override:
        If the frontend already signals the mode (coding, websearch, etc.)
        we trust that and skip heavy text analysis. This is correct ~100%
        of the time because the user explicitly selected the mode.

    Pass 2 — Rule-based keyword matching:
        Iterate through _INTENT_RULES in priority order.
        First rule whose any pattern matches the normalised text wins.
        Final entry ("chat", []) always matches as the fallback.
    """
    # Pass 1: source override (only for persistent modes)
    persistent_sources = ("coding", "websearch", "Voice Chat", "file_handle", "live_display")
    if source in persistent_sources and source in _SOURCE_INTENT_MAP:
        return _SOURCE_INTENT_MAP[source]

    # Pass 2: keyword / regex matching on normalised text
    lowered = _normalize(text)
    for intent, patterns in _INTENT_RULES:
        if not patterns:          # catch-all "chat" entry
            return intent
        for pattern in patterns:
            if re.search(pattern, lowered):
                return intent

    return "chat"   # absolute fallback (should never reach here)


# ══════════════════════════════════════════════════════════════════════════════
# STEP 5 — METADATA ENRICHMENT
# ══════════════════════════════════════════════════════════════════════════════

def _build_metadata(original: str, clean: str, intent: str, source: str) -> dict:
    """
    Attach lightweight metadata that downstream modules (views.py,
    hero_model.py) can use for logging, routing decisions, or rate-limiting.

    Fields:
    - token_estimate  : rough word-count proxy for token budgeting
    - char_count      : character length of the clean text
    - has_code_block  : True if the text contains a markdown code fence
    - has_url         : True if the text contains a URL
    - has_question    : True if the text ends with '?' or contains wh-words
    - is_short        : True if clean_text is ≤ 12 words (voice-friendly)
    - language_hint   : 'en' (extendable; currently always 'en')
    - source_changed  : True if inferred intent differs from source default
    """
    words          = clean.split()
    token_estimate = len(words)
    source_default = _SOURCE_INTENT_MAP.get(source, "chat")

    metadata = {
        "token_estimate": token_estimate,
        "char_count":     len(clean),
        "has_code_block": bool(re.search(r"```[\s\S]*?```|`[^`]+`", original)),
        "has_url":        bool(re.search(r"https?://\S+|www\.\S+", original)),
        "has_question":   bool(
            clean.rstrip().endswith("?") or
            re.search(r"\b(?:what|who|where|when|why|how|which|whose|whom)\b",
                      clean, re.IGNORECASE)
        ),
        "is_short":       token_estimate <= 12,
        "language_hint":  "en",     # placeholder — extend with langdetect if needed
        "source_changed": intent != source_default,
    }
    return metadata


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

def preprocess(text: str, source: str = "text") -> PreprocessedInput:
    """
    Run the full NLP preprocessing pipeline on a user message.

    Parameters
    ----------
    text   : Raw user input string (from any source).
    source : The frontend mode string. Accepted values match the project's
             existing mode keys:
               "text"         – default text chat
               "coding"       – coding mode
               "websearch"    – web search mode
               "Voice Chat"   – full voice conversation
               "voice_message"– inline mic message
               "file_handle"  – file upload chat
               "live_display" – live screen / display mode

    Returns
    -------
    PreprocessedInput dict with keys:
        clean_text, intent, source, metadata
    """
    if not isinstance(text, str):
        text = str(text)

    # Guard: return a safe default for empty input
    if not text.strip():
        return PreprocessedInput(
            clean_text="",
            intent="chat",
            source=source,
            metadata={"token_estimate": 0, "char_count": 0, "has_code_block": False,
                      "has_url": False, "has_question": False, "is_short": True,
                      "language_hint": "en", "source_changed": False},
        )

    original  = text                          # keep for metadata inspection

    # ── Pipeline ─────────────────────────────────────────────────────────────
    step1 = _remove_noise(original)           # Step 1: noise removal
    step2 = _basic_clean(step1, source)       # Step 2 & 3: normalize + clean
    clean = step2                             # final clean text

    intent   = _detect_intent(clean, source)  # Step 4: intent detection
    metadata = _build_metadata(              # Step 5: metadata
        original, clean, intent, source
    )
    # ─────────────────────────────────────────────────────────────────────────

    return PreprocessedInput(
        clean_text=clean,
        intent=intent,
        source=source,
        metadata=metadata,
    )


# ══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE HELPERS  (used directly by views.py / hero_model.py)
# ══════════════════════════════════════════════════════════════════════════════

def get_clean_text(text: str, source: str = "text") -> str:
    """Return only the cleaned text. Useful for quick inline calls."""
    return preprocess(text, source)["clean_text"]


def get_intent(text: str, source: str = "text") -> str:
    """Return only the detected intent label."""
    return preprocess(text, source)["intent"]


def resolve_mode(preprocessed: PreprocessedInput, current_mode: str) -> str:
    """
    Suggest the best handler mode for views.py / Baymax based on
    preprocessed intent vs the frontend-declared mode.

    Rules:
    - If the frontend mode is explicit and persistent (coding, websearch, file_handle)
      always honour it — the user made a deliberate choice.
    - If mode is "text" or "voice_message" (transient), and NLP detected a 
      stronger specific intent (like coding), return the NLP-inferred mode.
    - Otherwise keep the current_mode unchanged.
    """
    # Persistent explicit mode beats NLP inference
    # Note: "voice_message" is transient, so we allow NLP overrides
    persistent_modes = ("coding", "websearch", "Voice Chat", "file_handle", "live_display")
    if current_mode in persistent_modes:
        return current_mode

    intent = preprocessed["intent"]

    # If the user used the mic but didn't trigger a specific intent,
    # we preserve voice_message so they get the short voice-optimized response.
    if current_mode == "voice_message" and intent == "chat":
        return "voice_message"

    # Map NLP intent back to the Baymax handler mode strings
    _intent_to_mode: dict[str, str] = {
        "coding":        "coding",
        "web_search":    "websearch",
        "voice_chat":    "Voice Chat",
        "file_analysis": "file_handle",
        "task":          "text",
        "creative":      "text",
        "math":          "text",
        "explain":       "text",
        "chat":          "text",
    }
    return _intent_to_mode.get(intent, current_mode)


# ══════════════════════════════════════════════════════════════════════════════
# BATCH PROCESSING  (optional — useful for analysis / logging pipelines)
# ══════════════════════════════════════════════════════════════════════════════

def preprocess_batch(
    items: list[dict[str, str]],
) -> list[PreprocessedInput]:
    """
    Process a list of {"text": ..., "source": ...} dicts in one call.
    Useful for offline log analysis or bulk intent classification.

    Example:
        results = preprocess_batch([
            {"text": "write a python function", "source": "text"},
            {"text": "latest AI news",          "source": "websearch"},
        ])
    """
    return [preprocess(item.get("text", ""), item.get("source", "text"))
            for item in items]