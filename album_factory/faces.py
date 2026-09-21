"""Local YuNet detection and SFace embeddings. Models are never sent photographs."""
from pathlib import Path
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


class FaceEngine:
    def __init__(self, model_dir=ROOT / "models"):
        self.detector = cv2.FaceDetectorYN.create(str(model_dir / "yunet.onnx"), "", (320, 320), 0.9, 0.3, 5000)
        self.recognizer = cv2.FaceRecognizerSF.create(str(model_dir / "sface.onnx"), "")

    def extract(self, image):
        height, width = image.shape[:2]
        scale = min(1.0, 1600 / max(height, width))
        if scale < 1:
            image = cv2.resize(image, (round(width * scale), round(height * scale)))
        self.detector.setInputSize((image.shape[1], image.shape[0]))
        _, faces = self.detector.detect(image)
        if faces is None:
            return "no_face", None
        if len(faces) != 1:
            return "multiple_faces", None
        face = faces[0]
        if min(face[2], face[3]) < 40:
            return "small_face", None
        aligned = self.recognizer.alignCrop(image, face)
        vector = self.recognizer.feature(aligned).flatten().astype(float)
        norm = np.linalg.norm(vector)
        if not np.isfinite(norm) or norm == 0:
            raise ValueError("Invalid face embedding")
        return "ready", (vector / norm).tolist()


def choose_person(vector, groups):
    """Conservative grouping: require best sample, mean support, and a clear margin.

    A new, uncertain group is preferable to silently merging different pupils.
    Thresholds require evaluation on the photographer's own sessions.
    """
    ranked = []
    for person_id, samples in groups.items():
        if not samples:
            continue
        similarities = np.array(samples) @ np.array(vector)
        ranked.append((float(similarities.max()), float(similarities.mean()), person_id))
    ranked.sort(reverse=True)
    if not ranked:
        return None, False
    best, average, person_id = ranked[0]
    runner_up = ranked[1][0] if len(ranked) > 1 else -1
    if best >= 0.5 and average >= 0.45 and best - runner_up >= 0.07:
        return person_id, False
    return None, best >= 0.35
