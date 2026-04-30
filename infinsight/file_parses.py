"""
infinsight/services/file_parser.py
-----------------------------------
Parses uploaded files (CSV, Excel, PDF) into clean text chunks.
Returns a list of dicts: [{"text": "...", "metadata": {...}}, ...]
"""

import io
import logging
import traceback
from pathlib import Path

logger = logging.getLogger("infinsight.parser")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _chunk_text(text: str, chunk_size: int = 800, overlap: int = 100) -> list[str]:
    """Split a long string into overlapping chunks."""
    words = text.split()
    chunks = []
    i = 0
    while i < len(words):
        chunk = " ".join(words[i : i + chunk_size])
        chunks.append(chunk)
        i += chunk_size - overlap
    return [c for c in chunks if c.strip()]


def _extract_structured_insights(df, source_label: str, sheet_name: str = "") -> list[dict]:
    import json
    import numpy as np
    import pandas as pd
    chunks = []
    
    meta_base = {"source": source_label}
    if sheet_name:
        meta_base["sheet"] = sheet_name

    # --- 1. Column Entity Detection Heuristics ---
    lower_cols = {c.lower(): c for c in df.columns}
    
    date_col = next((c for l, c in lower_cols.items() if 'date' in l or 'time' in l or l == 'period'), None)
    cust_col = next((c for l, c in lower_cols.items() if 'customer' in l or 'client' in l or 'user' in l), None)
    prod_col = next((c for l, c in lower_cols.items() if 'product' in l or 'item' in l or 'category' in l), None)
    
    sales_col = next((c for l, c in lower_cols.items() if 'sales' in l or 'revenue' in l or 'amount' in l), None)
    profit_col = next((c for l, c in lower_cols.items() if 'profit' in l or 'margin' in l), None)
    disc_col = next((c for l, c in lower_cols.items() if 'discount' in l), None)
    qty_col = next((c for l, c in lower_cols.items() if 'quantity' in l or 'qty' in l), None)
    
    numeric_cols = df.select_dtypes(include=['number']).columns.tolist()

    # Generic Totals
    if numeric_cols:
        global_totals = {}
        for col in numeric_cols:
            global_totals[f"total_{col}"] = float(df[col].sum(skipna=True))
            global_totals[f"avg_{col}"] = float(df[col].mean(skipna=True))
        chunks.append({
            "text": f"Global Aggregate Metrics:\n{json.dumps(global_totals, indent=2)}",
            "metadata": {"type": "global_insights", **meta_base}
        })

    # --- 2. Advanced Product Analytics ---
    if prod_col and sales_col:
        try:
            prod_metrics = df.groupby(prod_col).agg({
                sales_col: 'sum',
                **( {profit_col: 'sum'} if profit_col else {} ),
                **( {qty_col: 'sum'} if qty_col else {} )
            }).sort_values(by=sales_col, ascending=False).head(20) # Top 20 products
            
            chunks.append({
                "text": f"Top 20 Product Analytics (Sales, Profit, Quantity):\n{json.dumps(prod_metrics.to_dict(orient='index'), indent=2)}",
                "metadata": {"type": "products_analytics", "entity": "product", **meta_base}
            })
        except Exception as e:
            logger.warning(f"Product Analytics failed: {e}")

    # --- 3. Customer RFM Analytics ---
    if cust_col and sales_col and date_col:
        try:
            # Convert date to datetime if not
            if not pd.api.types.is_datetime64_any_dtype(df[date_col]):
                df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
            
            max_date = df[date_col].max()
            rfm = df.groupby(cust_col).agg({
                date_col: lambda x: (max_date - x.max()).days if pd.notnull(x.max()) else 0, # Recency
                cust_col: 'count', # Frequency
                sales_col: 'sum'   # Monetary
            }).rename(columns={date_col: 'Recency_Days', cust_col: 'Frequency_Orders', sales_col: 'Monetary_Total_Sales'})
            
            rfm = rfm.sort_values(by='Monetary_Total_Sales', ascending=False).head(20)
            chunks.append({
                "text": f"Top 20 Customers RFM Analytics (Recency, Frequency, Monetary):\n{json.dumps(rfm.to_dict(orient='index'), indent=2)}",
                "metadata": {"type": "customer_analytics", "entity": "customer", **meta_base}
            })
        except Exception as e:
            logger.warning(f"RFM Analytics failed: {e}")

    # --- 4. Time-Series & ML Forecasting ---
    if date_col and sales_col:
        try:
            if not pd.api.types.is_datetime64_any_dtype(df[date_col]):
                df[date_col] = pd.to_datetime(df[date_col], errors='coerce')

            # Group by Month
            ts_df = df.dropna(subset=[date_col]).set_index(date_col)
            monthly = ts_df.resample('ME').agg({
                sales_col: 'sum',
                **( {profit_col: 'sum'} if profit_col else {} )
            }).fillna(0)
            
            # Format index to string YYYY-MM
            monthly.index = monthly.index.strftime('%Y-%m')
            
            ts_dict = monthly.to_dict(orient='index')
            chunks.append({
                "text": f"Time-Series Monthly Trends:\n{json.dumps(ts_dict, indent=2)}",
                "metadata": {"type": "time_series", "entity": "time", **meta_base}
            })

            # ML Layer: Numpy Polyfit for Linear Regression Forecasting
            if len(monthly) > 3:
                x = np.arange(len(monthly))
                y = monthly[sales_col].values
                # Linear trend line y = mx + b
                m, b = np.polyfit(x, y, 1)
                
                # Predict next 3 periods
                next_x = np.arange(len(monthly), len(monthly) + 3)
                predictions = (m * next_x + b).tolist()
                
                forecast = {
                    "historical_trend": "Increasing" if m > 0 else "Decreasing",
                    "average_monthly_growth": round(m, 2),
                    "next_3_months_forecast_sales": [round(p, 2) for p in predictions]
                }
                
                chunks.append({
                    "text": f"Machine Learning Forecasts (Linear Regression on Monthly Sales):\n{json.dumps(forecast, indent=2)}",
                    "metadata": {"type": "ml_forecasts", "entity": "forecast", **meta_base}
                })

        except Exception as e:
            logger.warning(f"Time-Series/ML failed: {e}")

    # --- 5. Profit vs Discount ML Trend Correlation ---
    if profit_col and disc_col:
        try:
            # Drop NaNs
            valid_df = df[[profit_col, disc_col]].dropna()
            if len(valid_df) > 10:
                corr = valid_df[profit_col].corr(valid_df[disc_col])
                elasticity = {
                    "correlation_coefficient": round(corr, 3),
                    "interpretation": "Negative correlation implies higher discounts reduce actual profit." if corr < -0.3 else "Weak or positive correlation."
                }
                chunks.append({
                    "text": f"Profit vs Discount Elasticity Analysis:\n{json.dumps(elasticity, indent=2)}",
                    "metadata": {"type": "ml_elasticity", "entity": "correlation", **meta_base}
                })
        except Exception as e:
            logger.warning(f"Elasticity Analysis failed: {e}")

    # Aggregated Analytics for Metadata storage
    analytics_package = {
        "products": prod_metrics.to_dict(orient='index') if 'prod_metrics' in locals() else {},
        "customers": rfm.to_dict(orient='index') if 'rfm' in locals() else {},
        "time_series": ts_dict if 'ts_dict' in locals() else {},
        "forecast": forecast if 'forecast' in locals() else {},
        "elasticity": elasticity if 'elasticity' in locals() else {}
    }

    return chunks, analytics_package


# ─────────────────────────────────────────────────────────────────────────────
# CSV Parser
# ─────────────────────────────────────────────────────────────────────────────

def parse_csv(file_obj) -> tuple[list[dict], dict]:
    """
    Parse a CSV file.
    Returns: (chunks_list, metadata_dict)
    """
    try:
        import pandas as pd

        df = pd.read_csv(file_obj)
        metadata = {
            "rows": len(df),
            "columns": list(df.columns),
            "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
            "null_counts": df.isnull().sum().to_dict(),
        }

        chunks = []

        # Chunk 1: schema overview
        schema_text = (
            f"Dataset Overview: {len(df)} rows, {len(df.columns)} columns.\n"
            f"Columns: {', '.join(df.columns)}.\n"
            f"Data types: {', '.join(f'{c}: {t}' for c, t in df.dtypes.items())}.\n"
        )
        chunks.append({"text": schema_text, "metadata": {"type": "schema", "source": "csv"}})

        # Chunk 2: statistical summary
        try:
            stats = df.describe(include="all").to_string()
            chunks.append({"text": f"Statistical Summary:\n{stats}", "metadata": {"type": "stats", "source": "csv"}})
        except Exception:
            pass

        # Chunk 3: sample rows (first 20, stringified)
        sample = df.head(20).to_string(index=False)
        chunks.append({"text": f"Sample rows (first 20):\n{sample}", "metadata": {"type": "sample", "source": "csv"}})

        # Chunk each column's unique values (for categorical)
        for col in df.columns:
            if df[col].dtype == object or df[col].nunique() < 50:
                vals = df[col].dropna().unique()[:30]
                col_text = f"Column '{col}' values: {', '.join(str(v) for v in vals)}"
                chunks.append({"text": col_text, "metadata": {"type": "column_values", "column": col, "source": "csv"}})

        # Extract deep JSON insights (Sums, Averages, GroupBys)
        ins_chunks, analytics = _extract_structured_insights(df, "csv")
        chunks.extend(ins_chunks)
        metadata["analytics"] = analytics

        return chunks, metadata

    except Exception as e:
        logger.error("CSV parse error: %s\n%s", e, traceback.format_exc())
        raise ValueError(f"Failed to parse CSV: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Excel Parser
# ─────────────────────────────────────────────────────────────────────────────

def parse_excel(file_obj) -> tuple[list[dict], dict]:
    """Parse an Excel file (all sheets)."""
    try:
        import pandas as pd

        xl = pd.ExcelFile(file_obj)
        sheet_names = xl.sheet_names
        metadata = {"sheets": sheet_names, "total_sheets": len(sheet_names)}

        chunks = []
        chunks.append({
            "text": f"Excel workbook with {len(sheet_names)} sheet(s): {', '.join(sheet_names)}.",
            "metadata": {"type": "overview", "source": "excel"},
        })

        for sheet in sheet_names:
            df = xl.parse(sheet)
            metadata[f"sheet_{sheet}_rows"] = len(df)
            metadata[f"sheet_{sheet}_cols"] = list(df.columns)

            header_text = (
                f"Sheet '{sheet}': {len(df)} rows, {len(df.columns)} columns. "
                f"Columns: {', '.join(str(c) for c in df.columns)}."
            )
            chunks.append({"text": header_text, "metadata": {"type": "sheet_schema", "sheet": sheet, "source": "excel"}})

            try:
                stats = df.describe(include="all").to_string()
                chunks.append({
                    "text": f"Sheet '{sheet}' statistics:\n{stats}",
                    "metadata": {"type": "stats", "sheet": sheet, "source": "excel"},
                })
            except Exception:
                pass

            sample = df.head(20).to_string(index=False)
            chunks.append({
                "text": f"Sheet '{sheet}' sample rows:\n{sample}",
                "metadata": {"type": "sample", "sheet": sheet, "source": "excel"},
            })

            # Extract deep JSON insights (Sums, Averages, GroupBys) for the sheet
            ins_chunks, analytics = _extract_structured_insights(df, "excel", sheet_name=sheet)
            chunks.extend(ins_chunks)
            if "analytics" not in metadata:
                metadata["analytics"] = {}
            metadata["analytics"][sheet] = analytics

        return chunks, metadata

    except Exception as e:
        logger.error("Excel parse error: %s\n%s", e, traceback.format_exc())
        raise ValueError(f"Failed to parse Excel: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# PDF Parser
# ─────────────────────────────────────────────────────────────────────────────

def parse_pdf(file_obj) -> tuple[list[dict], dict]:
    """Parse a PDF file page-by-page."""
    try:
        import pypdf

        reader = pypdf.PdfReader(file_obj)
        num_pages = len(reader.pages)
        metadata = {"pages": num_pages}

        all_text = []
        chunks = []

        for i, page in enumerate(reader.pages):
            page_text = page.extract_text() or ""
            page_text = page_text.strip()
            if not page_text:
                continue
            all_text.append(page_text)
            # Each page becomes one or more chunks
            for chunk in _chunk_text(page_text, chunk_size=600, overlap=80):
                chunks.append({
                    "text": chunk,
                    "metadata": {"type": "page_content", "page": i + 1, "source": "pdf"},
                })

        metadata["extracted_pages"] = len(all_text)

        # Also add a full-doc summary chunk (first 1000 words)
        full_text_preview = " ".join(all_text)[:4000]
        chunks.insert(0, {
            "text": f"Document overview (first portion):\n{full_text_preview}",
            "metadata": {"type": "overview", "source": "pdf"},
        })

        return chunks, metadata

    except Exception as e:
        logger.error("PDF parse error: %s\n%s", e, traceback.format_exc())
        raise ValueError(f"Failed to parse PDF: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Main dispatcher
# ─────────────────────────────────────────────────────────────────────────────

def parse_file(file_obj, file_type: str) -> tuple[list[dict], dict]:
    """
    Dispatcher: routes to the correct parser based on file_type.
    Returns: (chunks_list, metadata_dict)
    Each chunk: {"text": str, "metadata": dict}
    """
    parsers = {
        "csv": parse_csv,
        "excel": parse_excel,
        "pdf": parse_pdf,
    }
    parser = parsers.get(file_type.lower())
    if not parser:
        raise ValueError(f"Unsupported file type: {file_type}")
    return parser(file_obj)