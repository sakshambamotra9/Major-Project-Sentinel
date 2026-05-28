from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import os
import sys
import cv2
import requests
import base64
import time
import subprocess
import threading
import random
from dotenv import load_dotenv
from supabase import create_client, Client

# Load environment configuration
if getattr(sys, 'frozen', False):
    exe_dir = os.path.dirname(sys.executable)
    external_env = os.path.join(exe_dir, ".env")
    if os.path.exists(external_env):
        print(f"Loading environment from external .env: {external_env}")
        load_dotenv(external_env)
    else:
        bundled_env = os.path.join(getattr(sys, '_MEIPASS', ''), "backend", ".env")
        if os.path.exists(bundled_env):
            print(f"Loading environment from bundled .env: {bundled_env}")
            load_dotenv(bundled_env)
        else:
            load_dotenv()
else:
    # Development mode path: check current dir or backend/
    load_dotenv()
    if not os.getenv("SUPABASE_URL"):
        load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

try:
    from models.identity import IdentityVerifier
    IDENTITY_AVAILABLE = True
except Exception as e:
    print(f"WARNING: Identity verification disabled due to import error: {e}")
    IDENTITY_AVAILABLE = False
from models.vision import VisionAnalyzer

app = FastAPI(title="Sentinel Exam AI Services", description="AI Proctoring Microservice")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if IDENTITY_AVAILABLE:
    identity_verifier = IdentityVerifier()
else:
    identity_verifier = None
vision_analyzer = VisionAnalyzer()

# Supabase Initialization
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase_client: Client | None = None

if SUPABASE_URL and SUPABASE_KEY and not SUPABASE_URL.startswith("https://your-"):
    try:
        supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
        print("Supabase client initialized successfully!")
    except Exception as e:
        print(f"Failed to initialize Supabase client: {e}")
else:
    print("WARNING: Supabase credentials not configured. Running in local/in-memory mode.")

class IdentityPayload(BaseModel):
    baseline_base64: str
    current_base64: str

class ReferencePayload(BaseModel):
    student_id: str
    image_base64: str

class RegisterStudentPayload(BaseModel):
    student_id: str
    student_name: str
    semester: str
    password: str
    image_base64: str

class StudentLoginPayload(BaseModel):
    student_id: str
    password: str

class VisionPayload(BaseModel):
    frame_base64: str
    student_id: str | None = None

class CalibratePayload(BaseModel):
    student_id: str
    frame_base64: str

reference_embeddings = {}
multi_reference_embeddings = {}
candidate_frame_states = {}

def start_warmup():
    def warmup_task():
        try:
            print("Background warmup: initializing models...")
            if IDENTITY_AVAILABLE and identity_verifier:
                identity_verifier.warmup()
            if vision_analyzer:
                # Accessing properties triggers lazy-loading and compilation in background
                _ = vision_analyzer.ort_session
                _ = vision_analyzer.mp_face_mesh
                print("VisionAnalyzer models warmed up in background.")
        except Exception as e:
            print(f"Error during background model warmup: {e}")

    thread = threading.Thread(target=warmup_task, daemon=True)
    thread.start()

@app.on_event("startup")
def startup_event():
    start_warmup()

class WifiConnectPayload(BaseModel):
    ssid: str

def upload_to_ipfs(filepath):
    """Uploads a file to a local IPFS node (preferring local daemon for decentralization) with Pinata fallback."""
    filename = os.path.basename(filepath)

    # 1. Try local IPFS node first (decentralized)
    try:
        print(f"Uploading {filename} to local IPFS node...")
        with open(filepath, 'rb') as f:
            # Assumes local IPFS daemon is running on default port 5001
            response = requests.post('http://127.0.0.1:5001/api/v0/add', files={'file': f}, timeout=5)
        if response.status_code == 200:
            cid = response.json().get('Hash')
            print(f"Successfully uploaded to local IPFS node! CID: {cid}")
            
            # Copy to MFS (Mutable File System) to make it visible in IPFS Desktop
            try:
                import urllib.parse
                mfs_path = f"/{filename}"
                cp_url = f"http://127.0.0.1:5001/api/v0/files/cp?arg=/ipfs/{cid}&arg={urllib.parse.quote(mfs_path)}"
                requests.post(cp_url, timeout=3)
                print(f"Pinned to local MFS as {mfs_path}")
            except Exception as e:
                print(f"Uploaded to local IPFS but could not pin to MFS UI: {e}")
                
            return cid
        else:
            print(f"Local IPFS API error: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"Local IPFS node upload failed: {e}. Falling back to Pinata...")

    # 2. Try Pinata if local fails and credentials are set
    pinata_jwt = os.getenv("PINATA_JWT")
    pinata_key = os.getenv("PINATA_API_KEY")
    pinata_secret = os.getenv("PINATA_API_SECRET")

    if pinata_jwt or (pinata_key and pinata_secret):
        print(f"Uploading {filename} to Pinata IPFS...")
        try:
            url = "https://api.pinata.cloud/pinning/pinFileToIPFS"
            headers = {}
            if pinata_jwt:
                headers["Authorization"] = f"Bearer {pinata_jwt.strip()}"
            else:
                headers["pinata_api_key"] = pinata_key.strip()
                headers["pinata_secret_api_key"] = pinata_secret.strip()

            with open(filepath, 'rb') as f:
                files = {
                    'file': (filename, f, 'image/jpeg')
                }
                response = requests.post(url, files=files, headers=headers, timeout=15)
            
            if response.status_code == 200:
                cid = response.json().get('IpfsHash')
                print(f"Successfully uploaded to Pinata IPFS! CID: {cid}")
                return cid
            else:
                print(f"Pinata API error: {response.status_code} - {response.text}")
        except Exception as e:
            print(f"Pinata upload failed: {e}")

    return None

# Root endpoint is handled at the bottom by the React static file server

@app.post("/api/v1/verify_identity")
def verify_identity(payload: IdentityPayload):
    if not identity_verifier:
        raise HTTPException(status_code=503, detail="Identity verification is currently disabled on the server.")
    result = identity_verifier.verify(payload.baseline_base64, payload.current_base64)
    return {"result": result}

@app.post("/api/v1/calibrate_pose")
def calibrate_pose(payload: CalibratePayload):
    if not identity_verifier:
        raise HTTPException(status_code=503, detail="Identity verification is currently disabled on the server.")
        
    img = identity_verifier.decode_image(payload.frame_base64)
    if img is None:
        raise HTTPException(status_code=400, detail="Invalid image frame.")
        
    h, w = img.shape[:2]
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    mesh_results = identity_verifier.mp_face_mesh.process(img_rgb)
    
    if not mesh_results.multi_face_landmarks:
        return {
            "success": False,
            "error": "No face detected",
            "angle_detected": None,
            "current_status": get_calibration_status(payload.student_id)
        }
        
    face_landmarks = mesh_results.multi_face_landmarks[0]
    
    # 1. Detect Pose Angle using relative landmarks
    # Nose tip
    nose = face_landmarks.landmark[1]
    # Eye corners (left outer, right outer)
    left_eye = face_landmarks.landmark[33]
    right_eye = face_landmarks.landmark[263]
    
    eye_center_x = (left_eye.x + right_eye.x) / 2.0
    eye_dist = abs(right_eye.x - left_eye.x)
    
    if eye_dist == 0:
        return {
            "success": False, 
            "error": "Invalid face size", 
            "angle_detected": None, 
            "current_status": get_calibration_status(payload.student_id)
        }
        
    # Horizontal pose difference ratio
    horizontal_ratio = (nose.x - eye_center_x) / eye_dist
    
    # Vertical pose difference ratio
    eye_y = (left_eye.y + right_eye.y) / 2.0
    vertical_ratio = (nose.y - eye_y) / eye_dist
    
    angle_detected = "CENTER"
    if horizontal_ratio < -0.15:
        angle_detected = "LEFT"
    elif horizontal_ratio > 0.15:
        angle_detected = "RIGHT"
    elif vertical_ratio < 0.55:
        angle_detected = "UP"
    elif vertical_ratio > 0.82:
        angle_detected = "DOWN"
        
    # Get embedding
    embedding = identity_verifier.get_embedding(payload.frame_base64)
    if not embedding:
        return {
            "success": False,
            "error": "Could not extract face embedding",
            "angle_detected": angle_detected,
            "current_status": get_calibration_status(payload.student_id)
        }
        
    # Save the embedding for this angle
    sid = payload.student_id
    if sid not in multi_reference_embeddings:
        multi_reference_embeddings[sid] = {
            "CENTER": None,
            "LEFT": None,
            "RIGHT": None,
            "UP": None,
            "DOWN": None
        }
        
    multi_reference_embeddings[sid][angle_detected] = embedding
    
    return {
        "success": True,
        "angle_detected": angle_detected,
        "current_status": get_calibration_status(sid)
    }

def get_calibration_status(student_id):
    if student_id not in multi_reference_embeddings:
        return {"CENTER": False, "LEFT": False, "RIGHT": False, "UP": False, "DOWN": False}
    status = {}
    for k, v in multi_reference_embeddings[student_id].items():
        status[k] = (v is not None)
    return status

@app.post("/api/v1/register_reference")
def register_reference(payload: ReferencePayload):
    if not identity_verifier:
        raise HTTPException(status_code=503, detail="Identity verification is currently disabled on the server.")
    embedding = identity_verifier.get_embedding(payload.image_base64)
    if not embedding:
        raise HTTPException(status_code=400, detail="Could not extract face embedding from the provided image. Please ensure your face is clearly visible.")
    reference_embeddings[payload.student_id] = embedding
    candidate_frame_states[payload.student_id] = {
        "last_state": "in",
        "leave_count": 0,
        "consecutive_no_face": 0,
        "verify_counter": 0,
        "last_verify_failed": False
    }
    return {"success": True}

@app.post("/api/v1/admin/register_student")
def register_student(payload: RegisterStudentPayload):
    if not identity_verifier:
        raise HTTPException(status_code=503, detail="Identity verification is currently disabled on the server.")
    
    embedding = identity_verifier.get_embedding(payload.image_base64)
    if not embedding:
        raise HTTPException(status_code=400, detail="Could not extract face embedding from the provided image. Please ensure your face is clearly visible.")
    
    photo_url = None
    
    if supabase_client:
        try:
            img_data_str = payload.image_base64
            if "," in img_data_str:
                img_data_str = img_data_str.split(",")[1]
            img_bytes = base64.b64decode(img_data_str)
            
            supabase_client.storage.from_("student-photos").upload(
                path=f"{payload.student_id}.jpg",
                file=img_bytes,
                file_options={"content-type": "image/jpeg", "x-upsert": "true"}
            )
            photo_url = supabase_client.storage.from_("student-photos").get_public_url(f"{payload.student_id}.jpg")
        except Exception as e:
            print(f"Failed to upload reference photo to Supabase storage: {e}")
            
        try:
            student_data = {
                "student_id": payload.student_id,
                "student_name": payload.student_name,
                "semester": payload.semester,
                "password": payload.password,
                "photo_url": photo_url,
                "embedding": embedding
            }
            supabase_client.table("students").upsert(student_data).execute()
        except Exception as e:
            print(f"Failed to insert student into Supabase DB: {e}")
            raise HTTPException(status_code=500, detail=f"Database insert failed: {str(e)}")
            
    reference_embeddings[payload.student_id] = embedding
    candidate_frame_states[payload.student_id] = {
        "last_state": "in",
        "leave_count": 0,
        "consecutive_no_face": 0,
        "verify_counter": 0,
        "last_verify_failed": False
    }
    
    return {"success": True, "photo_url": photo_url}

@app.get("/api/v1/admin/students")
def get_students():
    students = []
    if supabase_client:
        try:
            response = supabase_client.table("students").select("student_id, student_name, semester, photo_url").order("student_id").execute()
            if response.data:
                students = response.data
        except Exception as e:
            print(f"Failed to fetch students list: {e}")
    else:
        for sid in reference_embeddings.keys():
            students.append({
                "student_id": sid,
                "student_name": f"Cached Student {sid}",
                "semester": "Semester 1",
                "photo_url": None
            })
    return {"students": students}

@app.post("/api/v1/student/login")
def student_login(payload: StudentLoginPayload):
    student_name = "Mock Student"
    semester = "N/A"
    photo_url = None
    embedding = None
    
    if supabase_client:
        try:
            response = supabase_client.table("students").select("*").eq("student_id", payload.student_id).execute()
            if response.data and len(response.data) > 0:
                user_data = response.data[0]
                if user_data["password"] == payload.password:
                    student_name = user_data["student_name"]
                    semester = user_data["semester"]
                    photo_url = user_data["photo_url"]
                    
                    # Generate reference embedding on-the-fly using the active ArcFace model
                    # to ensure it matches the model used for live camera verification
                    embedding = None
                    if photo_url and identity_verifier:
                        try:
                            print(f"Generating reference embedding from photo_url: {photo_url}")
                            import urllib.request
                            req = urllib.request.Request(
                                photo_url, 
                                headers={'User-Agent': 'Mozilla/5.0'}
                            )
                            with urllib.request.urlopen(req, timeout=8) as img_res:
                                img_bytes = img_res.read()
                            img_b64 = base64.b64encode(img_bytes).decode('utf-8')
                            embedding = identity_verifier.get_embedding(img_b64)
                            if embedding:
                                print(f"Successfully generated embedding using active ArcFace model.")
                                # Save it back to Supabase so that we don't have to keep downloading it (this updates it to the new model!)
                                try:
                                    supabase_client.table("students").update({"embedding": embedding}).eq("student_id", payload.student_id).execute()
                                    print(f"Updated student embedding in Supabase database.")
                                except Exception as save_err:
                                    print(f"Could not update embedding in Supabase: {save_err}")
                        except Exception as emb_err:
                            print(f"Failed to generate embedding from photo_url: {emb_err}")
                            
                    if not embedding:
                        # Fallback to database value
                        embedding = user_data.get("embedding")
                else:
                    raise HTTPException(status_code=401, detail="Invalid student credentials.")
            else:
                raise HTTPException(status_code=404, detail="Student not found.")
        except HTTPException as he:
            raise he
        except Exception as e:
            print(f"Supabase login fetch failed: {e}")
            raise HTTPException(status_code=500, detail=f"Database error during login: {str(e)}")
    else:
        if payload.student_id == "demo" and payload.password == "demo123":
            student_name = "Demo Student"
            semester = "Semester 8"
        else:
            if payload.student_id in reference_embeddings:
                student_name = f"Student {payload.student_id}"
            else:
                raise HTTPException(status_code=401, detail="Offline Mode: Use roll number 'demo' and password 'demo123' to login.")
                
    if embedding:
        reference_embeddings[payload.student_id] = embedding
        candidate_frame_states[payload.student_id] = {
            "last_state": "in",
            "leave_count": 0,
            "consecutive_no_face": 0,
            "verify_counter": 0,
            "last_verify_failed": False
        }
        
    return {
        "success": True,
        "student_id": payload.student_id,
        "student_name": student_name,
        "semester": semester,
        "photo_url": photo_url,
        "embedding_loaded": bool(payload.student_id in reference_embeddings)
    }

@app.post("/api/v1/analyze_vision")
def analyze_vision(payload: VisionPayload):
    result = vision_analyzer.analyze_frame(payload.frame_base64)
    
    # Identity matching against reference embedding during pre-test
    if payload.student_id and payload.student_id in reference_embeddings and identity_verifier:
        live_emb = identity_verifier.get_embedding(payload.frame_base64)
        if live_emb:
            ref_emb = reference_embeddings[payload.student_id]
            ver_res = identity_verifier.verify_embedding(ref_emb, live_emb)
            result["identity_verified"] = bool(ver_res.get("verified", False))
        else:
            result["identity_verified"] = False
    else:
        result["identity_verified"] = True
        
    return {"result": result}

def get_risk_label(score: int, violation_type: str) -> str:
    has_serious = ("multiple" in violation_type.lower() or 
                   "liveness" in violation_type.lower() or 
                   "spoof" in violation_type.lower())
    effective_score = max(score, 70) if has_serious else score
    if effective_score <= 30:
        return 'Low'
    if effective_score <= 60:
        return 'Moderate'
    if effective_score <= 85:
        return 'High'
    return 'Very High'

def push_violation_in_background(student_id: str, frame_score: int, violation_type: str, img_bytes: bytes):
    def worker():
        try:
            # 1. Save frame locally
            user_documents = os.path.join(os.path.expanduser("~"), "Documents")
            violations_dir = os.path.join(user_documents, "Sentinel_Violations")
            os.makedirs(violations_dir, exist_ok=True)
            
            import time
            local_save_path = os.path.join(violations_dir, f"violation_{student_id or 'student'}_{int(time.time())}.jpg")
            with open(local_save_path, "wb") as f:
                f.write(img_bytes)
            print(f"Saved violation screenshot locally to: {local_save_path}")
            
            # 2. Upload to IPFS
            ipfs_cid = upload_to_ipfs(local_save_path)
            
            # 3. Push to Supabase if client exists
            if supabase_client:
                # Fetch existing violations and current risk_score
                response = supabase_client.table("sessions").select("violations, risk_score").eq("student_id", student_id).execute()
                current_violations = []
                current_risk = 0
                if response.data and len(response.data) > 0:
                    current_violations = response.data[0].get("violations") or []
                    current_risk = response.data[0].get("risk_score") or 0
                
                new_risk = min(100, current_risk + frame_score)
                risk_label = get_risk_label(new_risk, violation_type)
                
                import datetime
                # Time format like "5:38:03 pm"
                now_time = datetime.datetime.now().strftime("%I:%M:%S %p").lower()
                if now_time.startswith("0"):
                    now_time = now_time[1:]
                    
                new_violation = {
                    "type": violation_type,
                    "time": now_time,
                    "cid": ipfs_cid
                }
                
                updated_violations = current_violations + [new_violation]
                
                supabase_client.table("sessions").update({
                    "risk_score": new_risk,
                    "risk_label": risk_label,
                    "last_updated": datetime.datetime.utcnow().isoformat() + "Z",
                    "violations": updated_violations
                }).eq("student_id", student_id).execute()
                print(f"Async violation pushed to Supabase for student {student_id}. CID: {ipfs_cid}")
        except Exception as e:
            print(f"Failed to push violation in background: {e}")

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

@app.post("/api/v1/analyze_behavior")
def analyze_behavior(payload: VisionPayload):
    vision_result = vision_analyzer.analyze_frame(payload.frame_base64)
    
    score = 0
    flags = []
    
    if vision_result["multiple_persons"]:
        score += 50
        flags.append("Multiple persons detected")
    if vision_result["objects_found"]:
        score += 40
        flags.append(f"Unauthorized objects: {', '.join(vision_result['objects_found'])}")
    if vision_result.get("gaze_deviation"):
        score += 20
        flags.append("Gaze deviation detected")
    if vision_result.get("no_face_detected"):
        score += 50
        flags.append("No face detected (Camera Blocked?)")
    if vision_result.get("liveness_failed"):
        score += 80
        flags.append("Liveliness check failed (Spoofing or static image detected)")
    if vision_result.get("background_warning"):
        flags.append("TIP: Background contains photo frames/distractions. Please sit in a clear environment.")
        
    # Live face verification & repeatedly leaving frame tracking
    if payload.student_id:
        if payload.student_id not in reference_embeddings and supabase_client:
            try:
                response = supabase_client.table("students").select("embedding, photo_url").eq("student_id", payload.student_id).execute()
                if response.data and len(response.data) > 0:
                    db_embedding = response.data[0].get("embedding")
                    db_photo_url = response.data[0].get("photo_url")
                    
                    if db_photo_url and identity_verifier:
                        # Lazy generation on-the-fly from photo_url to match active ArcFace model
                        try:
                            print(f"Lazy downloading and generating embedding from photo: {db_photo_url}")
                            import urllib.request
                            req = urllib.request.Request(
                                db_photo_url, 
                                headers={'User-Agent': 'Mozilla/5.0'}
                            )
                            with urllib.request.urlopen(req, timeout=8) as img_res:
                                img_bytes = img_res.read()
                            img_b64 = base64.b64encode(img_bytes).decode('utf-8')
                            generated_emb = identity_verifier.get_embedding(img_b64)
                            if generated_emb:
                                reference_embeddings[payload.student_id] = generated_emb
                                print(f"Successfully lazy generated embedding for {payload.student_id}")
                                # Save back to DB to update it to new model
                                try:
                                    supabase_client.table("students").update({"embedding": generated_emb}).eq("student_id", payload.student_id).execute()
                                except Exception:
                                    pass
                        except Exception as emb_err:
                            print(f"Failed to lazy generate embedding: {emb_err}")
                            if db_embedding:
                                reference_embeddings[payload.student_id] = db_embedding
                    elif db_embedding:
                        reference_embeddings[payload.student_id] = db_embedding
                        print(f"Recovered reference embedding for student {payload.student_id} from database.")
            except Exception as e:
                print(f"Failed to recover reference embedding from database: {e}")

    if payload.student_id and payload.student_id in reference_embeddings:
        if payload.student_id not in candidate_frame_states:
            candidate_frame_states[payload.student_id] = {
                "last_state": "in",
                "leave_count": 0,
                "consecutive_no_face": 0,
                "verify_counter": 0,
                "last_verify_failed": False
            }
        
        state = candidate_frame_states[payload.student_id]
        
        # Track leaving the frame repeatedly
        if vision_result.get("no_face_detected"):
            state["consecutive_no_face"] += 1
            if state["consecutive_no_face"] >= 3:
                if state["last_state"] == "in":
                    state["last_state"] = "out"
                    state["leave_count"] += 1
                
                if state["leave_count"] >= 3:
                    score += 30
                    flags.append("Candidate left frame repeatedly")
        else:
            state["consecutive_no_face"] = 0
            state["last_state"] = "in"

    if score > 0 and payload.student_id:
        try:
            # Decode base64 frame in main thread to avoid copying issues across threads
            img_data_str = payload.frame_base64
            if "," in img_data_str:
                img_data_str = img_data_str.split(",")[1]
            img_bytes = base64.b64decode(img_data_str)
            
            # Delegate to background thread
            push_violation_in_background(payload.student_id, score, ", ".join(flags), img_bytes)
        except Exception as e:
            print(f"Failed to kick off background violation push: {e}")

    return {
        "risk_score": score,
        "flags": flags,
        "vision_details": vision_result,
        "ipfs_cid": None
    }

@app.post("/api/v1/system/wifi-flyout")
def open_wifi_flyout():
    try:
        # Opens the native Windows 11 WiFi network flyout directly
        os.system("start ms-availablenetworks:")
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/v1/system/close")
def close_system():
    os._exit(0)
    return {"success": True}

@app.delete("/api/v1/ipfs/unpin/{cid}")
def unpin_ipfs_file(cid: str):
    """Unpins a file from local IPFS daemon (if running) and Pinata IPFS fallback."""
    unpinned_locally = False
    local_error = None

    # 1. Try local IPFS node unpin
    try:
        url = f"http://127.0.0.1:5001/api/v0/pin/rm?arg={cid}"
        response = requests.post(url, timeout=5)
        if response.status_code == 200:
            unpinned_locally = True
            print(f"Successfully unpinned CID {cid} from local IPFS.")
        else:
            local_error = f"Status {response.status_code}: {response.text}"
    except Exception as e:
        local_error = str(e)

    # 2. Try Pinata fallback unpin
    pinata_jwt = os.getenv("PINATA_JWT")
    pinata_key = os.getenv("PINATA_API_KEY")
    pinata_secret = os.getenv("PINATA_API_SECRET")

    if pinata_jwt or (pinata_key and pinata_secret):
        try:
            url = f"https://api.pinata.cloud/pinning/unpin/{cid}"
            headers = {}
            if pinata_jwt:
                headers["Authorization"] = f"Bearer {pinata_jwt.strip()}"
            else:
                headers["pinata_api_key"] = pinata_key.strip()
                headers["pinata_secret_api_key"] = pinata_secret.strip()

            response = requests.delete(url, headers=headers, timeout=10)
            if response.status_code == 200:
                return {"success": True, "source": "pinata"}
            else:
                return {"success": unpinned_locally, "source": "local" if unpinned_locally else None, "error": f"Pinata returned {response.status_code}: {response.text}"}
        except Exception as e:
            return {"success": unpinned_locally, "source": "local" if unpinned_locally else None, "error": str(e)}

    if unpinned_locally:
        return {"success": True, "source": "local"}
    
    return {"success": False, "error": f"Local IPFS unpin failed: {local_error}. Pinata credentials not configured."}



# Mount React Frontend
frontend_dist = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "dist")
if os.path.exists(frontend_dist):
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_dist, "assets")), name="assets")
    
    @app.get("/{full_path:path}")
    def serve_frontend(full_path: str):
        filepath = os.path.join(frontend_dist, full_path)
        if os.path.exists(filepath) and os.path.isfile(filepath):
            return FileResponse(filepath)
        return FileResponse(os.path.join(frontend_dist, "index.html"))
else:
    print(f"WARNING: Frontend dist folder not found at {frontend_dist}. Please run 'npm run build' in the frontend folder.")
