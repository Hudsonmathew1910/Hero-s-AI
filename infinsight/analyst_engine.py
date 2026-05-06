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

def clean_analyst_code(code: str) -> str:
    """
    Remove import and from ... import ... statements from the code.
    This prevents 'NotImplementedError: ImportFrom not supported' in asteval.
    """
    lines = code.split('\n')
    cleaned_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('import ') or stripped.startswith('from '):
            continue
        cleaned_lines.append(line)
    return '\n'.join(cleaned_lines)

def execute_pandas_query(df: pd.DataFrame, code: str) -> dict:
    """
    Executes pandas code on the provided DataFrame safely using asteval.
    The code should expect 'df' to be available and should 
    assign the final result to a variable named 'result'.
    """
    if df is None:
        return {"success": False, "error": "DataFrame is None"}

    try:
        import sklearn
        from sklearn.linear_model import LinearRegression
        from asteval import Interpreter
    except ImportError as e:
        logger.error(f"Missing dependency for analysis: {e}")
        return {"success": False, "error": f"Missing dependency: {e}"}
    
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
        
        # Clean the code to remove imports that asteval doesn't support
        cleaned_code = clean_analyst_code(code)
        
        # Initialize the secure interpreter and update its symbol table
        aeval = Interpreter(use_numpy=True)
        aeval.symtable.update(local_vars)
        aeval(cleaned_code)
        
        sys.stdout = old_stdout
        
        if len(aeval.error) > 0:
            err_msg = str(aeval.error[0].get_error()[1])
            raise Exception(f"asteval error: {err_msg}")
        
        output = redirected_output.getvalue()
        result = aeval.symtable.get("result")
        
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
        if 'old_stdout' in locals():
            sys.stdout = old_stdout
        logger.error(f"Execution error: {e}\n{traceback.format_exc()}")
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }

