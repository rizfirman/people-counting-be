from flask import Flask, Response, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from flask_socketio import SocketIO
from ultralytics import YOLO
from sort import Sort
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, time as dt_time
import cv2
import numpy as np
import os

app = Flask(__name__)

# Database configuration (replace with your PostgreSQL credentials)
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://postgres:1234@localhost/rizfirman'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Enable CORS for all routes
CORS(app)

# Initialize SocketIO
socketio = SocketIO(app, cors_allowed_origins="*")

# Set resolution for video capture
desired_width = 640
desired_height = 480

# Load YOLO model
model = YOLO('yolov8n.pt')

# Array of RTSP stream URLs
cctv_urls = [
   os.getenv('RSTP_LINK_1'),
  os.getenv('RSTP_LINK_2'),
]

# Initialize SORT tracker for each stream
trackers = [Sort() for _ in cctv_urls]

# Initialize daily count and last time for each stream
total_counts = [0 for _ in cctv_urls]  # Start with zero for each stream
last_time = [None for _ in cctv_urls]  # Last time for each stream
current_date = datetime.now().date()   # Variable to track current date

# Model for storing visitor counts with specific time of detection
class VisitorCount(db.Model):
    __tablename__ = 'visitor_count'
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)              # Store date in yyyy-mm-dd format
    stream_id = db.Column(db.Integer, nullable=False)
    time = db.Column(db.Time, nullable=False)               # Store exact time of entry in hh:mm:ss format
    accumulation_count_per_day = db.Column(db.Integer, nullable=False, default=0)  # Daily cumulative count
    realtime_count = db.Column(db.Integer, nullable=False)  # Count at the exact time of detection

    def __init__(self, date, stream_id, time, accumulation_count_per_day, realtime_count):
        self.date = date
        self.stream_id = stream_id
        self.time = time
        self.accumulation_count_per_day = accumulation_count_per_day
        self.realtime_count = realtime_count

# Function to initialize total counts and last time from the database
def initialize_total_counts():
    global total_counts, last_time
    today = datetime.now().date()
    for i in range(len(cctv_urls)):
        # Get the last record for today for each stream
        last_record = VisitorCount.query.filter_by(date=today, stream_id=i + 1).order_by(VisitorCount.id.desc()).first()
        total_counts[i] = last_record.accumulation_count_per_day if last_record else 0
        last_time[i] = last_record.time if last_record else None  # Store the last detection time

# Create the tables in the database and initialize total counts and last time
with app.app_context():
    db.create_all()
    initialize_total_counts()

# Function to save each detection to the database and update the daily cumulative count
# def save_entry_to_db(stream_id):
#     try:
#         with app.app_context():
#             now = datetime.now()
#             current_date = now.date()
#             exact_time = dt_time(now.hour, now.minute, now.second)  # Exact time in hh:mm:ss

#             # Retrieve the last entry to get the latest daily cumulative count
#             last_record = VisitorCount.query.filter_by(date=current_date, stream_id=stream_id).order_by(VisitorCount.id.desc()).first()
            
#             # If new day, reset accumulation count; otherwise, increment
#             current_count = last_record.accumulation_count_per_day + 1 if last_record else 1

#             # Add new entry with specific detection time, updated cumulative count, and real-time count (1 per detection)
#             new_entry = VisitorCount(
#                 date=current_date,
#                 stream_id=stream_id,
#                 time=exact_time,
#                 accumulation_count_per_day=current_count,
#                 realtime_count=1
#             )
#             db.session.add(new_entry)
#             db.session.commit()

#             # Update last_time for the stream after saving
#             last_time[stream_id - 1] = exact_time  # Update the last time for the stream
#             print(f"New entry added: Stream {stream_id}, Date: {current_date}, Time: {exact_time}, Daily Accumulation: {current_count}")
#     except Exception as e:
#         db.session.rollback()
#         print(f"Error while saving entry to DB: {e}")

def save_entry_to_db(stream_id):
    try:
        with app.app_context():
            now = datetime.now()
            current_date = now.date()
            exact_time = dt_time(now.hour, now.minute, now.second)  # Exact time in hh:mm:ss

            # Check for existing entry with the same date, stream_id, and exact time
            existing_record = VisitorCount.query.filter_by(
                date=current_date,
                stream_id=stream_id,
                time=exact_time
            ).first()

            if existing_record:
                # If an entry exists at the same time, increment the realtime_count
                existing_record.realtime_count += 1
                existing_record.accumulation_count_per_day += 1
                db.session.commit()
                print(f"Updated entry: Stream {stream_id}, Date: {current_date}, Time: {exact_time}, "
                      f"Daily Accumulation: {existing_record.accumulation_count_per_day}, "
                      f"Realtime Count: {existing_record.realtime_count}")
                
                # Update last_time for the stream after updating the existing record
                last_time[stream_id - 1] = exact_time

            else:
                # If no entry exists, create a new one with realtime_count set to 1
                # Retrieve the last entry to get the latest daily cumulative count
                last_record = VisitorCount.query.filter_by(date=current_date, stream_id=stream_id).order_by(VisitorCount.id.desc()).first()
                current_count = last_record.accumulation_count_per_day + 1 if last_record else 1

                # Add new entry with specific detection time, updated cumulative count, and real-time count (1 per detection)
                new_entry = VisitorCount(
                    date=current_date,
                    stream_id=stream_id,
                    time=exact_time,
                    accumulation_count_per_day=current_count,
                    realtime_count=1
                )
                db.session.add(new_entry)
                db.session.commit()

                # Update last_time for the stream after saving
                last_time[stream_id - 1] = exact_time  # Update the last time for the stream
                print(f"New entry added: Stream {stream_id}, Date: {current_date}, Time: {exact_time}, "
                      f"Daily Accumulation: {current_count}, Realtime Count: 1")
    except Exception as e:
        db.session.rollback()
        print(f"Error while saving entry to DB: {e}")


# Reset daily counts at midnight for each stream
def reset_daily_counts():
    global total_counts, current_date
    current_date = datetime.now().date()  # Perbarui tanggal
    total_counts = [0 for _ in cctv_urls]  # Reset total counts ke 0
    
    # Reset accumulation_count_per_day di database
    with app.app_context():
        for stream_id in range(1, len(cctv_urls) + 1):
            new_entry = VisitorCount(
                date=current_date,
                stream_id=stream_id,
                time=dt_time(0, 0, 0),
                accumulation_count_per_day=0,
                realtime_count=0
            )
            db.session.add(new_entry)
        db.session.commit()
    
    print("Daily counts and database accumulation counts reset at midnight.")

# Scheduler to reset counts daily at midnight
scheduler = BackgroundScheduler()
scheduler.add_job(func=reset_daily_counts, trigger='cron', hour=0, minute=0)
scheduler.start()

def generate_frames(url_index):
    global total_counts, current_date
    cap = cv2.VideoCapture(cctv_urls[url_index])

    if not cap.isOpened():
        print(f"Error: Could not open video source: {cctv_urls[url_index]}")
        return None

    counted_ids = set()
    tracker = trackers[url_index]

    while True:
        # Cek apakah hari telah berganti
        now = datetime.now().date()
        if now != current_date:
            # Jika hari berganti, reset total counts dan update dari database
            reset_daily_counts()
            initialize_total_counts()  # Ambil data akumulasi terbaru dari database

        ret, frame = cap.read()
        if not ret:
            print(f"Error: Could not read frame from video source: {cctv_urls[url_index]}")
            break

        frame = cv2.resize(frame, (desired_width, desired_height))

        # Perform object detection
        results = model(frame, conf=0.25)
        detections = results[0].boxes.data.cpu().numpy()

        line_position = frame.shape[0] // 2

        sort_input = []
        for det in detections:
            if len(det) >= 5:
                x1, y1, x2, y2, conf = det[:5]
                cls = det[5] if len(det) == 6 else None
                if cls is None or int(cls) == 0:
                    sort_input.append([x1, y1, x2, y2, conf])

        sort_input = np.array(sort_input)

        if sort_input.size > 0:
            tracked_objects = tracker.update(sort_input)
            for obj in tracked_objects:
                x1, y1, x2, y2, obj_id = obj
                center_y = int((y1 + y2) / 2)

                cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 0), 2)

                if center_y > line_position - 10 and center_y < line_position + 10:
                    if int(obj_id) not in counted_ids:
                        counted_ids.add(int(obj_id))
                        total_counts[url_index] += 1
                        print(f"Stream {url_index + 1} Daily count: {total_counts[url_index]}")
                        
                        # Save entry to database with exact time, updated cumulative count, and real-time count
                        save_entry_to_db(stream_id=url_index + 1)

                        # Emit updated count and time to WebSocket clients
                        socketio.emit('update_count', {
                            'stream_id': url_index + 1,
                            'totalCount': total_counts[url_index],
                            'timestamp': last_time[url_index].strftime("%H:%M:%S") if last_time[url_index] else "N/A"
                        })

        cv2.line(frame, (0, line_position), (frame.shape[1], line_position), (255, 0, 0), 2)
        cv2.putText(frame, f'Count: {total_counts[url_index]}', (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

        ret, buffer = cv2.imencode('.jpg', frame)
        frame = buffer.tobytes()

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

@app.route('/video_feed/<int:url_index>')
def video_feed(url_index):
    if 0 <= url_index < len(cctv_urls):
        return Response(generate_frames(url_index), mimetype='multipart/x-mixed-replace; boundary=frame')
    else:
        return f"Error: Invalid stream index {url_index}", 400

@app.route('/cctv_links')
def get_cctv_links():
    data = []
    for i, url in enumerate(cctv_urls):
        # Convert last_time to string if available
        timestamp_str = last_time[i].strftime("%H:%M:%S") if last_time[i] else "N/A"
        
        data.append({
            "id": i + 1,
            "link": f"/video_feed/{i}",
            "totalCount": total_counts[i],
            "timestamp": timestamp_str
        })
    return jsonify({"data": data})

@socketio.on('connect')
def handle_connect():
    print('Client connected')

if __name__ == "__main__":
    socketio.run(app, host='0.0.0.0', port=9000, debug=True)
