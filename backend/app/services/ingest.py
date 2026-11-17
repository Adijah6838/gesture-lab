"""CSV ingestion and validation engine for Gesture Lab."""
from __future__ import annotations

import csv
import hashlib
import io
from typing import Any

import pandas as pd


def calculate_sha256(content: bytes) -> str:
    """Generate a unique fingerprint for the uploaded file."""
    return hashlib.sha256(content).hexdigest()


def sanitize_value(val: Any) -> Any:
    """Ensure values are JSON-safe (no NaN, no numpy types)."""
    if pd.isna(val):
        return None
    if isinstance(val, (int, float, str, bool)):
        return val
    return str(val)


def ingest_csv(content: bytes, filename: str) -> dict:
    """Parse, validate, and extract data from a raw CSV upload.
    
    Returns a dictionary containing valid records, malformed records, 
    column types, and file metadata.
    """
    checksum = calculate_sha256(content)

    # 1. Decode safely (handle UTF-8 BOM if present)
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("File is not valid UTF-8 text. Please save as CSV UTF-8.")

    reader = csv.reader(io.StringIO(text))
    
    # 2. Extract Headers
    try:
        headers = next(reader)
    except StopIteration:
        raise ValueError("File is completely empty.")
        
    headers = [h.strip() for h in headers]
    if not headers or all(not h for h in headers):
        raise ValueError("No valid column headers found.")

    valid_rows = []
    malformed_rows = []

    # 3. Separate Valid and Malformed Rows
    for row_idx, row in enumerate(reader):
        row_num = row_idx + 2  # +2 because CSV row 1 is the header
        
        # Skip completely empty rows silently BEFORE checking column counts
        if not row or all(not str(cell).strip() for cell in row):
            continue

        if len(row) != len(headers):
            malformed_rows.append({
                "row_number": row_num,
                "reason": f"Expected {len(headers)} columns, got {len(row)}",
                "raw_data": row
            })
        else:
            valid_rows.append(row)

    # 4. Create DataFrame from valid rows only
    df = pd.DataFrame(valid_rows, columns=headers)

    # 5. Type Inference (Numeric vs Categorical)
    column_types = {}
    for col in df.columns:
        # Try to convert column to numbers
        numeric_col = pd.to_numeric(df[col], errors='coerce')
        non_null_count = df[col].notna().sum()
        
        # If >80% of the values are numbers, treat the whole column as numeric
        if non_null_count > 0 and (numeric_col.notna().sum() / non_null_count) > 0.8:
            df[col] = numeric_col
            column_types[col] = "numeric"
        else:
            column_types[col] = "categorical"

    # 6. Convert to JSON-safe dictionaries
    records = []
    for row_dict in df.to_dict(orient="records"):
        records.append({k: sanitize_value(v) for k, v in row_dict.items()})

    return {
        "original_filename": filename,
        "checksum_sha256": checksum,
        "file_size_bytes": len(content),
        "row_count": len(records) + len(malformed_rows),
        "valid_row_count": len(records),
        "malformed_row_count": len(malformed_rows),
        "columns": headers,
        "column_types": column_types,
        "records": records,
        "malformed_records": malformed_rows
    }