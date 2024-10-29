from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi_sqlalchemy import DBSessionMiddleware, db
from sqlalchemy import Column, Integer, Date, Time
from sqlalchemy.orm import declarative_base
from pydantic import BaseModel
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, time as dt_time
import cv2
import numpy as np
import os
from ultralytics import YOLO
from sort import Sort
import asyncio

app = FastAPI()
app.add_middleware(DBSessionMiddleware, db_url=os.getenv("DATABASE_URL"))

# Database setup
Base = declarative_base()

class VisitorCount(Base):
    __tablename__ = 'visitor_count'
    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    stream_id = Column(Integer, nullable=False)
    time = Column(Time, nullable=False)
    accumulation_count_per_day = Column(Integer, nullable=False, default=0)
    realtime_count = Column(Integer, nullable=False)

    def __init__(self, date, stream_id, time, accumulation_count_per_day, realtime_count):
        self.date = date
        self.stream_id = stream_id
        self.time = time
        self.accumulation_count_per_day = accumulation_count_per_day
        self.realtime_count = realtime_count

# Initialize YOLO and video streams
desired_width, desired_height = 640, 480
model = YOLO("yolov8n.pt")
cctv_urls = [os.getenv("RSTP_LINK_1"), os.getenv("RSTP_LINK_2")]
trackers = [Sort() for _ in cctv_urls]
total_counts = [0 for _ in cctv_urls]
current_date = datetime.now().date()

# Functions for database operations
def initialize_total_counts():
    global total_counts
    today = datetime.now().date()
    session = db.session
    for i in range(len(cctv_urls)):
        last_record = session.query(VisitorCount).filter_by(date=today, stream_id=i + 1).order_by(VisitorCount.id.desc()).first()
        total_counts[i] = last_record.accumulation_count_per_day if last_record else 0

async def save_entry_to_db(stream_id):
    try:
        now = datetime.now()
        session = db.session
        current_date = now.date()
        exact_time = dt_time(now.hour, now.minute, now.second)

        last_record = session.query(VisitorCount).filter_by(date=current_date, stream_id=stream_id).order_by(VisitorCount.id.desc()).first()
        current_count = last_record.accumulation_count_per_day + 1 if last_record else 1

        new_entry = VisitorCount(date=current_date, stream_id=stream_id, time=exact_time, accumulation_count_per_day=current_count, realtime_count=1)
        session.add(new_entry)
        session.commit()
    except Exception as e:
        session.rollback()
        print(f"Error while saving entry to DB: {e}")

# Reset daily counts at midnight
def reset_daily_counts():
    global total_counts, current_date
    current_date = datetime.now().date()
    total_counts = [0 for _ in cctv_urls]
    session = db.session
    for stream_id in range(1, len(cctv_urls) + 1):
        new_entry = VisitorCount(date=current_date, stream_id=stream_id, time=dt_time(0, 0, 0), accumulation_count_per_day=0, realtime_count=0)
        session.add(new_entry)
    session.commit()

scheduler = BackgroundScheduler()
scheduler.add_job(reset_daily_counts, "cron", hour=0, minute=0)
scheduler.start()

# Video streaming and object detection
async def generate_frames(url_index: int):
    global total_counts, current_date
    cap = cv2.VideoCapture(cctv_urls[url_index])
    if not cap.isOpened():
        raise HTTPException(status_code=404, detail="Could not open video source")

    counted_ids = set()
    tracker = trackers[url_index]

    while True:
        if datetime.now().date() != current_date:
            reset_daily_counts()
            initialize_total_counts()

        ret, frame = cap.read()
        if not ret:
            break

        frame = cv2.resize(frame, (desired_width, desired_height))
        results = model(frame, conf=0.25)
        detections = results[0].boxes.data.cpu().numpy()

        sort_input = []
        for det in detections:
            if len(det) >= 5:
                x1, y1, x2, y2, conf = det[:5]
                cls = det[5] if len(det) == 6 else None
                if cls is None or int(cls) == 0:
                    sort_input.append([x1, y1, x2, y2, conf])

        if sort_input:
            tracked_objects = tracker.update(np.array(sort_input))
            for obj in tracked_objects:
                x1, y1, x2, y2, obj_id = obj
                if int(obj_id) not in counted_ids:
                    counted_ids.add(int(obj_id))
                    total_counts[url_index] += 1
                    await save_entry_to_db(stream_id=url_index + 1)

        ret, buffer = cv2.imencode(".jpg", frame)
        frame = buffer.tobytes()
        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"

@app.get("/video_feed/{url_index}")
async def video_feed(url_index: int):
    if 0 <= url_index < len(cctv_urls):
        return StreamingResponse(generate_frames(url_index), media_type="multipart/x-mixed-replace; boundary=frame")
    else:
        raise HTTPException(status_code=400, detail="Invalid stream index")

@app.get("/cctv_links")
async def get_cctv_links():
    data = [{"id": i + 1, "link": f"/video_feed/{i}", "totalCount": total_counts[i]} for i in range(len(cctv_urls))]
    return JSONResponse(content={"data": data})

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            for i, count in enumerate(total_counts):
                await websocket.send_json({"stream_id": i + 1, "totalCount": count, "timestamp": datetime.now().strftime("%H:%M")})
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        print("Client disconnected")

# Run the app with: uvicorn main:app --host 0.0.0.0 --port 9000
