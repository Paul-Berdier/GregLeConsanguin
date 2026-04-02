# utils/ffmpeg.py
from __future__ import annotations
import os

CANDIDATES = [
    "/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/bin/ffmpeg",
    "ffmpeg", r"D:\Paul Berdier\ffmpeg\bin\ffmpeg.exe"
]

def detect_ffmpeg() -> str:
    for p in CANDIDATES:
        try:
            if p == "ffmpeg":
                continue
            if os.path.exists(p) and os.access(p, os.X_OK):
                return p
        except Exception:
            pass
    return "ffmpeg"
