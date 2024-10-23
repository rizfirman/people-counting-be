from flask import Flask, Response, request, jsonify
from flask_cors import CORS  # Import Flask-CORS
from ultralytics import YOLO
import cv2
import numpy as np
from sort import Sort
from flask_socketio import SocketIO
from dotenv import load_dotenv
import os

# Muat file .env
load_dotenv()

app = Flask(__name__)

# Enable CORS for all routes
CORS(app)

# Initialize SocketIO
socketio = SocketIO(app, cors_allowed_origins="*")

# Load YOLO model
model = YOLO('yolov8n.pt')  # Change this if you're using a different YOLO model

# Array of RTSP stream URLs
cctv_urls = [
   os.getenv('RSTP_LINK_1'),
    os.getenv('RSTP_LINK_2'),
]

# Initialize SORT tracker for each stream
trackers = [Sort() for _ in cctv_urls]

# Initialize total count for each stream
total_counts = [0 for _ in cctv_urls]

# Set resolution for video capture
desired_width = 640
desired_height = 480

def generate_frames(url_index):
    global total_counts
    cap = cv2.VideoCapture(cctv_urls[url_index])
    
    if not cap.isOpened():
        print(f"Error: Could not open video source: {cctv_urls[url_index]}")
        return None

    counted_ids = set()  # Set to keep track of counted object IDs for each stream
    tracker = trackers[url_index]  # Use the corresponding tracker for this stream

    while True:
        ret, frame = cap.read()
        if not ret:
            print(f"Error: Could not read frame from video source: {cctv_urls[url_index]}")
            break

        # YOLOv8 Detection
        frame = cv2.resize(frame, (desired_width, desired_height))

        # Perform object detection
        results = model(frame, conf=0.25)
        detections = results[0].boxes.data.cpu().numpy()

        # Calculate center line position (y-coordinate for imaginary line)
        line_position = frame.shape[0] // 2  # Midpoint of the frame height

        # Prepare the detections for SORT: [x1, y1, x2, y2, score]
        sort_input = []
        for det in detections:
            if len(det) == 6:  # Ensure detection has 6 components: x1, y1, x2, y2, conf, cls
                x1, y1, x2, y2, conf, cls = det
                if int(cls) == 0:  # Only track 'person' class (class 0 in COCO)
                    sort_input.append([x1, y1, x2, y2, conf])

        # Convert to numpy array and check if sort_input is not empty
        sort_input = np.array(sort_input)

        # Check if sort_input has valid detections
        if sort_input.size > 0:
            # Update tracker
            tracked_objects = tracker.update(sort_input)

            # Process the tracked objects
            for obj in tracked_objects:
                x1, y1, x2, y2, obj_id = obj  # Extract bounding box and ID
                center_y = int((y1 + y2) / 2)

                # Draw the bounding box and ID
                cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 0), 2)
                # cv2.putText(frame, f'ID: {int(obj_id)}', (int(x1), int(y1) - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

                # Check if the person crosses the line and has not been counted yet
                if center_y > line_position - 10 and center_y < line_position + 10:
                    if int(obj_id) not in counted_ids:
                        counted_ids.add(int(obj_id))
                        total_counts[url_index] += 1  # Increment total count for this stream
                        print(f"Stream {url_index + 1} Person count: {total_counts[url_index]}")

                        # Emit total count to all connected WebSocket clients
                        socketio.emit('update_count', {'stream_id': url_index + 1, 'totalCount': total_counts[url_index]})

        # Draw the imaginary line in the middle of the frame
        cv2.line(frame, (0, line_position), (frame.shape[1], line_position), (255, 0, 0), 2)

        # Display the count on the frame
        cv2.putText(frame, f'Count: {total_counts[url_index]}', (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

        # Convert frame to JPEG format for streaming
        ret, buffer = cv2.imencode('.jpg', frame)
        frame = buffer.tobytes()

        # Yield the frame in byte format for streaming
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

@app.route('/video_feed/<int:url_index>')
def video_feed(url_index):
    # Video streaming route for the specified stream (based on url_index)
    if 0 <= url_index < len(cctv_urls):
        return Response(generate_frames(url_index), mimetype='multipart/x-mixed-replace; boundary=frame')
    else:
        return f"Error: Invalid stream index {url_index}", 400

@app.route('/cctv_links')
def get_cctv_links():
    # Return available channels with total counts
    data = []
    for i, url in enumerate(cctv_urls):
        data.append({
            "id": i + 1,
            "link": f"/video_feed/{i}",
            "totalCount": total_counts[i]
        })
    return jsonify({"data": data})

# WebSocket handler for when a client connects
@socketio.on('connect')
def handle_connect():
    print('Client connected')

if __name__ == "__main__":
    socketio.run(app, host='0.0.0.0', port=9000, debug=True)
