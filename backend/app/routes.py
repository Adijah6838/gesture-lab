"""API routes for uploading, exploring, and analyzing datasets."""
from __future__ import annotations

import io
import json
import math
from typing import Optional

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, UploadFile, Query
from fastapi.responses import StreamingResponse

from app.db import get_connection
from app.models import (
    DatasetSummary, DatasetMetadata, PreviewPage, DatasetStats,
    FilterOptions, CompareResult, UploadResponse, UploadHistoryEntry
)
from app.services.ingest import ingest_csv
from app.services.datasets import save_dataset_upload

router = APIRouter(prefix="/api/datasets")

def _row_to_summary(row) -> dict:
    return {
        "id": row["id"], "name": row["name"],
        "created_at": row["created_at"], "updated_at": row["updated_at"],
        "latest_version": row["latest_version"] or 0,
        "total_versions": row["total_versions"] or 0,
    }

def _row_to_version(row) -> dict:
    return {
        "id": row["id"], "dataset_id": row["dataset_id"],
        "version_number": row["version_number"], "uploaded_at": row["uploaded_at"],
        "original_filename": row["original_filename"], "file_size_bytes": row["file_size_bytes"],
        "checksum_sha256": row["checksum_sha256"], "row_count": row["row_count"],
        "valid_row_count": row["valid_row_count"], "malformed_row_count": row["malformed_row_count"],
    }

def _get_version(conn, dataset_id: int, version_id: Optional[int]):
    if version_id:
        return conn.execute("SELECT * FROM dataset_versions WHERE id = ? AND dataset_id = ?", (version_id, dataset_id)).fetchone()
    return conn.execute("SELECT * FROM dataset_versions WHERE dataset_id = ? ORDER BY version_number DESC LIMIT 1", (dataset_id,)).fetchone()

@router.post("/upload", response_model=UploadResponse)
async def upload_dataset(name: str = Form(...), file: UploadFile = File(...)):
    content = await file.read()
    try:
        ingest_result = ingest_csv(content, file.filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return save_dataset_upload(name, file.filename, ingest_result)

@router.get("", response_model=list[DatasetSummary])
def list_datasets():
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT d.*, 
                   (SELECT COUNT(*) FROM dataset_versions WHERE dataset_id = d.id) as total_versions,
                   (SELECT MAX(version_number) FROM dataset_versions WHERE dataset_id = d.id) as latest_version
            FROM datasets d ORDER BY d.updated_at DESC
        """).fetchall()
        return [_row_to_summary(r) for r in rows]

@router.get("/{dataset_id}", response_model=DatasetMetadata)
def get_metadata(dataset_id: int):
    with get_connection() as conn:
        d_row = conn.execute("SELECT * FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
        if not d_row: raise HTTPException(404, "Dataset not found")
        
        v_rows = conn.execute("SELECT * FROM dataset_versions WHERE dataset_id = ? ORDER BY version_number DESC", (dataset_id,)).fetchall()
        if not v_rows: raise HTTPException(404, "No versions found")
        
        latest = v_rows[0]
        columns = json.loads(latest["columns_json"])
        records = json.loads(latest["records_json"])
        
        col_types = {}
        for col in columns:
            vals = [r[col] for r in records[:100] if r[col] is not None]
            if vals and all(isinstance(v, (int, float)) for v in vals):
                col_types[col] = "numeric"
            else:
                col_types[col] = "categorical"
                
        cat_col = next((c for c in columns if c.lower() in ("gesture", "category", "label", "class")), None)
        if not cat_col: cat_col = next((c for c in columns if col_types[c] == "categorical"), None)
                
        categories = sorted(list(set(str(r[cat_col]) for r in records if r[cat_col] is not None))) if cat_col else []
            
        return {
            "dataset": _row_to_summary({**d_row, "latest_version": len(v_rows), "total_versions": len(v_rows)}),
            "current_version": _row_to_version(latest),
            "available_versions": [_row_to_version(r) for r in v_rows],
            "columns": columns, "column_types": col_types,
            "categories": categories, "category_column": cat_col
        }

@router.get("/{dataset_id}/preview", response_model=PreviewPage)
def preview_dataset(dataset_id: int, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), version_id: Optional[int] = None):
    with get_connection() as conn:
        v_row = _get_version(conn, dataset_id, version_id)
        if not v_row: raise HTTPException(404, "Version not found")
        
        records = json.loads(v_row["records_json"])
        total_rows = len(records)
        total_pages = math.ceil(total_rows / page_size) if total_rows > 0 else 1
        start = (page - 1) * page_size
        page_records = records[start : start + page_size]
        
        return {
            "page": page, "page_size": page_size, "total_rows": total_rows, "total_pages": total_pages,
            "rows": [{"index": start + i, "values": r} for i, r in enumerate(page_records)]
        }

@router.get("/{dataset_id}/stats", response_model=DatasetStats)
def get_stats(dataset_id: int, version_id: Optional[int] = None):
    with get_connection() as conn:
        v_row = _get_version(conn, dataset_id, version_id)
        if not v_row: raise HTTPException(404, "Version not found")
        
        records = json.loads(v_row["records_json"])
        if not records:
            return {"row_count": 0, "valid_row_count": 0, "malformed_row_count": v_row["malformed_row_count"], "numeric_columns": [], "category_distribution": [], "category_column": None}
            
        df = pd.DataFrame(records)
        numeric_cols = []
        for col in df.columns:
            if pd.api.types.is_numeric_dtype(df[col]):
                s = df[col].dropna()
                if not s.empty:
                    numeric_cols.append({
                        "column": col, "count": int(s.count()), "mean": float(s.mean()), "median": float(s.median()),
                        "std": float(s.std()) if s.count() > 1 else 0.0, "min": float(s.min()), "max": float(s.max()),
                        "q1": float(s.quantile(0.25)), "q3": float(s.quantile(0.75))
                    })
                    
        cat_col = next((c for c in df.columns if c.lower() in ("gesture", "category", "label", "class")), None)
        if not cat_col: cat_col = next((c for c in df.columns if c not in [n["column"] for n in numeric_cols]), None)
        cat_dist = [{"category": str(k), "count": int(v)} for k, v in df[cat_col].value_counts().items()] if cat_col else []
                
        return {
            "row_count": v_row["row_count"], "valid_row_count": v_row["valid_row_count"], "malformed_row_count": v_row["malformed_row_count"],
            "numeric_columns": numeric_cols, "category_distribution": cat_dist, "category_column": cat_col
        }

@router.get("/{dataset_id}/export")
def export_dataset(dataset_id: int, category: Optional[str] = None, version_id: Optional[int] = None):
    with get_connection() as conn:
        v_row = _get_version(conn, dataset_id, version_id)
        if not v_row: raise HTTPException(404, "Version not found")
        
        df = pd.DataFrame(json.loads(v_row["records_json"]))
        if category and not df.empty:
            cat_col = next((c for c in df.columns if c.lower() in ("gesture", "category", "label", "class")), None)
            if cat_col: df = df[df[cat_col].astype(str) == category]
                
        stream = io.StringIO()
        df.to_csv(stream, index=False)
        response = StreamingResponse(iter([stream.getvalue()]), media_type="text/csv")
        response.headers["Content-Disposition"] = f"attachment; filename=dataset_{dataset_id}_export.csv"
        return response

@router.get("/{dataset_id}/history", response_model=list[UploadHistoryEntry])
def get_history(dataset_id: int):
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM upload_history WHERE dataset_id = ? ORDER BY uploaded_at DESC", (dataset_id,)).fetchall()
        return [
            {"id": r["id"], "dataset_id": r["dataset_id"], "dataset_version_id": r["dataset_version_id"],
             "uploaded_at": r["uploaded_at"], "status": r["status"], "message": r["message"],
             "filename": r["filename"], "file_size_bytes": r["file_size_bytes"]}
            for r in rows
        ]

@router.get("/compare/{version_a_id}/{version_b_id}", response_model=CompareResult)
def compare_versions(version_a_id: int, version_b_id: int):
    with get_connection() as conn:
        v_a = conn.execute("SELECT * FROM dataset_versions WHERE id = ?", (version_a_id,)).fetchone()
        v_b = conn.execute("SELECT * FROM dataset_versions WHERE id = ?", (version_b_id,)).fetchone()
        if not v_a or not v_b: raise HTTPException(404, "One or both versions not found")
        
        rec_a, rec_b = json.loads(v_a["records_json"]), json.loads(v_b["records_json"])
        cols_a = set(v_a["columns_json"]) if isinstance(v_a["columns_json"], list) else set(json.loads(v_a["columns_json"]))
        cols_b = set(v_b["columns_json"]) if isinstance(v_b["columns_json"], list) else set(json.loads(v_b["columns_json"]))
        common_cols = list(cols_a & cols_b)
        
        cat_col = next((c for c in common_cols if c.lower() in ("gesture", "category", "label", "class")), None)
        dist_a, dist_b, delta = [], [], []
        if cat_col and rec_a and rec_b:
            vc_a = pd.DataFrame(rec_a)[cat_col].value_counts().to_dict()
            vc_b = pd.DataFrame(rec_b)[cat_col].value_counts().to_dict()
            for cat in sorted(set(vc_a.keys()) | set(vc_b.keys())):
                ca, cb = int(vc_a.get(cat, 0)), int(vc_b.get(cat, 0))
                dist_a.append({"category": str(cat), "count": ca})
                dist_b.append({"category": str(cat), "count": cb})
                delta.append({"category": str(cat), "count_a": ca, "count_b": cb, "delta": cb - ca})
                
        return {
            "version_a": _row_to_version(v_a), "version_b": _row_to_version(v_b),
            "row_count_delta": v_b["row_count"] - v_a["row_count"], "malformed_delta": v_b["malformed_row_count"] - v_a["malformed_row_count"],
            "common_columns": common_cols, "columns_only_in_a": list(cols_a - cols_b), "columns_only_in_b": list(cols_b - cols_a),
            "category_distribution_a": dist_a, "category_distribution_b": dist_b, "category_delta": delta
        }