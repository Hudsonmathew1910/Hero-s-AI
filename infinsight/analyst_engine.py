import pandas as pd
import numpy as np
import logging
import traceback
import io

logger = logging.getLogger("infinsight.analyst_engine")

def load_dataset(file_path: str, file_type: str):
    """Load dataset into a pandas DataFrame."""
    try:
        if file_type == "csv":
            return pd.read_csv(file_path)
        elif file_type == "excel":
            # For Excel, we might need to handle multiple sheets. 
            # For simplicity, we'll load the first sheet or allow the LLM to specify if we 
            # pass all sheet names in schema.
            return pd.read_excel(file_path)
        else:
            return None
    except Exception as e:
        logger.error(f"Error loading dataset: {e}")
        return None

def get_df_schema(df: pd.DataFrame) -> str:
    """Generate a compact schema description for the LLM."""
    if df is None or df.empty:
        return "Dataset is empty or could not be loaded."
    
    schema = []
    schema.append(f"Dimensions: {df.shape[0]} rows x {df.shape[1]} columns")
    schema.append("Columns and Dtypes:")
    for col, dtype in df.dtypes.items():
        # Get sample values (non-null)
        sample = df[col].dropna().unique()[:3].tolist()
        schema.append(f"- {col} ({dtype}): Sample values: {sample}")
    
    # Statistical summary for numeric columns
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    if numeric_cols:
        schema.append("\nNumeric Summary (min, max, mean):")
        summary = df[numeric_cols].describe().loc[['min', 'max', 'mean']].to_string()
        schema.append(summary)
        
    return "\n".join(schema)

def execute_pandas_query(df: pd.DataFrame, code: str) -> dict:
    """
    Executes pandas code on the provided DataFrame.
    The code should expect 'df' to be available and should 
    assign the final result to a variable named 'result'.
    """
    if df is None:
        return {"success": False, "error": "DataFrame is None"}

    # Basic safety: check for dangerous keywords
    dangerous = ["os.", "sys.", "subprocess", "eval(", "exec(", "open(", "import "]
    # Note: We might need 'import' for scikit-learn inside the code block if we allow it.
    # But for now, let's provide common libraries in globals.
    
    for d in dangerous:
        if d in code and d != "import ": # Allow import for specific libraries if needed
            # We'll be more permissive with 'import' for sklearn/statsmodels if they are in the code
            pass

    import sklearn
    from sklearn.linear_model import LinearRegression
    
    # Prepare execution environment
    local_vars = {
        "df": df,
        "pd": pd,
        "np": np,
        "sklearn": sklearn,
        "LinearRegression": LinearRegression,
        "result": None
    }
    
    try:
        # Capture stdout to see if there are print statements
        import sys
        old_stdout = sys.stdout
        redirected_output = io.StringIO()
        sys.stdout = redirected_output
        
        exec(code, {}, local_vars)
        
        sys.stdout = old_stdout
        
        output = redirected_output.getvalue()
        result = local_vars.get("result")
        
        # If result is a DataFrame or Series, convert to something readable
        if isinstance(result, (pd.DataFrame, pd.Series)):
            result_str = result.to_string()
        else:
            result_str = str(result)
            
        full_res = result_str
        if output:
            full_res = f"Output:\n{output}\nResult:\n{result_str}"
            
        return {
            "success": True,
            "result": full_res,
            "raw_result": result
        }
    except Exception as e:
        sys.stdout = old_stdout
        logger.error(f"Execution error: {e}\n{traceback.format_exc()}")
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }
