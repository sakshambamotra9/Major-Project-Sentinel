from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import os
import requests
import base64
import time
import subprocess
import threading
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

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

reference_embeddings = {}
candidate_frame_states = {}

def start_warmup():
    if IDENTITY_AVAILABLE and identity_verifier:
        print("Starting DeepFace model warmup in background thread...")
        thread = threading.Thread(target=identity_verifier.warmup, daemon=True)
        thread.start()

@app.on_event("startup")
def startup_event():
    start_warmup()

class WifiConnectPayload(BaseModel):
    ssid: str

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
                mfs_path = f"/{os.path.basename(filepath)}"
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

# Root endpoint is handled at the bottom by the React static file server

@app.post("/api/v1/verify_identity")
def verify_identity(payload: IdentityPayload):
    if not identity_verifier:
        raise HTTPException(status_code=503, detail="Identity verification is currently disabled on the server.")
    result = identity_verifier.verify(payload.baseline_base64, payload.current_base64)
    return {"result": result}

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
                    embedding = user_data.get("embedding")
                    
                    # On-the-fly embedding generation if it is not yet stored in Supabase
                    if not embedding and photo_url:
                        try:
                            print(f"Downloading student reference photo for on-the-fly embedding: {photo_url}")
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
                                print(f"Successfully generated embedding from photo_url on-the-fly for {payload.student_id}")
                                # Save back to Supabase so we don't have to download/compute it again
                                try:
                                    supabase_client.table("students").update({"embedding": embedding}).eq("student_id", payload.student_id).execute()
                                    print(f"Saved generated embedding back to Supabase for {payload.student_id}")
                                except Exception as save_err:
                                    print(f"Could not save generated embedding back to Supabase: {save_err}")
                        except Exception as emb_err:
                            print(f"Failed to generate embedding on-the-fly from url: {emb_err}")
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
    if payload.student_id and payload.student_id in reference_embeddings:
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
                    
                    if db_embedding:
                        reference_embeddings[payload.student_id] = db_embedding
                        print(f"Recovered reference embedding for student {payload.student_id} from database.")
                    elif db_photo_url:
                        # Lazy generation on-the-fly from photo_url
                        try:
                            print(f"Lazy downloading student reference photo: {db_photo_url}")
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
                                print(f"Successfully generated lazy embedding for {payload.student_id}")
                                # Save back to DB
                                try:
                                    supabase_client.table("students").update({"embedding": generated_emb}).eq("student_id", payload.student_id).execute()
                                except Exception:
                                    pass
                        except Exception as emb_err:
                            print(f"Failed to lazy generate embedding: {emb_err}")
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
        
        # Identity verification during the exam is disabled (only verified during pre-test check)
        state["last_verify_failed"] = False
            
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

    ipfs_cid = None
    if score > 0:
        # We found a violation! Save the frame and upload to IPFS.
        try:
            # Decode base64 (handle data URI scheme if present)
            img_data_str = payload.frame_base64
            if "," in img_data_str:
                img_data_str = img_data_str.split(",")[1]
            img_bytes = base64.b64decode(img_data_str)
            
            # Save to temporary file
            filename = f"violation_{int(time.time())}.jpg"
            with open(filename, "wb") as f:
                f.write(img_bytes)
                
            # Upload to IPFS
            ipfs_cid = upload_to_ipfs(filename)
            
            # Clean up local file
            if os.path.exists(filename):
                os.remove(filename)
        except Exception as e:
            print(f"Failed to process and upload snapshot: {e}")

    return {
        "risk_score": score,
        "flags": flags,
        "vision_details": vision_result,
        "ipfs_cid": ipfs_cid
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

class BrowserPayload(BaseModel):
    url: str = "https://www.bing.com"

@app.post("/api/v1/browser/open")
def open_browser(payload: BrowserPayload):
    """
    Launches Microsoft Edge (or Chrome as fallback) in fullscreen app mode.
    This gives a real browser experience — no iframe X-Frame-Options restrictions.
    """
    url = payload.url
    try:
        # Try Edge first (pre-installed on all modern Windows)
        edge_paths = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ]
        chrome_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]

        browser_exe = None
        for p in edge_paths + chrome_paths:
            if os.path.exists(p):
                browser_exe = p
                break

        if browser_exe:
            subprocess.Popen([
                browser_exe,
                f"--app={url}",
                "--start-fullscreen",
                "--no-first-run",
                "--disable-translate",
                "--disable-infobars",
            ])
        else:
            # Fallback: open with default browser via shell
            os.system(f'start "" "{url}"')

        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

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
