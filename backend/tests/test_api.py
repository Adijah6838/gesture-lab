import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.main import app
from app.db import Base, get_db

# Test DB
SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base.metadata.create_all(bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)

def test_upload_and_stats():
    # Test malformed file upload
    with open("../sample_data/gestures_malformed.csv", "rb") as f:
        res = client.post("/api/upload", files={"file": ("test.csv", f, "text/csv")})
    assert res.status_code == 200
    data = res.json()
    ds_id = data["dataset_id"]
    
    # Check stats
    stats_res = client.get(f"/api/datasets/{ds_id}/stats")
    assert stats_res.status_code == 200
    assert "summary" in stats_res.json()

def test_missing_columns():
    csv_content = "wrong_col,gesture\n1,tap"
    res = client.post("/api/upload", files={"file": ("bad.csv", csv_content, "text/csv")})
    assert res.status_code == 400
    assert "Missing columns" in res.json()["detail"]