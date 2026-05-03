"""
infinsight/services/rag.py
---------------------------
RAG orchestration layer.
Coordinates: file parsing → embedding → Pinecone → LLM response.
"""

import logging
import time
import traceback

from .file_parses import parse_file
from .Embedding import upsert_chunks, generate_query_embedding, query_chunks, delete_namespace
from .Llm import generate_analyst_response, generate_session_title, generate_final_interpretation
from .analyst_engine import load_dataset, get_df_schema, execute_pandas_query

logger = logging.getLogger("infinsight.rag")


# ─────────────────────────────────────────────────────────────────────────────
# Ingestion pipeline
# ─────────────────────────────────────────────────────────────────────────────

def ingest_file(session, file_obj, file_type: str, gemini_api_key: str) -> dict:
    """
    Full ingestion pipeline for a newly uploaded file.
    1. Parse file → chunks
    2. Generate embeddings → upsert to Pinecone
    3. Update session status
    """
    from infinsight.models import ProjectSession

    try:
        t_start = time.time()
        print(f"--- [INF] Ingestion Started for session {session.session_id} ---")
        logger.info("Starting ingestion for session %s | type=%s", session.session_id, file_type)

        # Step 1: Parse
        t0 = time.time()
        chunks, metadata = parse_file(file_obj, file_type)
        print(f"--- [INF] Step 1: File parsed ({len(chunks)} chunks) in {time.time() - t0:.2f}s ---")
        logger.info("Parsed %d chunks from %s", len(chunks), file_type)

        if not chunks:
            raise ValueError("File produced no parseable content.")

        # Step 2: Embed + store
        t1 = time.time()
        namespace = session.pinecone_namespace
        count = upsert_chunks(chunks, namespace, gemini_api_key)
        print(f"--- [INF] Step 2: Embeddings upserted ({count} vectors) in {time.time() - t1:.2f}s ---")
        logger.info("Upserted %d vectors into namespace %s", count, namespace)

        # Step 3: Update session
        session.status = "ready"
        session.chunk_count = count
        session.uploaded_file.metadata = metadata
        session.uploaded_file.save(update_fields=["metadata"])
        session.save(update_fields=["status", "chunk_count"])

        print(f"--- [INF] Ingestion Completed in {time.time() - t_start:.2f}s ---")
        return {"success": True, "chunk_count": count, "metadata": metadata, "error": None}

    except Exception as e:
        tb = traceback.format_exc()
        logger.error("Ingestion failed for session %s: %s\n%s", session.session_id, e, tb)
        session.status = "error"
        session.error_message = str(e)[:500]
        session.save(update_fields=["status", "error_message"])
        return {"success": False, "chunk_count": 0, "metadata": {}, "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# Query pipeline
# ─────────────────────────────────────────────────────────────────────────────

def query_session(
    session,
    user_message: str,
    gemini_api_key: str,
    chat_history: list[dict] = None,
) -> dict:
    """
    Full RAG query pipeline for a session with dynamic analysis.
    """
    if chat_history is None:
        chat_history = []

    try:
        if session.status != "ready":
            return {
                "reply": f"This session is still **{session.status}**. Please wait for processing to complete.",
                "model": "none",
                "sources": [],
                "error": "session_not_ready",
            }

        # --- 1. Preparation: Schema & DF ---
        t0 = time.time()
        file_path = session.uploaded_file.file.path
        file_type = session.uploaded_file.file_type
        
        # Load schema for LLM
        df = None
        schema_text = ""
        if file_type in ["csv", "excel"]:
            df = load_dataset(file_path, file_type)
            schema_text = get_df_schema(df)
        print(f"--- [INF] Step 1: Schema/Data loaded in {time.time() - t0:.2f}s ---")

        # --- 2. Step 1: LLM Call (Think or Answer) ---
        t1 = time.time()
        # Search Pinecone for textual context (always useful)
        query_embedding = generate_query_embedding(user_message, gemini_api_key)
        hits = query_chunks(query_embedding, session.pinecone_namespace, top_k=8)

        reply, model_used = generate_analyst_response(
            user_message=user_message,
            context_chunks=hits,
            gemini_api_key=gemini_api_key,
            chat_history=chat_history,
            session_name=session.session_name,
            schema=schema_text
        )
        print(f"--- [INF] Step 2: RAG & LLM Think completed in {time.time() - t1:.2f}s ---")

        # --- 3. Step 2: Dynamic Execution if requested ---
        if "```python_pandas" in reply:
            import re
            code_match = re.search(r"```python_pandas\n(.*?)```", reply, re.DOTALL)
            if code_match:
                t2 = time.time()
                code = code_match.group(1).strip()
                logger.info("Executing dynamic analyst code for session %s", session.session_id)
                
                # Run the code
                exec_result = execute_pandas_query(df, code)
                print(f"--- [INF] Step 3: Code execution completed in {time.time() - t2:.2f}s ---")
                
                if exec_result["success"]:
                    # Pass results back for interpretation
                    t3 = time.time()
                    reply = generate_final_interpretation(
                        user_message=user_message,
                        code_execution_result=exec_result["result"],
                        gemini_api_key=gemini_api_key,
                        chat_history=chat_history
                    )
                    print(f"--- [INF] Step 4: Final interpretation completed in {time.time() - t3:.2f}s ---")
                else:
                    # Log the technical error for the developer
                    logger.error("Dynamic analysis failed: %s\n%s", exec_result['error'], exec_result.get('traceback', ''))
                    # Send a friendly message to the user
                    reply = "I encountered an issue while analyzing the data. This might be due to an unexpected format in your file or a complex calculation requirement. Could you try rephrasing your question?"

        return {
            "reply": reply,
            "model": model_used,
            "sources": [{"score": h["score"], "type": h["metadata"].get("type", "")} for h in hits[:2]],
            "error": None,
        }

    except Exception as e:
        tb = traceback.format_exc()
        logger.error("Query failed for session %s: %s\n%s", session.session_id, e, tb)
        return {
            "reply": f"Analysis Error: {str(e)}",
            "model": "error",
            "sources": [],
            "error": str(e),
        }



# ─────────────────────────────────────────────────────────────────────────────
# Session title generation
# ─────────────────────────────────────────────────────────────────────────────

def get_session_title(file_name: str, file_type: str, gemini_api_key: str) -> str:
    """Wrapper around LLM title generation with fallback."""
    try:
        return generate_session_title(file_name, file_type, gemini_api_key)
    except Exception:
        return file_name.rsplit(".", 1)[0][:100]


# ─────────────────────────────────────────────────────────────────────────────
# Cleanup
# ─────────────────────────────────────────────────────────────────────────────

def cleanup_session(session) -> None:
    """Delete Pinecone vectors when a session is removed."""
    try:
        delete_namespace(session.pinecone_namespace)
    except Exception as e:
        logger.warning("Pinecone cleanup failed for %s: %s", session.session_id, e)