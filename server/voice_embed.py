# -*- coding: utf-8 -*-
r"""voice_embed.py -- audio reading, Silero voice activity and speaker voice vectors (sherpa-onnx, CPU).

The model files are downloaded by the installer into %LOCALAPPDATA%\Shema\models (paths.MODELS).
"""
import shutil, subprocess
from pathlib import Path

import numpy as np
import sherpa_onnx

from paths import MODELS as MODELS_DIR

MODELS = {
    "eres2netv2": "3dspeaker_speech_eres2netv2_sv_zh-cn_16k-common.onnx",
    "titanet": "nemo_en_titanet_large.onnx",
}
SR = 16000


def ffmpeg():
    hit = shutil.which("ffmpeg")
    if hit:
        return hit
    found = sorted((Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Packages").glob(
        "Gyan.FFmpeg*/*/bin/ffmpeg.exe"))
    return str(found[-1]) if found else "ffmpeg"


FF = ffmpeg()


def read_audio(path, max_s=150):
    a = subprocess.run([FF, "-v", "error", "-t", str(max_s), "-i", str(path), "-vn", "-ac", "1", "-ar", str(SR),
                        "-f", "s16le", "-"], capture_output=True, creationflags=0x08000000).stdout
    return np.frombuffer(a, np.int16).astype(np.float32) / 32768.0 if a else None


def make_vad():
    cfg = sherpa_onnx.VadModelConfig()
    cfg.silero_vad.model = str(MODELS_DIR / "silero_vad.onnx")
    cfg.silero_vad.min_silence_duration = 0.2
    cfg.silero_vad.min_speech_duration = 0.2
    cfg.silero_vad.threshold = 0.5
    cfg.sample_rate = SR
    return cfg


def voiced_mask(cfg, audio):
    vad = sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=max(30, len(audio) / SR + 5))
    mask = np.zeros(len(audio), bool)
    win = cfg.silero_vad.window_size
    for i in range(0, len(audio), win):
        vad.accept_waveform(audio[i:i + win])
        while not vad.empty():
            s = vad.front
            mask[s.start:s.start + len(s.samples)] = True
            vad.pop()
    vad.flush()
    while not vad.empty():
        s = vad.front
        mask[s.start:s.start + len(s.samples)] = True
        vad.pop()
    return mask


def load_extractors(names=None):
    ex = {}
    for k, fn in MODELS.items():
        if names and k not in names:
            continue
        c = sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(MODELS_DIR / fn), num_threads=4, provider="cpu")
        ex[k] = sherpa_onnx.SpeakerEmbeddingExtractor(c)
    return ex


def embed(ex, wave):
    st = ex.create_stream()
    st.accept_waveform(sample_rate=SR, waveform=wave)
    st.input_finished()
    e = np.asarray(ex.compute(st), np.float32)
    return e / (np.linalg.norm(e) + 1e-9)
