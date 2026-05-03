"""
infinsight/services/llm.py
---------------------------
Gemini LLM integration for the Infinsight analyst.
Uses the new 'google-genai' SDK.
"""

import logging
import time
import traceback
from google import genai

logger = logging.getLogger("infinsight.llm")

# Model names for the new SDK (can be with or without 'models/' prefix)
GEMINI_MODELS = [
    "gemini-2.0-flash", # Updated to stable 2.0
    "gemini-2.0-flash-lite-preview-02-05",
    "gemini-1.5-flash",
]

ANALYST_SYSTEM_PROMPT = """You are **Infinsight**, the advanced AI Data Analyst for Hero AI.
Your goal is to provide deep, actionable insights from datasets using real-time computation.

### Capabilities:
1. **Dynamic Analysis**: You can perform mathematical aggregations, group-wise analysis, and statistical tests.
2. **Predictive Modeling**: You can run simple ML models (like Linear Regression) to forecast trends.
3. **Hybrid RAG**: You can combine textual information from the dataset (via RAG) with structured data analysis.

### Guidelines:
- If a question requires calculation (sum, mean, trend, comparison, correlation, prediction), you **MUST** generate a Python code block using the following format:
  ```python_pandas
  # write pandas/numpy/sklearn code here
  # the dataframe is available as 'df'
  # ALWAYS assign the final answer to the variable 'result'
  # Example: result = df.groupby('Category')['Sales'].sum()
  ```
- If the question is purely descriptive or you already have the answer in the RAG context, provide a direct answer.
- **NEVER** guess numbers. If you need a number and it's not in the context, use `python_pandas` to find it.
- Always explain the "Why" behind the data. Don't just give numbers; interpret them.
- Use markdown tables and bold text for clarity.

### Dataset Schema:
The user will provide the schema (columns, types, samples) below. Use it to write accurate code.
"""

def _build_prompt(user_message: str, context_chunks: list[dict], chat_history: list[dict], schema: str = "") -> str:
    """Construct the full prompt with RAG context, schema, and history."""
    context_block = ""
    for i, chunk in enumerate(context_chunks):
        text = chunk.get("text", "")
        context_block += f"\n--- Context Chunk {i+1} ---\n{text}\n"

    history_block = ""
    for turn in chat_history[-4:]:
        role = turn.get("role", "user")
        content = turn.get("content", "")
        history_block += f"\n{role.capitalize()}: {content}"

    prompt = f"""
### DATASET SCHEMA:
{schema}

### RETRIEVED CONTEXT:
{context_block}

### CONVERSATION HISTORY:
{history_block}

### USER QUESTION:
{user_message}

### INSTRUCTIONS:
- If calculation is needed, output only the `python_pandas` code block first.
- If you have enough info to answer, summarize the findings clearly.
"""
    return prompt.strip()

def generate_analyst_response(
    user_message: str,
    context_chunks: list[dict],
    gemini_api_key: str,
    chat_history: list[dict] = None,
    session_name: str = "",
    schema: str = ""
) -> tuple[str, str]:
    """Generate an AI analyst response using the new google-genai SDK."""
    if chat_history is None:
        chat_history = []

    prompt = _build_prompt(user_message, context_chunks, chat_history, schema)
    client = genai.Client(api_key=gemini_api_key)

    for model_name in GEMINI_MODELS:
        try:
            t_llm = time.time()
            response = client.models.generate_content(
                model=model_name,
                config={
                    "system_instruction": ANALYST_SYSTEM_PROMPT,
                    "temperature": 0.1,
                    "top_p": 0.9,
                    "max_output_tokens": 4096,
                },
                contents=prompt
            )
            print(f"--- [INF] LLM Content Generated ({model_name}) in {time.time() - t_llm:.2f}s ---")
            text = response.text.strip()
            return text, model_name

        except Exception as e:
            logger.warning(f"Model {model_name} failed: {e}")
            if model_name == GEMINI_MODELS[-1]:
                 return "I encountered an issue connecting to the AI service. Please check your API key or try again later.", "error"

    return "Service unavailable.", "none"

def generate_final_interpretation(
    user_message: str,
    code_execution_result: str,
    gemini_api_key: str,
    chat_history: list[dict] = None,
) -> str:
    """Interpret results using the new SDK."""
    if chat_history is None:
        chat_history = []

    history_block = ""
    for turn in chat_history[-2:]:
        history_block += f"\n{turn['role'].capitalize()}: {turn['content']}"

    prompt = f"""
The analyst (you) ran some code to answer the user's question.
User Question: {user_message}
Recent History: {history_block}
Code Execution Results:
{code_execution_result}

INSTRUCTIONS:
- Interpret these results for the user.
- Provide a professional, verbal summary of the findings.
- Use formatting (tables/bold) to highlight key numbers.
- If the result contains an error, explain it simply to the user.
"""
    client = genai.Client(api_key=gemini_api_key)
    
    for model_name in GEMINI_MODELS:
        try:
            t_llm = time.time()
            response = client.models.generate_content(
                model=model_name,
                config={"system_instruction": ANALYST_SYSTEM_PROMPT},
                contents=prompt
            )
            print(f"--- [INF] LLM Interpretation Generated ({model_name}) in {time.time() - t_llm:.2f}s ---")
            return response.text.strip()
        except Exception as e:
            if model_name == GEMINI_MODELS[-1]:
                return f"I couldn't interpret the data results: {str(e)}\nRaw result:\n{code_execution_result}"
    
    return "Error interpreting results."

def generate_session_title(file_name: str, file_type: str, gemini_api_key: str) -> str:
    """Generate session title using the new SDK."""
    client = genai.Client(api_key=gemini_api_key)
    prompt = (
        f"Generate a short, descriptive session title (max 8 words) for an uploaded "
        f"{file_type.upper()} file named '{file_name}'. "
        f"Return ONLY the title, no quotes, no punctuation at end."
    )
    
    for model_name in GEMINI_MODELS:
        try:
            response = client.models.generate_content(model=model_name, contents=prompt)
            return response.text.strip()[:100]
        except Exception:
            if model_name == GEMINI_MODELS[-1]:
                 return file_name.rsplit(".", 1)[0][:100]
    return file_name.rsplit(".", 1)[0][:100]