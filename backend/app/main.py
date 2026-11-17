import io
import pandas as pd
from fastapi import FastAPI, UploadFile, File, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from .db import engine, get_db, Base
from .models import Dataset, GestureRecord

# Create tables on startup
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Gesture Lab API")

# Allow frontend to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174", "http://localhost:5175"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

REQUIRED_COLUMNS = ["timestamp", "gesture", "confidence", "duration_ms", "hand"]

@app.post("/api/upload")
async def upload_dataset(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="Only CSV files are allowed")
    
    contents = await file.read()
    
    # Get previous version count
    prev_count = db.query(Dataset).filter(Dataset.filename == file.filename).count()
    version = prev_count + 1
    
    dataset = Dataset(filename=file.filename, version=version)
    db.add(dataset)
    db.commit()
    db.refresh(dataset)
    
    try:
        # Read CSV with Pandas, skipping lines with too many commas
        df = pd.read_csv(io.BytesIO(contents), on_bad_lines='skip')
    except Exception as e:
        dataset.malformed_rows = -1 
        db.commit()
        raise HTTPException(status_code=400, detail=f"Failed to parse CSV: {str(e)}")

    # Count total rows manually to catch skipped malformed lines
    raw_text = contents.decode('utf-8')
    total_rows = max(0, len(raw_text.strip().split('\n')) - 1) # -1 for header
    valid_rows = 0
    malformed_rows = 0

    # Check missing columns
    missing_cols = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing_cols:
        dataset.total_rows = total_rows
        dataset.valid_rows = 0
        dataset.malformed_rows = total_rows
        db.commit()
        raise HTTPException(status_code=400, detail=f"Missing columns: {missing_cols}")

    # Iterate and validate rows that Pandas successfully read
    for _, row in df.iterrows():
        try:
            if pd.isna(row['timestamp']) or pd.isna(row['gesture']) or pd.isna(row['confidence']) or pd.isna(row['duration_ms']) or pd.isna(row['hand']):
                raise ValueError("Missing required field")

            ts = float(row['timestamp'])
            gesture = str(row['gesture'])
            conf = float(row['confidence'])
            dur = int(row['duration_ms'])
            hand = str(row['hand'])
            
            if not (0 <= conf <= 1):
                raise ValueError("Confidence out of bounds")

            record = GestureRecord(
                dataset_id=dataset.id,
                timestamp=ts, gesture=gesture, confidence=conf, duration_ms=dur, hand=hand,
                is_malformed=0
            )
            db.add(record)
            valid_rows += 1
        except Exception:
            malformed_rows += 1
            bad_record = GestureRecord(
                dataset_id=dataset.id,
                is_malformed=1,
                raw_data={k: str(v) for k, v in row.to_dict().items()}
            )
            db.add(bad_record)

    # Any rows that Pandas skipped due to bad formatting are also malformed
    malformed_rows += (total_rows - len(df))

    dataset.total_rows = total_rows
    dataset.valid_rows = valid_rows
    dataset.malformed_rows = malformed_rows
    db.commit()

    return {"message": "Upload successful", "dataset_id": dataset.id, "version": version}

@app.get("/api/datasets")
def list_datasets(db: Session = Depends(get_db)):
    return db.query(Dataset).order_by(Dataset.uploaded_at.desc()).all()

@app.get("/api/datasets/{dataset_id}/preview")
def preview_dataset(dataset_id: str, page: int = 1, size: int = 10, gesture: str = None, db: Session = Depends(get_db)):
    query = db.query(GestureRecord).filter(
        GestureRecord.dataset_id == dataset_id,
        GestureRecord.is_malformed == 0
    )
    if gesture:
        query = query.filter(GestureRecord.gesture == gesture)
    
    total = query.count()
    records = query.offset((page - 1) * size).limit(size).all()
    
    # Get unique gestures for filtering
    gestures = [r[0] for r in db.query(GestureRecord.gesture).filter(
        GestureRecord.dataset_id == dataset_id, 
        GestureRecord.is_malformed == 0
    ).distinct().all()]

    return {
        "total": total,
        "page": page,
        "size": size,
        "gestures": gestures,
        "records": [
            {"timestamp": r.timestamp, "gesture": r.gesture, "confidence": r.confidence, "duration_ms": r.duration_ms, "hand": r.hand} 
            for r in records
        ]
    }

@app.get("/api/datasets/{dataset_id}/stats")
def dataset_stats(dataset_id: str, db: Session = Depends(get_db)):
    records = db.query(GestureRecord).filter(
        GestureRecord.dataset_id == dataset_id,
        GestureRecord.is_malformed == 0
    ).all()
    
    if not records:
        return {"summary": [], "chart_data": []}

    data = [{"gesture": r.gesture, "confidence": r.confidence, "duration_ms": r.duration_ms} for r in records]
    df = pd.DataFrame(data)
    
    summary = df.groupby("gesture").agg(
        count=("gesture", "size"),
        avg_confidence=("confidence", "mean"),
        avg_duration=("duration_ms", "mean")
    ).reset_index().to_dict(orient="records")
    
    chart_data = df["gesture"].value_counts().reset_index()
    chart_data.columns = ["name", "value"]
    
    return {
        "summary": summary,
        "chart_data": chart_data.to_dict(orient="records")
    }

@app.get("/api/datasets/{dataset_id}/export")
def export_dataset(dataset_id: str, gesture: str = None, db: Session = Depends(get_db)):
    query = db.query(GestureRecord).filter(
        GestureRecord.dataset_id == dataset_id,
        GestureRecord.is_malformed == 0
    )
    if gesture:
        query = query.filter(GestureRecord.gesture == gesture)
    
    records = query.all()
    data = [{"timestamp": r.timestamp, "gesture": r.gesture, "confidence": r.confidence, "duration_ms": r.duration_ms, "hand": r.hand} for r in records]
    
    if not data:
        raise HTTPException(status_code=404, detail="No data found")
        
    df = pd.DataFrame(data)
    stream = io.StringIO()
    df.to_csv(stream, index=False)
    
    response = StreamingResponse(iter([stream.getvalue()]), media_type="text/csv")
    response.headers["Content-Disposition"] = f"attachment; filename=export_{dataset_id}.csv"
    return response

@app.get("/api/compare")
def compare_datasets(base_id: str, compare_id: str, db: Session = Depends(get_db)):
    def get_df(ds_id):
        records = db.query(GestureRecord).filter(
            GestureRecord.dataset_id == ds_id,
            GestureRecord.is_malformed == 0
        ).all()
        return pd.DataFrame([{"gesture": r.gesture, "confidence": r.confidence, "duration_ms": r.duration_ms} for r in records])

    df1 = get_df(base_id)
    df2 = get_df(compare_id)

    if df1.empty or df2.empty:
        raise HTTPException(status_code=400, detail="One or both datasets are empty.")

    stats1 = df1.groupby("gesture").agg(count=("gesture", "size"), avg_conf=("confidence", "mean")).reset_index()
    stats2 = df2.groupby("gesture").agg(count=("gesture", "size"), avg_conf=("confidence", "mean")).reset_index()

    merged = pd.merge(stats1, stats2, on="gesture", how="outer", suffixes=("_base", "_compare")).fillna(0)
    
    merged["count_diff"] = merged["count_compare"] - merged["count_base"]
    merged["avg_conf_diff"] = merged["avg_conf_compare"] - merged["avg_conf_base"]

    return merged.to_dict(orient="records")