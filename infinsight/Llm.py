"""
infinsight/services/llm.py
---------------------------
Gemini LLM integration for the Infinsight analyst.
Primary: gemini-2.5-flash
Fallback: gemini-2.5-flash-lite
Second Fallback: gemini-1.5-flash
"""

import logging
import time
import traceback

logger = logging.getLogger("infinsight.llm")

GEMINI_MODELS = [
    "models/gemini-2.5-flash",
    "models/gemini-2.5-flash-lite",
    "models/gemini-1.5-flash",
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

    # Format retrieved context
    context_block = ""
    for i, chunk in enumerate(context_chunks):
        score = chunk.get("score", "")
        text = chunk.get("text", "")
        context_block += f"\n--- Context Chunk {i+1} ---\n{text}\n"

    # Format recent history
    history_block = ""
    for turn in chat_history[-4:]:
        role = turn.get("role", "user")
        content = turn.get("content", "")
        if role == "user":
            history_block += f"\nUser: {content}"
        else:
            history_block += f"\nAssistant: {content}"

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
    """
    Generate an AI analyst response using Gemini.
    Can return either a direct answer or a code block for execution.
    """
    if chat_history is None:
        chat_history = []

    prompt = _build_prompt(user_message, context_chunks, chat_history, schema)
    import google.generativeai as genai

    for model in GEMINI_MODELS:
        try:
            genai.configure(api_key=gemini_api_key)
            gemini_model = genai.GenerativeModel(
                model_name=model,
                system_instruction=ANALYST_SYSTEM_PROMPT,
                generation_config={
                    "temperature": 0.1,
                    "top_p": 0.9,
                    "max_output_tokens": 4096,
                },
            )
            t_llm = time.time()
            response = gemini_model.generate_content(prompt)
            print(f"--- [INF] LLM Content Generated ({model}) in {time.time() - t_llm:.2f}s ---")
            text = response.text.strip()
            return text, model

        except Exception as e:
            print(f"--- [INF] Model {model} failed. Details: {str(e)} ---")
            logger.warning(f"Model {model} failed: {e}")
            if model == GEMINI_MODELS[-1]:
                 return "Something wrong please try again later", "error"

    return "Something wrong please try again later", "none"


def generate_final_interpretation(
    user_message: str,
    code_execution_result: str,
    gemini_api_key: str,
    chat_history: list[dict] = None,
) -> str:
    """Take the results of a pandas execution and turn them into a human-readable analyst report."""
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
    
    try:
        import google.generativeai as genai
        genai.configure(api_key=gemini_api_key)
        
        for model_name in GEMINI_MODELS:
            try:
                model = genai.GenerativeModel(model_name, system_instruction=ANALYST_SYSTEM_PROMPT)
                t_llm = time.time()
                response = model.generate_content(prompt)
                print(f"--- [INF] LLM Interpretation Generated ({model_name}) in {time.time() - t_llm:.2f}s ---")
                return response.text.strip()
            except Exception as e:
                print(f"--- [INF] Fallback: Interpretation model {model_name} failed. Details: {str(e)} ---")
                if model_name == GEMINI_MODELS[-1]:
                    raise e
                    
    except Exception as e:
        return f"Something wrong please try again later\nTechnical Details: {str(e)}\nRaw result:\n{code_execution_result}"


def generate_session_title(file_name: str, file_type: str, gemini_api_key: str) -> str:
    """Generate a short descriptive session title for the uploaded file."""
    try:
        import google.generativeai as genai
        genai.configure(api_key=gemini_api_key)
        
        for model_name in GEMINI_MODELS:
            try:
                model = genai.GenerativeModel(model_name)
                prompt = (
                    f"Generate a short, descriptive session title (max 8 words) for an uploaded "
                    f"{file_type.upper()} file named '{file_name}'. "
                    f"Return ONLY the title, no quotes, no punctuation at end."
                )
                response = model.generate_content(prompt)
                return response.text.strip()[:100]
            except Exception as e:
                print(f"--- [INF] Fallback: Title generation model {model_name} failed. Details: {str(e)} ---")
                if model_name == GEMINI_MODELS[-1]:
                     return file_name.rsplit(".", 1)[0][:100]
    except Exception:
        return file_name.rsplit(".", 1)[0][:100]

    return file_name.rsplit(".", 1)[0][:100]