"""
infinsight/services/embeddings.py
-----------------------------------
Handles embedding generation and Pinecone vector store operations.
Uses Google's embedding-001 model via the generativeai SDK.
"""

import logging
import time
import traceback
from typing import Optional

_CACHED_EMBEDDING_MODEL = None

def _get_embedding_model_name(api_key: str) -> str:
    global _CACHED_EMBEDDING_MODEL
    if _CACHED_EMBEDDING_MODEL:
        return _CACHED_EMBEDDING_MODEL
        
    from google import genai
    client = genai.Client(api_key=api_key)
    
    try:
        for m in client.models.list():
            if 'embed_content' in getattr(m, 'supported_generation_methods', []) or 'embedContent' in getattr(m, 'supported_generation_methods', []):
                _CACHED_EMBEDDING_MODEL = m.name
                return m.name
    except Exception as e:
        logger.warning(f"Could not list models: {e}. Falling back to default.")
            
    # Stable default for production
    _CACHED_EMBEDDING_MODEL = "text-embedding-004"
    return _CACHED_EMBEDDING_MODEL

logger = logging.getLogger("infinsight.embeddings")

# Pinecone embedding dimension for text-embedding-004
EMBEDDING_DIM = 768
PINECONE_INDEX_NAME = "infinsight"  # Set in .env or hardcode your index name


# ─────────────────────────────────────────────────────────────────────────────
# Pinecone Client (lazy-loaded singleton)
# ─────────────────────────────────────────────────────────────────────────────

_pinecone_index = None


def _get_pinecone_index():
    """Lazy-load and cache the Pinecone index client."""
    global _pinecone_index
    if _pinecone_index is not None:
        return _pinecone_index
    try:
        from pinecone import Pinecone
        from django.conf import settings

        pc = Pinecone(api_key=settings.PINECONE_API_KEY)
        _pinecone_index = pc.Index(settings.PINECONE_INDEX_NAME)
        logger.info("Pinecone index connected: %s", settings.PINECONE_INDEX_NAME)
        return _pinecone_index
    except Exception as e:
        logger.error("Pinecone init failed: %s", e)
        raise


# ─────────────────────────────────────────────────────────────────────────────
# Embedding generation
# ─────────────────────────────────────────────────────────────────────────────

def generate_embedding(text: str, gemini_api_key: str) -> list[float]:
    """
    Generate a single embedding vector for the given text.
    Uses Google's text-embedding-004 model (768 dims).
    """
    try:
        from google import genai
        client = genai.Client(api_key=gemini_api_key)

        model_name = _get_embedding_model_name(gemini_api_key)
        result = client.models.embed_content(
            model=model_name,
            contents=text,
            config={"task_type": "RETRIEVAL_DOCUMENT"},
        )
        return result.embeddings[0].values
    except Exception as e:
        from google.api_core import exceptions
        if isinstance(e, exceptions.ResourceExhausted):
            logger.warning("Gemini Embedding Rate Limit reached.")
            raise ValueError("You reached Gemini embedding rate limit. Please try again later.")
        elif isinstance(e, exceptions.Unauthenticated):
            logger.error("Gemini Authentication failed for embeddings.")
            raise ValueError("Invalid Gemini API Key.")
        
        logger.error("Embedding generation failed: %s", e)
        raise


def generate_query_embedding(query: str, gemini_api_key: str) -> list[float]:
    """Generate embedding specifically for a search query."""
    try:
        from google import genai
        client = genai.Client(api_key=gemini_api_key)

        model_name = _get_embedding_model_name(gemini_api_key)
        result = client.models.embed_content(
            model=model_name,
            contents=query,
            config={"task_type": "RETRIEVAL_QUERY"},
        )
        return result.embeddings[0].values
    except Exception as e:
        from google.api_core import exceptions
        if isinstance(e, exceptions.ResourceExhausted):
            raise ValueError("You reached Gemini rate limit. Please try again later.")
        
        logger.error("Query embedding failed: %s", e)
        raise


# ─────────────────────────────────────────────────────────────────────────────
# Pinecone operations
# ─────────────────────────────────────────────────────────────────────────────

def upsert_chunks(chunks: list[dict], namespace: str, gemini_api_key: str) -> int:
    """
    Generate embeddings for all chunks and upsert into Pinecone.
    chunks: [{"text": "...", "metadata": {...}}]
    Returns: number of vectors upserted.
    """
    index = _get_pinecone_index()
    vectors = []

    for i, chunk in enumerate(chunks):
        text = chunk["text"]
        meta = chunk.get("metadata", {})

        if not text or not text.strip():
            continue

        # Rate-limit-safe: small delay every 10 embeddings
        if i > 0 and i % 10 == 0:
            time.sleep(0.5)

        try:
            embedding = generate_embedding(text[:8000], gemini_api_key)
            vector_id = f"{namespace}_chunk_{i}"
            vectors.append({
                "id": vector_id,
                "values": embedding,
                "metadata": {
                    **meta,
                    "text": text[:2000],  # Pinecone metadata limit
                    "chunk_index": i,
                },
            })
        except Exception as e:
            logger.warning("Skipping chunk %d due to embedding error: %s", i, e)
            continue

    if not vectors:
        raise ValueError("No valid vectors generated from chunks.")

    # Upsert in batches of 100
    batch_size = 100
    total = 0
    for start in range(0, len(vectors), batch_size):
        batch = vectors[start : start + batch_size]
        index.upsert(vectors=batch, namespace=namespace)
        total += len(batch)
        logger.info("Upserted batch %d/%d vectors", total, len(vectors))

    return total


def query_chunks(
    query_embedding: list[float],
    namespace: str,
    top_k: int = 8,
) -> list[dict]:
    """
    Search Pinecone for the most relevant chunks.
    Returns list of {"text": "...", "score": float, "metadata": {...}}
    """
    index = _get_pinecone_index()
    try:
        results = index.query(
            vector=query_embedding,
            top_k=top_k,
            namespace=namespace,
            include_metadata=True,
        )
        hits = []
        for match in results.get("matches", []):
            meta = match.get("metadata", {})
            hits.append({
                "text": meta.get("text", ""),
                "score": round(match.get("score", 0), 4),
                "metadata": {k: v for k, v in meta.items() if k != "text"},
            })
        return hits
    except Exception as e:
        logger.error("Pinecone query failed: %s", e)
        raise


def delete_namespace(namespace: str) -> None:
    """Delete all vectors in a namespace (called when session is deleted)."""
    try:
        index = _get_pinecone_index()
        index.delete(delete_all=True, namespace=namespace)
        logger.info("Deleted Pinecone namespace: %s", namespace)
    except Exception as e:
        logger.warning("Could not delete namespace %s: %s", namespace, e)