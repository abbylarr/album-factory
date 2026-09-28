"""Download the local vision models into models/ and verify their SHA-256.

    python scripts/fetch_models.py            # missing files only
    python scripts/fetch_models.py --check    # verify what is present, download nothing

Every model runs offline; photographs never leave the machine. Licences:
YuNet, SFace (OpenCV Zoo, Apache 2.0 / MIT), RTMO-s (OpenMMLab, Apache 2.0),
MediaPipe Face Landmarker (Google, Apache 2.0), CLIP ViT-B/32 (OpenAI, MIT;
quantised ONNX export by Xenova).
"""
from __future__ import annotations

import argparse
import hashlib
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

MODELS = Path(__file__).resolve().parents[1] / 'models'
ZOO = 'https://github.com/opencv/opencv_zoo/raw/main/models/'
CLIP = 'https://huggingface.co/Xenova/clip-vit-base-patch32/resolve/main/'
FILES = [
    ('yunet.onnx', ZOO + 'face_detection_yunet/face_detection_yunet_2023mar.onnx', None,
     '8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4'),
    ('sface.onnx', ZOO + 'face_recognition_sface/face_recognition_sface_2021dec.onnx', None,
     '0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79'),
    ('rtmo-s.onnx', 'https://download.openmmlab.com/mmpose/v1/projects/rtmo/onnx_sdk/rtmo-s_8xb32-600e_body7-640x640-dac2bf74_20231211.zip',
     'end2end.onnx', 'd0703d40d19f3921da51ae725402d5fdae4d2478c7442072d3101bd396f370d8'),
    ('face_landmarker.task', 'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task', None,
     '64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff'),
    ('clip/vision_model_quantized.onnx', CLIP + 'onnx/vision_model_quantized.onnx', None,
     '583fd1110a514667812fee7d684952aaf82a99b959760c8d7dca7e0ab9839299'),
    ('clip/text_model_quantized.onnx', CLIP + 'onnx/text_model_quantized.onnx', None,
     '73baab855d406190da9faa498cfedf65f15cf309f4cc7385b7b032e6d08e5c3a'),
    ('clip/vocab.json', CLIP + 'vocab.json', None, '5047b556ce86ccaf6aa22b3ffccfc52d391ea4accdab9c2f2407da5b742d4363'),
    ('clip/merges.txt', CLIP + 'merges.txt', None, '9fd691f7c8039210e0fced15865466c65820d09b63988b0174bfe25de299051a'),
]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--check', action='store_true', help='only verify files that are present')
    args = parser.parse_args()
    failed = False
    for name, url, member, expected in FILES:
        target = MODELS / name
        if target.is_file():
            ok = digest(target.read_bytes()) == expected
            print(f'{"ok " if ok else "BAD"} {name}')
            failed |= not ok
            continue
        if args.check:
            print(f'--  {name} (missing)')
            continue
        print(f'... {name} ← {url}', flush=True)
        with urllib.request.urlopen(url, timeout=120) as response:
            data = response.read()
        if member:
            with zipfile.ZipFile(io.BytesIO(data)) as bundle:
                data = bundle.read(member)
        if digest(data) != expected:
            print(f'BAD {name}: checksum mismatch, file not saved')
            failed = True
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        print(f'ok  {name}')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
