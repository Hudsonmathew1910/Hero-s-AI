"""
infinsight/services/embeddings.py
-----------------------------------
Handles embedding generation and Pinecone vector store operations.
Uses the new 'google-genai' SDK.
"""

import logging
import time
import traceback
from typing import Optional
from google import genai

logger = logging.getLogger("infinsight.embeddings")

_CACHED_EMBEDDING_MODEL = "text-embedding-004" # Default to latest stable

def _get_embedding_model_name(api_key: str) -> str:
    global _CACHED_EMBEDDING_MODEL
    # We'll use the cached name or just return the standard latest model
    return _CACHED_EMBEDDING_MODEL

# Pinecone embedding dimension for text-embedding-004
EMBEDDING_DIM = 768
PINECONE_INDEX_NAME = "infinsight"

_pinecone_index = None

def _get_pinecone_index():
    """Lazy-load and cache the Pinecone index client."""
    global _pinecone_index
    if _pinecone_index is not None:
        return _pinecone_index
    try:
        from pinecone import Pinecone
        from django.conf import settings

        if not settings.PINECONE_API_KEY:
            raise ValueError("PINECONE_API_KEY is missing from environment variables.")

        pc = Pinecone(api_key=settings.PINECONE_API_KEY)
        _pinecone_index = pc.Index(settings.PINECONE_INDEX_NAME or "infinsight")
        logger.info("Pinecone index connected: %s", settings.PINECONE_INDEX_NAME)
        return _pinecone_index
    except Exception as e:
        logger.error("Pinecone init failed: %s", e)
        raise

def generate_embedding(text: str, gemini_api_key: str) -> list[float]:
    """Generate embedding using the new google-genai SDK."""
    try:
        client = genai.Client(api_key=gemini_api_key)
        model_name = _get_embedding_model_name(gemini_api_key)
        
        # New SDK embed_content call
        result = client.models.embed_content(
            model=model_name,
            contents=text,
            config={"task_type": "RETRIEVAL_DOCUMENT"}
        )
        return result.embeddings[0].values
    except Exception as e:
        logger.error("Embedding generation failed: %s", e)
        raise

def generate_query_embedding(query: str, gemini_api_key: str) -> list[float]:
    """Generate query embedding using the new google-genai SDK."""
    try:
        client = genai.Client(api_key=gemini_api_key)
        model_name = _get_embedding_model_name(gemini_api_key)
        
        result = client.models.embed_content(
            model=model_name,
            contents=query,
            config={"task_type": "RETRIEVAL_QUERY"}
        )
        return result.embeddings[0].values
    except Exception as e:
        logger.error("Query embedding failed: %s", e)
        raise

def upsert_chunks(chunks: list[dict], namespace: str, gemini_api_key: str) -> int:
    """Upsert vectors into Pinecone."""
    index = _get_pinecone_index()
    vectors = []

    for i, chunk in enumerate(chunks):
        text = chunk["text"]
        meta = chunk.get("metadata", {})

        if not text or not text.strip():
            continue

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
                    "text": text[:2000],
                    "chunk_index": i,
                },
            })
        except Exception as e:
            logger.warning("Skipping chunk %d due to error: %s", i, e)
            continue

    if not vectors:
        raise ValueError("No valid vectors generated.")

    batch_size = 100
    total = 0
    for start in range(0, len(vectors), batch_size):
        batch = vectors[start : start + batch_size]
        index.upsert(vectors=batch, namespace=namespace)
        total += len(batch)

    return total

def query_chunks(query_embedding: list[float], namespace: str, top_k: int = 8) -> list[dict]:
    """Search Pinecone."""
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
    """Delete namespace."""
    try:
        index = _get_pinecone_index()
        index.delete(delete_all=True, namespace=namespace)
    except Exception as e:
        logger.warning("Could not delete namespace %s: %s", namespace, e)