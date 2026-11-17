# Gesture Lab — Gesture Data Explorer

A full-stack platform for uploading, validating, analyzing, and exporting pre-recorded gesture datasets.

## Tech Stack
- **Frontend:** React, TypeScript, Vite, Recharts
- **Backend:** Python, FastAPI, Pandas, SQLite, SQLAlchemy
- **Testing:** Pytest

## Features
- **Upload & Validation:** Upload CSV datasets. Validates required columns (`timestamp`, `gesture`, `confidence`, `duration_ms`, `hand`). Malformed rows are safely isolated without failing the upload.
- **Version Tracking:** Automatically tracks versions of uploads (e.g., `file.csv` v1, v2) and keeps a full upload history.
- **Metadata & Preview:** Paginated preview of valid rows with the ability to filter by gesture category.
- **Statistical Summaries & Charts:** Backend uses Pandas to group data by gesture to calculate counts, average confidence, and average duration. Frontend renders distribution charts using Recharts.
- **Comparison:** Compare two dataset versions to see differences in gesture counts and confidence scores.
- **Export:** Export filtered datasets back to CSV. Original uploads are never overwritten or lost.
- **Accessibility:** Simple semantic HTML layout with keyboard-navigable inputs and clear focus states.

## Project Structure