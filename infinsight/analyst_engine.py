import pandas as pd
import numpy as np
import logging
import traceback
import io

logger = logging.getLogger("infinsight.analyst_engine")

def load_dataset(file_path: str, file_type: str):
    """Load dataset into a pandas DataFrame with existence check."""
    import os
    if not os.path.exists(file_path):
        logger.error(f"Dataset file not found: {file_path}. This usually happens if the session was created in a previous deployment (Render ephemeral storage).")
        return None
        
    try:
        if file_type == "csv":
            return pd.read_csv(file_path)
        elif file_type == "excel":
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
    Executes pandas code on the provided DataFrame safely using asteval.
    The code should expect 'df' to be available and should 
    assign the final result to a variable named 'result'.
    """
    if df is None:
        return {"success": False, "error": "DataFrame is None"}

    import sklearn
    from sklearn.linear_model import LinearRegression
    from asteval import Interpreter
    
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
        
        # Initialize the secure interpreter
        aeval = Interpreter(symtable=local_vars, use_numpy=True)
        aeval(code)
        
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
        sys.stdout = old_stdout
        logger.error(f"Execution error: {e}\n{traceback.format_exc()}")
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }
