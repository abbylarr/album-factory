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

    def frame(self, image):
        """Normalised [x, y, w, h] of the only detected face, or None."""
        height, width = image.shape[:2]
        scale = min(1.0, 1600 / max(height, width))
        if scale < 1:
            image = cv2.resize(image, (round(width * scale), round(height * scale)))
        self.detector.setInputSize((image.shape[1], image.shape[0]))
        _, faces = self.detector.detect(image)
        if faces is None or len(faces) != 1:
            return None
        face = faces[0]
        image_h, image_w = image.shape[:2]
        return [
            float(face[0]) / image_w,
            float(face[1]) / image_h,
            float(face[2]) / image_w,
            float(face[3]) / image_h,
        ]


SUPPORT_SAMPLES = 3


def choose_person(vector, groups, *, strong_match_threshold=None, join_threshold=None):
    """Conservative grouping: require group support, mean support, and a clear margin.

    A group is scored by the mean of its few closest samples, not the single
    closest one: one misplaced frame must not pull every later frame of that
    pupil into someone else's group.
    Thresholds require evaluation on the photographer's own sessions.
    """
    ranked = []
    for person_id, samples in groups.items():
        if not samples:
            continue
        similarities = np.sort(np.array(samples) @ np.array(vector))[::-1]
        ranked.append((float(similarities[:SUPPORT_SAMPLES].mean()), float(similarities.mean()),
                       float(similarities[0]), person_id))
    ranked.sort(reverse=True)
    if not ranked:
        return None, False
    support, average, closest, person_id = ranked[0]
    runner_up = ranked[1][0] if len(ranked) > 1 else -1
    # Production may accept a uniquely best, very strong individual match even
    # when diverse poses lower the group mean or the usual margin is not met.
    # Keep the historical behavior for laboratory versions unless opted in.
    if strong_match_threshold is not None and closest >= strong_match_threshold and support > runner_up:
        return person_id, False
    # Two groups that both match strongly almost always hold one pupil split
    # earlier. Opening yet another group only deepens that split (one pupil
    # once became 62 persons), so join the closer one and flag it for review.
    if join_threshold is not None and support >= join_threshold:
        return person_id, support - runner_up < 0.07
    if support >= 0.5 and average >= 0.45 and support - runner_up >= 0.07:
        # A look-alike classmate scores in the same band as a pupil's own
        # hardest first frames, so a weak join from production goes to review.
        return person_id, join_threshold is not None and support < 0.7
    return None, support >= 0.35
