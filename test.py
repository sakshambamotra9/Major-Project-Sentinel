import cv2
from ultralytics import YOLO
import mediapipe as mp
import time
import requests
import math
from collections import deque
import numpy as np

# Load YOLO model
model = YOLO("yolo11n.pt")

# MediaPipe Face Mesh
mp_face = mp.solutions.face_mesh
face_mesh = mp_face.FaceMesh(max_num_faces=1, refine_landmarks=True)

class PersonTracker:
    def __init__(self):
        self.persons = {}
        self.next_id = 0
        
    def update(self, current_boxes):
        new_persons = {}
        for box in current_boxes:
            cx = (box[0] + box[2]) / 2.0
            cy = (box[1] + box[3]) / 2.0
            w = box[2] - box[0]
            h = box[3] - box[1]
            
            best_id = -1
            best_dist = float('inf')
            for pid, pdata in self.persons.items():
                last_box = pdata['history'][-1]
                dist = math.hypot(cx - last_box[0], cy - last_box[1])
                if dist < 100:
                    best_id = pid
                    best_dist = dist
                    
            if best_id != -1 and best_id not in new_persons:
                new_persons[best_id] = self.persons[best_id]
                new_persons[best_id]['history'].append((cx, cy, w, h))
                if len(new_persons[best_id]['history']) > 90:
                    new_persons[best_id]['history'].pop(0)
            else:
                new_persons[self.next_id] = {'history': [(cx, cy, w, h)], 'is_real': False}
                self.next_id += 1
                
        self.persons = new_persons
        
        real_boxes = []
        fake_boxes = []
        
        # Identify largest box as main user
        largest_id = -1
        max_area = 0
        for pid, pdata in self.persons.items():
            last_box = pdata['history'][-1]
            area = last_box[2] * last_box[3]
            if area > max_area:
                max_area = area
                largest_id = pid
                
        for pid, pdata in self.persons.items():
            hist = pdata['history']
            if pid == largest_id:
                pdata['is_real'] = True # Main user is always real
            elif len(hist) > 10:
                ws = [b[2] for b in hist]
                hs = [b[3] for b in hist]
                cxs = [b[0] for b in hist]
                cys = [b[1] for b in hist]
                total_var = np.var(ws) + np.var(hs) + np.var(cxs) + np.var(cys)
                
                # Dynamic evaluation (no permanent latching) with a robust threshold
                pdata['is_real'] = total_var > 15.0
            else:
                pdata['is_real'] = False
            
            last_box = hist[-1]
            bx1, by1, bx2, by2 = int(last_box[0] - last_box[2]/2), int(last_box[1] - last_box[3]/2), int(last_box[0] + last_box[2]/2), int(last_box[1] + last_box[3]/2)
            
            if pdata['is_real']:
                real_boxes.append((bx1, by1, bx2, by2))
            else:
                fake_boxes.append((bx1, by1, bx2, by2))
                
        return real_boxes, fake_boxes

person_tracker = PersonTracker()

# ---- Rolling average buffer to smooth out jitter (last 10 frames) ----
SMOOTH_FRAMES = 10
h_ratio_buf = deque(maxlen=SMOOTH_FRAMES)
v_ratio_buf = deque(maxlen=SMOOTH_FRAMES)

def calculate_horizontal_gaze(iris_center, eye_left, eye_right):
    """Iris x position as a fraction of eye width. 0=full left, 1=full right."""
    eye_width = eye_right.x - eye_left.x
    if eye_width == 0:
        return 0.5
    return (iris_center.x - eye_left.x) / eye_width

def calculate_vertical_gaze(iris_center, eye_top, eye_bottom):
    """Iris y position as a fraction of eye height. 0=full up, 1=full down."""
    eye_height = eye_bottom.y - eye_top.y
    if eye_height == 0:
        return 0.5
    return (iris_center.y - eye_top.y) / eye_height

def calculate_ear(landmarks, indices):
    def dist(p1, p2):
        return math.hypot(landmarks[p1].x - landmarks[p2].x, landmarks[p1].y - landmarks[p2].y)
    v1 = dist(indices[1], indices[5])
    v2 = dist(indices[2], indices[4])
    h = dist(indices[0], indices[3])
    if h == 0: return 0
    return (v1 + v2) / (2.0 * h)
cap = cv2.VideoCapture(0)

snapshot_count = 0
last_capture_time = 0

# Variables for thresholds and continuous violation tracking
looking_away_start_time = None
no_face_start_time = None
head_turn_start_time = None
multiple_people_start_time = None
liveness_fail_start_time = None
LOOK_AWAY_THRESHOLD = 2.0 # seconds for eye movement
NO_FACE_THRESHOLD = 1.0   # seconds for no face
HEAD_TURN_THRESHOLD = 0.5 # seconds for head movement
MULTIPLE_PEOPLE_THRESHOLD = 1.0 # seconds to confirm multiple people
LIVENESS_THRESHOLD = 1.0 # seconds to confirm spoof

# Liveness state
blink_threshold = 0.25
consecutive_frames_below_threshold = 0
frames_since_blink = 0
nose_history = []

warning_count = 0
MAX_WARNINGS = 5
exam_terminated = False
termination_reason = "EXAM TERMINATED - MALPRACTICE"

# Calibration state
baseline_H = None
baseline_V = None
calibration_frames = []

def upload_to_ipfs(filepath):
    """Uploads a file to a local IPFS node and makes it visible in IPFS Desktop."""
    try:
        with open(filepath, 'rb') as f:
            # Assumes local IPFS daemon is running on default port 5001
            response = requests.post('http://127.0.0.1:5001/api/v0/add', files={'file': f}, timeout=5)
        if response.status_code == 200:
            cid = response.json().get('Hash')
            
            # Copy to MFS (Mutable File System) to make it visible in IPFS Desktop "Files" tab
            try:
                import urllib.parse
                mfs_path = f"/{filepath}"
                cp_url = f"http://127.0.0.1:5001/api/v0/files/cp?arg=/ipfs/{cid}&arg={urllib.parse.quote(mfs_path)}"
                requests.post(cp_url, timeout=3)
            except Exception as e:
                print(f"Uploaded to IPFS but could not pin to MFS UI: {e}")
                
            return cid
        else:
            print(f"IPFS API error: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"IPFS upload failed: {e}. Ensure IPFS Daemon is running locally.")
    return None

while True:
    ret, frame = cap.read()
    if not ret:
        break

    h, w, _ = frame.shape

    # ---------------- YOLO (Detection) ----------------
    results = model(frame, verbose=False)

    phone_detected = False
    person_boxes_raw = []

    for r in results:
        for box in r.boxes:
            cls = int(box.cls[0])
            label = model.names[cls]

            if label == "person":
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                person_boxes_raw.append((x1, y1, x2, y2))
            elif label == "cell phone":
                phone_detected = True
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                cv2.rectangle(frame, (x1,y1), (x2,y2), (0,0,255), 2)
                cv2.putText(frame, "PHONE!", (x1,y1-10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,0,255), 2)

    # Filter real people vs static photo frames using bounding box variance
    real_boxes, fake_boxes = person_tracker.update(person_boxes_raw)
    person_count = len(real_boxes)
    
    for (x1, y1, x2, y2) in real_boxes:
        cv2.rectangle(frame, (x1,y1), (x2,y2), (0,165,255), 2)
        cv2.putText(frame, "REAL PERSON", (x1, y1-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,165,255), 2)
        
    for (x1, y1, x2, y2) in fake_boxes:
        cv2.rectangle(frame, (x1,y1), (x2,y2), (255,0,0), 2)
        cv2.putText(frame, "PERSON", (x1, y1-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,0,0), 2)

    if person_count > 1:
        # Give a popup/warning on the screen
        cv2.rectangle(frame, (0, 0), (w, 50), (0, 0, 255), -1)
        cv2.putText(frame, f"WARNING: {person_count} PEOPLE DETECTED!", (50, 35),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 3)

    # ---------------- Eye & Head Tracking ----------------
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    
    # Isolate main user for MediaPipe to prevent background photos from interfering
    main_user_box = None
    if real_boxes:
        # Sort by area
        sorted_boxes = sorted(real_boxes, key=lambda b: (b[2]-b[0])*(b[3]-b[1]), reverse=True)
        main_user_box = sorted_boxes[0]
        
    crop_offset_x = 0
    crop_offset_y = 0
    crop_w = w
    crop_h = h
    
    if main_user_box:
        mx1, my1, mx2, my2 = main_user_box
        mw = mx2 - mx1
        mh = my2 - my1
        
        # Expand box by 20% to ensure whole head is captured
        mx1 = max(0, int(mx1 - 0.2*mw))
        my1 = max(0, int(my1 - 0.2*mh))
        mx2 = min(w, int(mx2 + 0.2*mw))
        my2 = min(h, int(my2 + 0.2*mh))
        
        crop_rgb = rgb[my1:my2, mx1:mx2]
        
        if crop_rgb.shape[0] > 0 and crop_rgb.shape[1] > 0:
            result = face_mesh.process(crop_rgb)
            crop_offset_x = mx1
            crop_offset_y = my1
            crop_w = mx2 - mx1
            crop_h = my2 - my1
        else:
            result = face_mesh.process(rgb)
    else:
        result = face_mesh.process(rgb)

    looking_away = False
    liveness_failed = False
    gaze_direction = "CENTER"

    if result.multi_face_landmarks:
        face_landmarks = result.multi_face_landmarks[0]
        lm = face_landmarks.landmark

        # --- Iris landmarks (MediaPipe 478-point model) ---
        right_iris = lm[468]   # right eye iris center
        left_iris  = lm[473]   # left eye iris center

        # --- Eye corner landmarks (horizontal reference) ---
        right_eye_left  = lm[33]   # viewer right of right eye (outer)
        right_eye_right = lm[133]  # viewer left  of right eye (inner)
        left_eye_left   = lm[362]  # viewer right of left eye  (inner)
        left_eye_right  = lm[263]  # viewer left  of left eye  (outer)

        # --- Eye top/bottom landmarks (vertical reference) ---
        right_eye_top    = lm[159]
        right_eye_bottom = lm[145]
        left_eye_top     = lm[386]
        left_eye_bottom  = lm[374]

        # --- Horizontal ratio (per eye, then averaged) ---
        r_h = calculate_horizontal_gaze(right_iris, right_eye_left, right_eye_right)
        l_h = calculate_horizontal_gaze(left_iris,  left_eye_left,  left_eye_right)
        avg_h = (r_h + l_h) / 2.0

        # --- Vertical ratio (per eye, then averaged) ---
        r_v = calculate_vertical_gaze(right_iris, right_eye_top, right_eye_bottom)
        l_v = calculate_vertical_gaze(left_iris,  left_eye_top,  left_eye_bottom)
        avg_v = (r_v + l_v) / 2.0

        # --- Push into rolling buffers ---
        h_ratio_buf.append(avg_h)
        v_ratio_buf.append(avg_v)
        smooth_h = sum(h_ratio_buf) / len(h_ratio_buf)
        smooth_v = sum(v_ratio_buf) / len(v_ratio_buf)

        # --- Draw iris dots ---
        cv2.circle(frame, (int(right_iris.x * crop_w) + crop_offset_x, int(right_iris.y * crop_h) + crop_offset_y), 4, (0, 255, 0), -1)
        cv2.circle(frame, (int(left_iris.x  * crop_w) + crop_offset_x, int(left_iris.y  * crop_h) + crop_offset_y), 4, (0, 255, 0), -1)

        # -----------------------------------------------
        # Dynamic Calibration & Thresholds
        # -----------------------------------------------
        if baseline_H is None:
            calibration_frames.append((smooth_h, smooth_v))
            cv2.putText(frame, "CALIBRATING GAZE... LOOK AT SCREEN", (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 3)
            
            if len(calibration_frames) >= 30:
                baseline_H = sum([f[0] for f in calibration_frames]) / 30.0
                baseline_V = sum([f[1] for f in calibration_frames]) / 30.0
            else:
                # Skip detection logic while calibrating
                cv2.imshow("Proctoring", frame)
                if cv2.waitKey(1) & 0xFF == 27:
                    break
                continue

        H_LEFT  = 0.40
        H_RIGHT = 0.59
        V_DOWN  = baseline_V + 0.15  # Threshold for looking down at a phone

        if smooth_v > V_DOWN:
            looking_away = True
            gaze_direction = "LOOKING DOWN"
        elif smooth_h < H_LEFT:
            looking_away = True
            gaze_direction = "LOOKING RIGHT"
        elif smooth_h > H_RIGHT:
            looking_away = True
            gaze_direction = "LOOKING LEFT"
        
        # --- Head pose fallback ---
        nose = lm[1]
        eye_center_x = (right_eye_left.x + left_eye_right.x) / 2.0
        eye_dist = abs(left_eye_right.x - right_eye_left.x)
        if eye_dist > 0:
            head_dev = abs(nose.x - eye_center_x) / eye_dist
            if head_dev > 0.15: # Made more sensitive to catch head movement
                looking_away = True
                gaze_direction = "HEAD TURNED"

        # --- Liveness tracking (EAR & Nose Variance) ---
        right_eye_indices = [33, 160, 158, 133, 153, 144]
        left_eye_indices = [362, 385, 387, 263, 373, 380]
        right_ear = calculate_ear(lm, right_eye_indices)
        left_ear = calculate_ear(lm, left_eye_indices)
        avg_ear = (right_ear + left_ear) / 2.0
        
        if avg_ear < blink_threshold:
            consecutive_frames_below_threshold += 1
        else:
            if consecutive_frames_below_threshold >= 1:
                frames_since_blink = 0
            consecutive_frames_below_threshold = 0
        frames_since_blink += 1
        
        nose_history.append((nose.x, nose.y))
        if len(nose_history) > 100:
            nose_history.pop(0)
            
        if frames_since_blink > 250:
            liveness_failed = True
            
        if len(nose_history) == 100:
            xs = [p[0] for p in nose_history]
            ys = [p[1] for p in nose_history]
            if np.var(xs) < 1e-7 and np.var(ys) < 1e-7:
                liveness_failed = True

        if liveness_failed:
            cv2.rectangle(frame, (0, h - 150), (w, h - 100), (0, 0, 255), -1)
            cv2.putText(frame, "WARNING: LIVENESS FAILED (SPOOF)", (20, h - 115),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
                        
        if len(fake_boxes) > 0:
            cv2.putText(frame, "TIP: Please sit with a plain background to avoid frame detection", (20, h - 160), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

        # --- Debug overlay: show live ratios ---
        cv2.putText(frame, f"H:{smooth_h:.2f} V:{smooth_v:.2f}", (w - 200, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 2)
        cv2.putText(frame, f"Thresh: H[{H_LEFT:.2f}-{H_RIGHT:.2f}] V[{V_DOWN:.2f}]", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 1)

        if looking_away:
            cv2.rectangle(frame, (0, h - 100), (w, h - 50), (0, 165, 255), -1)
            warning_text = f"WARNING: EYES NOT ON SCREEN  [{gaze_direction}]"
            cv2.putText(frame, warning_text, (20, h - 65),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    else:
        # No face detected
        looking_away = True
        liveness_failed = False
        h_ratio_buf.clear()
        v_ratio_buf.clear()
        frames_since_blink = 0
        nose_history.clear()
        
        cv2.rectangle(frame, (0, h - 50), (w, h), (0, 0, 255), -1)
        cv2.putText(frame, "WARNING: NO FACE DETECTED (CAMERA BLOCKED?)", (10, h - 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255,255,255), 2)

    current_time = time.time()
    
    trigger_snapshot = False

    # 1. Phone detected (immediate)
    if phone_detected:
        trigger_snapshot = True
        exam_terminated = False
        termination_reason = "EXAM TERMINATED - PHONE DETECTED"

    # Multiple people (with delay to avoid false positives)
    if person_count > 1:
        if multiple_people_start_time is None:
            multiple_people_start_time = current_time
        elif (current_time - multiple_people_start_time) > MULTIPLE_PEOPLE_THRESHOLD:
            trigger_snapshot = True
    else:
        multiple_people_start_time = None

    # 2. No face detected / Camera Blocked
    if not result.multi_face_landmarks:
        if no_face_start_time is None:
            no_face_start_time = current_time
        elif (current_time - no_face_start_time) > NO_FACE_THRESHOLD:
            trigger_snapshot = True
    else:
        no_face_start_time = None

    # 3. Head turned
    if result.multi_face_landmarks and gaze_direction == "HEAD TURNED":
        if head_turn_start_time is None:
            head_turn_start_time = current_time
        elif (current_time - head_turn_start_time) > HEAD_TURN_THRESHOLD:
            trigger_snapshot = True
    else:
        head_turn_start_time = None

    # 4. Eye looking away (left/right/down)
    if result.multi_face_landmarks and looking_away and gaze_direction in ["LOOKING LEFT", "LOOKING RIGHT", "LOOKING DOWN"]:
        if looking_away_start_time is None:
            looking_away_start_time = current_time
        elif (current_time - looking_away_start_time) > LOOK_AWAY_THRESHOLD:
            trigger_snapshot = True
    else:
        looking_away_start_time = None
        
    # 5. Liveness failed
    if result.multi_face_landmarks and liveness_failed:
        if liveness_fail_start_time is None:
            liveness_fail_start_time = current_time
        elif (current_time - liveness_fail_start_time) > LIVENESS_THRESHOLD:
            trigger_snapshot = True
    else:
        liveness_fail_start_time = None

    # ---------------- Snapshot Logic ----------------
    if trigger_snapshot and (current_time - last_capture_time > 3):
        filename = f"snapshot_{snapshot_count}.jpg"
        cv2.imwrite(filename, frame)
        print(f"\n--- SNAPSHOT TAKEN ---")
        print(f"Saved: {filename}")
        
        # Upload to IPFS
        print(f"Uploading {filename} to IPFS...")
        cid = upload_to_ipfs(filename)
        if cid:
            print(f"SUCCESS! IPFS CID: {cid}")
            print(f"IPFS Link: http://127.0.0.1:8080/ipfs/{cid}")
        else:
            print("Failed to get CID.")
            
        print("----------------------\n")

        snapshot_count += 1
        warning_count += 1
        last_capture_time = current_time
        looking_away_start_time = None  # Reset to prevent continuous snapping
        no_face_start_time = None
        head_turn_start_time = None
        multiple_people_start_time = None
        liveness_fail_start_time = None

        if warning_count >= MAX_WARNINGS:
            exam_terminated = True

    # ---------------- Display ----------------
    # Show warning count on screen
    cv2.putText(frame, f"Warnings: {warning_count}/{MAX_WARNINGS}", (10, h - 110),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

    if exam_terminated:
        cv2.rectangle(frame, (0, 0), (w, h), (0, 0, 255), -1)
        cv2.putText(frame, termination_reason, (50, h // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 3)
        cv2.imshow("Proctoring", frame)
        cv2.waitKey(4000) # Wait 4 seconds before closing
        break

    cv2.imshow("Proctoring", frame)

    if cv2.waitKey(1) & 0xFF == 27:
        break

cap.release()
cv2.destroyAllWindows()