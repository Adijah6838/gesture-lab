"""Database operations for datasets, versions, and upload history."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.db import get_connection


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_dataset_upload(
    dataset_name: str, 
    filename: str, 
    ingest_result: dict[str, Any]
) -> dict[str, Any]:
    """Save a parsed upload to the database, creating dataset or new version.
    
    Returns the created UploadResponse payload.
    """
    now = utc_now()
    
    with get_connection() as conn:
        # 1. Find or create the dataset
        row = conn.execute("SELECT id FROM datasets WHERE name = ?", (dataset_name,)).fetchone()
        if row:
            dataset_id = row["id"]
            conn.execute("UPDATE datasets SET updated_at = ? WHERE id = ?", (now, dataset_id))
        else:
            cursor = conn.execute(
                "INSERT INTO datasets (name, created_at, updated_at) VALUES (?, ?, ?)",
                (dataset_name, now, now)
            )
            dataset_id = cursor.lastrowid

        # 2. Determine next version number
        row = conn.execute(
            "SELECT COALESCE(MAX(version_number), 0) + 1 AS next_ver FROM dataset_versions WHERE dataset_id = ?", 
            (dataset_id,)
        ).fetchone()
        version_number = row["next_ver"]

        # 3. Insert the new version
        cursor = conn.execute(
            """
            INSERT INTO dataset_versions (
                dataset_id, version_number, uploaded_at, original_filename,
                file_size_bytes, checksum_sha256, row_count, valid_row_count,
                malformed_row_count, columns_json, records_json, malformed_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                dataset_id,
                version_number,
                now,
                ingest_result["original_filename"],
                ingest_result["file_size_bytes"],
                ingest_result["checksum_sha256"],
                ingest_result["row_count"],
                ingest_result["valid_row_count"],
                ingest_result["malformed_row_count"],
                json.dumps(ingest_result["columns"]),
                json.dumps(ingest_result["records"]),
                json.dumps(ingest_result["malformed_records"]),
            )
        )
        version_id = cursor.lastrowid

        # 4. Log to upload_history
        conn.execute(
            """
            INSERT INTO upload_history (
                dataset_id, dataset_version_id, uploaded_at, status, 
                message, filename, file_size_bytes
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                dataset_id,
                version_id,
                now,
                "success",
                f"Ingested {ingest_result['valid_row_count']} valid rows.",
                filename,
                ingest_result["file_size_bytes"],
            )
        )

        # 5. Return the result payload
        return {
            "dataset_id": dataset_id,
            "dataset_name": dataset_name,
            "version_id": version_id,
            "version_number": version_number,
            "original_filename": ingest_result["original_filename"],
            "file_size_bytes": ingest_result["file_size_bytes"],
            "checksum_sha256": ingest_result["checksum_sha256"],
            "row_count": ingest_result["row_count"],
            "valid_row_count": ingest_result["valid_row_count"],
            "malformed_row_count": ingest_result["malformed_row_count"],
            "columns": ingest_result["columns"],
            "warnings": []
        }