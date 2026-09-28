"""Local models for general photos. Nothing here sends pixels outside the machine.

YuNet + SFace (faces, identity), MediaPipe Face Landmarker read by OpenCV DNN
(eyes and smile), RTMO-s (people and body keypoints), CLIP ViT-B/32 (scene,
aesthetics and near duplicates). Every optional model degrades gracefully:
missing files only remove the corresponding fields. See scripts/fetch_models.py.
"""
from __future__ import annotations

from datetime import datetime
from functools import cached_property
from pathlib import Path
import base64
import hashlib
import json
import math
import re
import threading
import zipfile

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / 'models'

# Scene dictionary: key -> (label, English prompt for CLIP). Versioned with the analysis.
TAGS = {
    'classroom': ('Класс', 'a photo of students sitting at desks in a school classroom'),
    'library': ('Библиотека', 'a photo of people in a library with bookshelves'),
    'hall': ('Школьный коридор', 'a photo of people in a school hallway'),
    'gym': ('Спортзал', 'a photo of children playing sports in a gym'),
    'stage': ('Сцена', 'a photo of children performing on a stage'),
    'ceremony': ('Праздник, линейка', 'a photo of a school ceremony with balloons and flowers'),
    'studio': ('Студия', 'a studio photo with a plain backdrop'),
    'nature': ('Природа', 'a photo of people outdoors on grass in a park or forest'),
    'beach': ('Море', 'a photo of people on a beach by the sea'),
    'city': ('Город', 'a photo of people on a city street'),
    'picnic': ('Пикник', 'a photo of friends having a picnic with food'),
    'winter': ('Зима', 'a photo of people outside in the snow in winter'),
}
PAIRS = {
    'aesthetic': ('a beautiful professional photograph with great composition', 'a blurry badly lit amateur snapshot'),
    'posed': ('a posed group photo, everyone smiling at the camera', 'a candid photo of people who are not looking at the camera'),
    'indoor': ('a photo taken indoors', 'a photo taken outdoors'),
}
# MediaPipe face_blendshapes graph: landmark subset fed to the blendshape model.
BLEND_SUBSET = [0, 1, 4, 5, 6, 7, 8, 10, 13, 14, 17, 21, 33, 37, 39, 40, 46, 52, 53, 54, 55, 58, 61, 63, 65, 66, 67, 70, 78, 80, 81, 82, 84, 87, 88, 91, 93, 95, 103, 105, 107, 109, 127, 132, 133, 136, 144, 145, 146, 148, 149, 150, 152, 153, 154, 155, 157, 158, 159, 160, 161, 162, 163, 168, 172, 173, 176, 178, 181, 185, 191, 195, 197, 234, 246, 249, 251, 263, 267, 269, 270, 276, 282, 283, 284, 285, 288, 291, 293, 295, 296, 297, 300, 308, 310, 311, 312, 314, 317, 318, 321, 323, 324, 332, 334, 336, 338, 356, 361, 362, 365, 373, 374, 375, 377, 378, 379, 380, 381, 382, 384, 385, 386, 387, 388, 389, 390, 397, 398, 400, 402, 405, 409, 415, 454, 466, 468, 469, 470, 471, 472, 473, 474, 475, 476, 477]
BLINK_LEFT, BLINK_RIGHT, SMILE_LEFT, SMILE_RIGHT = 9, 10, 44, 45
CLIP_MEAN = np.array([0.48145466, 0.4578275, 0.40821073])
CLIP_STD = np.array([0.26862954, 0.26130258, 0.27577711])


def pack(vector):
    return base64.b64encode(np.asarray(vector, dtype=np.float16).tobytes()).decode()


def unpack(text):
    return np.frombuffer(base64.b64decode(text), dtype=np.float16).astype(np.float32) if text else None


def taken_at(path):
    """EXIF capture time with offset as ISO text, or None."""
    try:
        with Image.open(path) as image:
            exif = image.getexif()
            sub = exif.get_ifd(0x8769)
            value = sub.get(0x9003) or exif.get(0x0132)
            if not value:
                return None, exif.get(0x0110)
            moment = datetime.strptime(str(value).strip(), '%Y:%m:%d %H:%M:%S')
            offset = sub.get(0x9011) or sub.get(0x9010)
            text = moment.isoformat() + (offset.strip() if isinstance(offset, str) and re.fullmatch(r'[+-]\d\d:\d\d', offset.strip()) else '')
            return text, exif.get(0x0110)
    except (OSError, ValueError, SyntaxError):
        return None, None


class ClipTokenizer:
    """Byte-level BPE of CLIP for plain lower-case prompts."""
    def __init__(self, folder):
        self.vocab = json.loads((folder / 'vocab.json').read_text(encoding='utf-8'))
        merges = (folder / 'merges.txt').read_text(encoding='utf-8').split('\n')[1:]
        self.ranks = {tuple(m.split()): i for i, m in enumerate(merges) if m.strip()}
        codes = list(range(ord('!'), ord('~') + 1)) + list(range(ord('¡'), ord('¬') + 1)) + list(range(ord('®'), ord('ÿ') + 1))
        chars, extra = codes[:], 0
        for b in range(256):
            if b not in codes:
                codes.append(b); chars.append(256 + extra); extra += 1
        self.bytes = dict(zip(codes, map(chr, chars)))

    def bpe(self, word):
        parts = list(word[:-1]) + [word[-1] + '</w>']
        while len(parts) > 1:
            rank, index = min((self.ranks.get(pair, math.inf), i) for i, pair in enumerate(zip(parts, parts[1:])))
            if rank == math.inf:
                break
            parts = parts[:index] + [parts[index] + parts[index + 1]] + parts[index + 2:]
        return parts

    def encode(self, text):
        ids = [49406]
        for token in re.findall(r"'s|'t|'re|'ve|'m|'ll|'d|[a-z]+|[0-9]|[^\sa-z0-9]+", ' '.join(text.lower().split())):
            ids += [self.vocab[p] for p in self.bpe(''.join(self.bytes[b] for b in token.encode()))]
        return ids + [49407]


class GeneralVision:
    def __init__(self, model_dir=MODELS):
        self.dir = Path(model_dir)
        self.lock = threading.Lock()

    def has(self, *names):
        return all((self.dir / n).is_file() for n in names)

    @property
    def features(self):
        return {'faces': self.has('yunet.onnx', 'sface.onnx'), 'expressions': self.has('face_landmarker.task'),
                'bodies': self.has('rtmo-s.onnx'),
                'scene': self.has('clip/vision_model_quantized.onnx', 'clip/text_model_quantized.onnx', 'clip/vocab.json', 'clip/merges.txt')}

    @cached_property
    def detector(self):
        return cv2.FaceDetectorYN.create(str(self.dir / 'yunet.onnx'), '', (320, 320), 0.6, 0.3, 5000)

    @cached_property
    def recognizer(self):
        return cv2.FaceRecognizerSF.create(str(self.dir / 'sface.onnx'), '')

    @cached_property
    def mesh(self):
        with zipfile.ZipFile(self.dir / 'face_landmarker.task') as bundle:
            landmarks = bundle.read('face_landmarks_detector.tflite')
            blend = bundle.read('face_blendshapes.tflite')
        return (cv2.dnn.readNetFromTFLite(np.frombuffer(landmarks, np.uint8)),
                cv2.dnn.readNetFromTFLite(np.frombuffer(blend, np.uint8)))

    @cached_property
    def rtmo(self):
        import onnxruntime as ort
        return ort.InferenceSession(str(self.dir / 'rtmo-s.onnx'), providers=['CPUExecutionProvider'])

    @cached_property
    def clip(self):
        import onnxruntime as ort
        return ort.InferenceSession(str(self.dir / 'clip/vision_model_quantized.onnx'), providers=['CPUExecutionProvider'])

    @cached_property
    def prompts(self):
        """Text embeddings of the dictionary, cached next to the model."""
        texts = [p for _, p in TAGS.values()] + [p for pair in PAIRS.values() for p in pair]
        key = hashlib.sha256('\n'.join(texts).encode()).hexdigest()[:16]
        cache = self.dir / 'clip' / f'prompts-{key}.json'
        if cache.is_file():
            values = json.loads(cache.read_text())
        else:
            import onnxruntime as ort
            session = ort.InferenceSession(str(self.dir / 'clip/text_model_quantized.onnx'), providers=['CPUExecutionProvider'])
            tokenizer = ClipTokenizer(self.dir / 'clip')
            values = []
            for text in texts:
                vector = session.run(None, {'input_ids': np.array([tokenizer.encode(text)], np.int64)})[0][0]
                values.append((vector / np.linalg.norm(vector)).round(6).tolist())
            cache.write_text(json.dumps(values))
        matrix = np.array(values, dtype=np.float32)
        return matrix[:len(TAGS)], matrix[len(TAGS):]

    def analyze(self, path, original=None):
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError('Cannot decode image')
        height, width = image.shape[:2]
        moment, camera = taken_at(original if original and Path(original).is_file() else path)
        features = self.features
        with self.lock:
            raw = {'size': [width, height], 'taken_at': moment, 'camera': camera,
                   'features': sorted(k for k, v in features.items() if v)}
            small = _resize(image, 1024)
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            raw['sharp'] = round(float(cv2.Laplacian(gray, cv2.CV_64F).var()), 2)
            raw['exposure'] = {'mean': round(float(gray.mean()) / 255, 3), 'high': round(float((gray > 250).mean()), 4),
                               'low': round(float((gray < 5).mean()), 4)}
            raw['thumb'] = pack((cv2.resize(small, (16, 16), interpolation=cv2.INTER_AREA).astype(np.float32) / 255).ravel())
            raw['faces'] = self.faces(image, features['expressions']) if features['faces'] else []
            raw['bodies'] = self.bodies(image) if features['bodies'] else []
            raw['clip'] = self.scene(image) if features['scene'] else None
        return raw

    def faces(self, image, expressions):
        height, width = image.shape[:2]
        scaled = _resize(image, 2560)
        factor = width / scaled.shape[1]
        self.detector.setInputSize((scaled.shape[1], scaled.shape[0]))
        _, found = self.detector.detect(scaled)
        result = []
        for row in (found if found is not None else []):
            row = row.copy(); row[:14] *= factor
            x, y, w, h = (float(v) for v in row[:4])
            px = min(w, h)
            aligned = self.recognizer.alignCrop(image, row)
            face = {'box': [x / width, y / height, w / width, h / height],
                    'points': [[float(row[4 + 2 * i]) / width, float(row[5 + 2 * i]) / height] for i in range(5)],
                    'score': round(float(row[14]), 3), 'px': round(px, 1),
                    'sharp': _face_sharpness(image, x, y, w, h)}
            if px >= 24:
                vector = self.recognizer.feature(aligned).flatten().astype(np.float32)
                norm = float(np.linalg.norm(vector))
                face['embedding'] = pack(vector / norm) if np.isfinite(norm) and norm else None
            if expressions and px >= 24:
                face.update(self.expression(image, row))
            face['doubtful'] = face.get('presence', 99) < 0
            face['box'] = [round(v, 5) for v in face['box']]
            result.append(face)
        return result

    def expression(self, image, row):
        landmarks, blend = self.mesh
        x, y, w, h = (float(v) for v in row[:4])
        right, left = row[4:6], row[6:8]
        angle = math.degrees(math.atan2(left[1] - right[1], left[0] - right[0]))
        cx, cy, side = x + w / 2, y + h / 2, max(w, h) * 1.6
        matrix = cv2.getRotationMatrix2D((cx, cy), angle, 256 / side)
        matrix[0, 2] += 128 - cx; matrix[1, 2] += 128 - cy
        crop = cv2.warpAffine(image, matrix, (256, 256), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        blob = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB).astype(np.float32)[None] / 255
        landmarks.setInput(np.ascontiguousarray(blob.transpose(0, 3, 1, 2)))
        points, presence = None, None
        for out in landmarks.forward(landmarks.getUnconnectedOutLayersNames()):
            if out.size == 1434:
                points = out.reshape(478, 3)
            elif out.size == 1 and presence is None:
                presence = float(out.reshape(-1)[0])
        if points is None:
            return {}
        blend.setInput(np.ascontiguousarray(points[BLEND_SUBSET, :2][None].astype(np.float32)))
        shapes = blend.forward().reshape(-1)
        eye = np.linalg.norm(points[33, :2] - points[263, :2]) or 1
        nose = (points[1, 0] - (points[33, 0] + points[263, 0]) / 2) / eye
        # Negative when the head is tilted down: forehead nearer to the camera than the chin.
        pitch = (points[10, 2] - points[152, 2]) / (np.linalg.norm(points[10, :2] - points[152, :2]) or 1)
        return {'presence': round(presence, 2), 'blink': [round(float(shapes[BLINK_LEFT]), 3), round(float(shapes[BLINK_RIGHT]), 3)],
                'smile': round(float(shapes[SMILE_LEFT] + shapes[SMILE_RIGHT]) / 2, 3), 'yaw': round(float(nose), 3),
                'pitch': round(float(pitch), 3)}

    def bodies(self, image):
        height, width = image.shape[:2]
        ratio = min(640 / height, 640 / width)
        canvas = np.full((640, 640, 3), 114, np.uint8)
        resized = cv2.resize(image, (int(width * ratio), int(height * ratio)), interpolation=cv2.INTER_AREA)
        canvas[:resized.shape[0], :resized.shape[1]] = resized
        dets, keypoints = self.rtmo.run(None, {'input': canvas.transpose(2, 0, 1)[None].astype(np.float32)})
        result = []
        for det, kp in zip(dets[0], keypoints[0]):
            if det[4] < .35:
                continue
            x0, y0, x1, y1 = (float(v) / ratio for v in det[:4])
            x0, y0, x1, y1 = max(0, x0), max(0, y0), min(width, x1), min(height, y1)
            if x1 - x0 < 4 or y1 - y0 < 4:
                continue
            result.append({'box': [round(x0 / width, 5), round(y0 / height, 5), round((x1 - x0) / width, 5), round((y1 - y0) / height, 5)],
                           'score': round(float(det[4]), 3),
                           'keypoints': [[round(float(p[0]) / ratio / width, 4), round(float(p[1]) / ratio / height, 4), round(float(p[2]), 3)] for p in kp]})
        return result

    def scene(self, image):
        rgb = cv2.cvtColor(_resize(image, 640), cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        scale = 224 / min(h, w)
        rgb = cv2.resize(rgb, (max(224, round(w * scale)), max(224, round(h * scale))), interpolation=cv2.INTER_CUBIC)
        h, w = rgb.shape[:2]
        top, left = (h - 224) // 2, (w - 224) // 2
        pixels = ((rgb[top:top + 224, left:left + 224] / 255.0) - CLIP_MEAN) / CLIP_STD
        vector = self.clip.run(None, {'pixel_values': pixels.transpose(2, 0, 1)[None].astype(np.float32)})[0][0]
        vector = vector / np.linalg.norm(vector)
        tags, pairs = self.prompts
        logits = 100 * tags @ vector
        probs = np.exp(logits - logits.max()); probs /= probs.sum()
        result = {'embedding': pack(vector), 'tags': {k: round(float(p), 3) for k, p in zip(TAGS, probs)}}
        for index, key in enumerate(PAIRS):
            a, b = 100 * float(pairs[2 * index] @ vector), 100 * float(pairs[2 * index + 1] @ vector)
            result[key] = round(1 / (1 + math.exp(b - a)), 3)
        return result


def _face_sharpness(image, x, y, w, h):
    """Laplacian variance of the face at a fixed 64 px, never upscaled (small faces stay unknown)."""
    if min(w, h) < 64:
        return None
    x0, y0 = max(0, int(x + w * .15)), max(0, int(y + h * .1))
    crop = image[y0:int(y + h * .9), x0:int(x + w * .85)]
    if crop.size == 0:
        return None
    gray = cv2.cvtColor(cv2.resize(crop, (64, 64), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
    return round(float(cv2.Laplacian(gray, cv2.CV_64F).var()), 2)


def _resize(image, longest):
    height, width = image.shape[:2]
    scale = min(1.0, longest / max(height, width))
    if scale >= 1:
        return image
    return cv2.resize(image, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA)
