import cv2
import numpy as np
import mediapipe as mp
import base64
import onnxruntime as ort
import math
import os

# COCO class names (only what we need)
COCO_CLASSES = {0: "person", 67: "cell phone", 73: "book"}
CONF_THRESHOLD = 0.25
IOU_THRESHOLD = 0.45
INPUT_SIZE = 640

def _xywh_to_xyxy(boxes):
    """Convert cx,cy,w,h to x1,y1,x2,y2"""
    x1 = boxes[:, 0] - boxes[:, 2] / 2
    y1 = boxes[:, 1] - boxes[:, 3] / 2
    x2 = boxes[:, 0] + boxes[:, 2] / 2
    y2 = boxes[:, 1] + boxes[:, 3] / 2
    return np.stack([x1, y1, x2, y2], axis=1)

def _nms(boxes, scores, iou_threshold):
    """Simple NMS"""
    x1, y1, x2, y2 = boxes[:,0], boxes[:,1], boxes[:,2], boxes[:,3]
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]
    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        w = np.maximum(0.0, xx2 - xx1)
        h = np.maximum(0.0, yy2 - yy1)
        inter = w * h
        iou = inter / (areas[i] + areas[order[1:]] - inter)
        order = order[np.where(iou <= iou_threshold)[0] + 1]
    return keep

class VisionAnalyzer:
    def __init__(self):
        # Locate yolo11n.onnx in the root directory
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        model_path = os.path.join(base_dir, "yolo11n.onnx")
        self.ort_session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
        self.input_name = self.ort_session.get_inputs()[0].name
        
        # COCO ids: 67=cell phone, 73=book
        self.unauthorized_classes = [67, 73] 
        self.mp_face_mesh = mp.solutions.face_mesh.FaceMesh(
            static_image_mode=True, max_num_faces=1, min_detection_confidence=0.5, refine_landmarks=True
        )
        # Liveness tracking
        self.blink_threshold = 0.25
        self.consecutive_frames_below_threshold = 0
        self.frames_since_blink = 0
        self.nose_history = []
        
        # Bounding box tracker to ignore photo frames for multiple people detection
        self.persons = {}
        self.next_pid = 0
        
        # Calibration state
        self.baseline_H = None
        self.calibration_frames = []

    @staticmethod
    def calculate_gaze_ratio(iris_center, eye_left_point, eye_right_point):
        eye_width = eye_right_point.x - eye_left_point.x
        if eye_width == 0:
            return 0.5
        # Ratio goes from 0 (looking viewer's left) to 1 (looking viewer's right)
        return (iris_center.x - eye_left_point.x) / eye_width

    @staticmethod
    def calculate_ear(landmarks, indices):
        def dist(p1, p2):
            return math.hypot(landmarks[p1].x - landmarks[p2].x, landmarks[p1].y - landmarks[p2].y)
        
        # indices: [outer, upper1, upper2, inner, lower2, lower1]
        v1 = dist(indices[1], indices[5])
        v2 = dist(indices[2], indices[4])
        h = dist(indices[0], indices[3])
        
        if h == 0:
            return 0
        return (v1 + v2) / (2.0 * h)

    def decode_image(self, base64_image):
        img_data = base64.b64decode(base64_image.split(',')[1] if ',' in base64_image else base64_image)
        np_arr = np.frombuffer(img_data, np.uint8)
        img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        return img

    def analyze_frame(self, base64_image):
        img = self.decode_image(base64_image)
        results = {"objects_found": [], "multiple_persons": False, "gaze_deviation": False, "no_face_detected": False, "liveness_failed": False}
        
        # Object detection via ONNX Runtime
        h_orig, w_orig = img.shape[:2]
        # Preprocess: resize, normalize, BCHW
        blob = cv2.resize(img, (INPUT_SIZE, INPUT_SIZE))
        blob = cv2.cvtColor(blob, cv2.COLOR_BGR2RGB)
        blob = blob.astype(np.float32) / 255.0
        blob = np.transpose(blob, (2, 0, 1))[np.newaxis]
        # Inference
        raw = self.ort_session.run(None, {self.input_name: blob})[0]  # (1, 84, 8400)
        raw = raw[0].T  # (8400, 84)
        # Postprocess
        boxes_xywh = raw[:, :4]
        class_scores = raw[:, 4:]
        class_ids = np.argmax(class_scores, axis=1)
        confidences = class_scores[np.arange(len(class_scores)), class_ids]
        mask = confidences >= CONF_THRESHOLD
        boxes_xywh = boxes_xywh[mask]
        class_ids = class_ids[mask]
        confidences = confidences[mask]
        # Scale boxes back to original image size
        scale_x, scale_y = w_orig / INPUT_SIZE, h_orig / INPUT_SIZE
        boxes_xywh[:, 0] *= scale_x
        boxes_xywh[:, 2] *= scale_x
        boxes_xywh[:, 1] *= scale_y
        boxes_xywh[:, 3] *= scale_y
        boxes_xyxy = _xywh_to_xyxy(boxes_xywh) if len(boxes_xywh) > 0 else np.empty((0, 4))
        person_boxes_raw = []
        for i in (keep := _nms(boxes_xyxy, confidences, IOU_THRESHOLD) if len(boxes_xyxy) > 0 else []):
            cls_id = int(class_ids[i])
            if cls_id == 0:
                x1, y1, x2, y2 = map(int, boxes_xyxy[i])
                person_boxes_raw.append((x1, y1, x2, y2))
            elif cls_id in self.unauthorized_classes:
                results["objects_found"].append(COCO_CLASSES.get(cls_id, str(cls_id)))
                
        # Update person tracker
        new_persons = {}
        for box in person_boxes_raw:
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
                new_persons[self.next_pid] = {'history': [(cx, cy, w, h)], 'is_real': False}
                self.next_pid += 1
                
        self.persons = new_persons
        
        person_count = 0
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
                pdata['is_real'] = True
            elif len(hist) > 10:
                ws = [b[2] for b in hist]
                hs = [b[3] for b in hist]
                cxs = [b[0] for b in hist]
                cys = [b[1] for b in hist]
                total_var = np.var(ws) + np.var(hs) + np.var(cxs) + np.var(cys)
                
                pdata['is_real'] = total_var > 15.0
            else:
                pdata['is_real'] = False
            
            if pdata['is_real']:
                person_count += 1
                
        if person_count > 1:
            results["multiple_persons"] = True
            
        fake_boxes_detected = any(not pdata['is_real'] for pdata in self.persons.values())
        if fake_boxes_detected:
            results["background_warning"] = True
            
        # Gaze Tracking & Liveness
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        
        main_user_box = None
        if person_boxes_raw:
            # Sort raw YOLO person boxes by area
            sorted_raw = sorted(person_boxes_raw, key=lambda b: (b[2]-b[0])*(b[3]-b[1]), reverse=True)
            main_user_box = sorted_raw[0]
            
        if main_user_box:
            mx1, my1, mx2, my2 = main_user_box
            mw = mx2 - mx1
            mh = my2 - my1
            
            # Expand by 20%
            mx1 = max(0, int(mx1 - 0.2*mw))
            my1 = max(0, int(my1 - 0.2*mh))
            mx2 = min(img.shape[1], int(mx2 + 0.2*mw))
            my2 = min(img.shape[0], int(my2 + 0.2*mh))
            
            crop_rgb = img_rgb[my1:my2, mx1:mx2]
            if crop_rgb.shape[0] > 0 and crop_rgb.shape[1] > 0:
                mesh_results = self.mp_face_mesh.process(crop_rgb)
            else:
                mesh_results = self.mp_face_mesh.process(img_rgb)
        else:
            mesh_results = self.mp_face_mesh.process(img_rgb)
        
        if mesh_results.multi_face_landmarks:
            face_landmarks = mesh_results.multi_face_landmarks[0]
            
            nose_tip = face_landmarks.landmark[1]
            
            # Right eye (viewer's left)
            right_eye_left = face_landmarks.landmark[33]
            right_eye_right = face_landmarks.landmark[133]
            right_iris_center = face_landmarks.landmark[468]

            # Left eye (viewer's right)
            left_eye_left = face_landmarks.landmark[362]
            left_eye_right = face_landmarks.landmark[263]
            left_iris_center = face_landmarks.landmark[473]
            
            # Calculate true eye gaze (Iris Tracking)
            right_gaze_ratio = self.calculate_gaze_ratio(right_iris_center, right_eye_left, right_eye_right)
            left_gaze_ratio = self.calculate_gaze_ratio(left_iris_center, left_eye_left, left_eye_right)
            avg_gaze_ratio = (right_gaze_ratio + left_gaze_ratio) / 2.0
            
            # True gaze deviation (looking away from screen) horizontally
            if self.baseline_H is None:
                self.calibration_frames.append(avg_gaze_ratio)
                if len(self.calibration_frames) >= 30:
                    self.baseline_H = sum(self.calibration_frames) / 30.0
                results["calibrating"] = True
            else:
                if avg_gaze_ratio < 0.40 or avg_gaze_ratio > 0.59:
                    results["gaze_deviation"] = True

            # Head turning fallback
            eye_center_x = (right_eye_left.x + left_eye_right.x) / 2.0
            eye_dist = abs(left_eye_right.x - right_eye_left.x)
            
            if eye_dist > 0:
                deviation = abs(nose_tip.x - eye_center_x) / eye_dist
                if deviation > 0.15:
                    results["gaze_deviation"] = True
                    
            # Liveness Detection logic (Blink + Micromovement)
            right_eye_indices = [33, 160, 158, 133, 153, 144]
            left_eye_indices = [362, 385, 387, 263, 373, 380]
            
            right_ear = self.calculate_ear(face_landmarks.landmark, right_eye_indices)
            left_ear = self.calculate_ear(face_landmarks.landmark, left_eye_indices)
            avg_ear = (right_ear + left_ear) / 2.0
            
            if avg_ear < self.blink_threshold:
                self.consecutive_frames_below_threshold += 1
            else:
                if self.consecutive_frames_below_threshold >= 1:
                    # Blink occurred, reset the frames counter
                    self.frames_since_blink = 0
                self.consecutive_frames_below_threshold = 0
                
            self.frames_since_blink += 1
            
            self.nose_history.append((nose_tip.x, nose_tip.y))
            if len(self.nose_history) > 100:
                self.nose_history.pop(0)
                
            # Check liveness failure
            # Condition 1: No blink for a long time (e.g., 250 frames)
            if self.frames_since_blink > 250:
                results["liveness_failed"] = True
                
            # Condition 2: Completely static face (poster/photo)
            if len(self.nose_history) == 100:
                xs = [p[0] for p in self.nose_history]
                ys = [p[1] for p in self.nose_history]
                var_x = np.var(xs)
                var_y = np.var(ys)
                # Static images have almost 0 variance in relative landmark position, 
                # but there is tiny MediaPipe jitter. Threshold 1e-6 is extremely small.
                if var_x < 1e-7 and var_y < 1e-7:
                    results["liveness_failed"] = True
        else:
            results["no_face_detected"] = True
            self.frames_since_blink = 0 # reset if no face
            self.nose_history.clear()

                
        return results
