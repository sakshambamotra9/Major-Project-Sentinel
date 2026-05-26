import os
from deepface import DeepFace
import cv2
import numpy as np
import base64

class IdentityVerifier:
    def __init__(self, model_name="Facenet", detector_backend="opencv"):
        self.model_name = model_name
        self.detector_backend = detector_backend

    def warmup(self):
        try:
            # Create a small dummy image to trigger model loading and warmup
            dummy_img = np.zeros((100, 100, 3), dtype=np.uint8)
            DeepFace.represent(img_path=dummy_img, 
                               model_name=self.model_name, 
                               detector_backend=self.detector_backend,
                               enforce_detection=False)
            print("DeepFace model warmed up successfully.")
        except Exception as e:
            print(f"Warmup error: {e}")

    def decode_image(self, base64_image):
        img_data = base64.b64decode(base64_image.split(',')[1] if ',' in base64_image else base64_image)
        np_arr = np.frombuffer(img_data, np.uint8)
        img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        return img

    def verify(self, baseline_base64, current_base64):
        try:
            img1 = self.decode_image(baseline_base64)
            img2 = self.decode_image(current_base64)
            
            result = DeepFace.verify(img1_path=img1, img2_path=img2, 
                                     model_name=self.model_name, 
                                     detector_backend=self.detector_backend,
                                     enforce_detection=False)
            return {
                "verified": result["verified"],
                "distance": result["distance"],
                "threshold": result["threshold"]
            }
        except Exception as e:
            return {"error": str(e), "verified": False}

    def get_embedding(self, base64_image):
        try:
            img = self.decode_image(base64_image)
            reps = DeepFace.represent(img_path=img, 
                                     model_name=self.model_name, 
                                     detector_backend=self.detector_backend,
                                     enforce_detection=False)
            if reps and len(reps) > 0:
                return reps[0]["embedding"]
            return None
        except Exception as e:
            print(f"Error getting embedding: {e}")
            return None

    def verify_embedding(self, ref_embedding, live_embedding, threshold=0.40):
        try:
            a = np.array(ref_embedding)
            b = np.array(live_embedding)
            denom = np.linalg.norm(a) * np.linalg.norm(b)
            if denom == 0:
                return {"verified": False, "distance": 1.0, "threshold": threshold}
            distance = 1.0 - (np.dot(a, b) / denom)
            return {
                "verified": bool(distance <= threshold),
                "distance": float(distance),
                "threshold": float(threshold)
            }
        except Exception as e:
            return {"error": str(e), "verified": False}
