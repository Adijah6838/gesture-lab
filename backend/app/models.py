import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, Integer, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from .db import Base

class Dataset(Base):
    __tablename__ = "datasets"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    filename = Column(String, index=True)
    version = Column(Integer, default=1)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    total_rows = Column(Integer, default=0)
    valid_rows = Column(Integer, default=0)
    malformed_rows = Column(Integer, default=0)
    
    records = relationship("GestureRecord", back_populates="dataset", cascade="all, delete-orphan")

class GestureRecord(Base):
    __tablename__ = "gesture_records"
    id = Column(Integer, primary_key=True, autoincrement=True)
    dataset_id = Column(String, ForeignKey("datasets.id"))
    
    timestamp = Column(Float)
    gesture = Column(String, index=True)
    confidence = Column(Float)
    duration_ms = Column(Integer)
    hand = Column(String)
    
    # For tracking malformed rows
    is_malformed = Column(Integer, default=0) 
    raw_data = Column(JSON, nullable=True)

    dataset = relationship("Dataset", back_populates="records")