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
        # User recommended working models for Gemini v1beta
        _CACHED_EMBEDDING_MODEL = "models/gemini-embedding-001"
        return _CACHED_EMBEDDING_MODEL
    except Exception as e:
        logger.warning(f"Error selecting model: {e}")
            
    # Safest fallback as recommended by user
    _CACHED_EMBEDDING_MODEL = "models/gemini-embedding-2"
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


def generate_query_embedding(query: str, api_key: str) -> list[float]:
    """Generate a vector for a single search query using the recommended Gemini models."""
    from google import genai
    client = genai.Client(api_key=api_key)
    model_name = _get_embedding_model_name(api_key)

    try:
        result = client.models.embed_content(
            model=model_name,
            contents=query,
            config={"task_type": "RETRIEVAL_QUERY"},
        )
        return result.embeddings[0].values
    except Exception as e:
        logger.warning(f"Embedding failed with {model_name}: {e}. Trying fallback models/gemini-embedding-2...")
        try:
            # Safest fallback as recommended by user
            result = client.models.embed_content(
                model="models/gemini-embedding-2",
                contents=query,
                config={"task_type": "RETRIEVAL_QUERY"},
            )
            return result.embeddings[0].values
        except Exception as e2:
            logger.error(f"Fallback embedding also failed: {e2}")
            raise e


# ─────────────────────────────────────────────────────────────────────────────
# Pinecone operations
# ─────────────────────────────────────────────────────────────────────────────

def upsert_chunks(chunks: list[dict], namespace: str, api_key: str) -> int:
    """Batch embed and upsert chunks to Pinecone."""
    from google import genai
    client = genai.Client(api_key=api_key)
    model_name = _get_embedding_model_name(api_key)
    index = _get_pinecone_index()

    batch_size = 50
    total_upserted = 0

    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        texts = [c["text"] for c in batch]
        
        try:
            res = client.models.embed_content(
                model=model_name,
                contents=texts,
                config={"task_type": "RETRIEVAL_DOCUMENT"},
            )
            embeddings = [e.values for e in res.embeddings]
        except Exception as e:
            logger.warning(f"Batch embedding failed with {model_name}: {e}. Trying fallback models/gemini-embedding-2...")
            try:
                res = client.models.embed_content(
                    model="models/gemini-embedding-2",
                    contents=texts,
                    config={"task_type": "RETRIEVAL_DOCUMENT"},
                )
                embeddings = [e.values for e in res.embeddings]
            except Exception as e2:
                logger.error(f"Batch fallback embedding failed: {e2}")
                raise e

        vectors = []
        for j, emb in enumerate(embeddings):
            chunk = batch[j]
            vectors.append({
                "id": f"{namespace}_{i+j}",
                "values": emb,
                "metadata": {
                    "text": chunk["text"],
                    "session_id": namespace,
                    "type": chunk["metadata"].get("type", "text"),
                    "page": chunk["metadata"].get("page", 0)
                }
            })

        index.upsert(vectors=vectors, namespace=namespace)
        total_upserted += len(vectors)

    return total_upserted


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