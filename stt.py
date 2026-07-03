"""Moteur de transcription — Parakeet-tdt-0.6b-v3 via sherpa-onnx (CPU, offline)."""

import os
import time

import numpy as np
import sherpa_onnx


class Transcriber:
    def __init__(self, model_dir: str, num_threads: int = 4, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        base = os.path.abspath(model_dir)

        def pick(name: str) -> str:
            """Prend la variante int8 si présente, sinon fp32."""
            int8 = os.path.join(base, f"{name}.int8.onnx")
            fp32 = os.path.join(base, f"{name}.onnx")
            if os.path.exists(int8):
                return int8
            if os.path.exists(fp32):
                return fp32
            raise FileNotFoundError(f"Modèle introuvable : {int8}")

        t0 = time.perf_counter()
        self.recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=pick("encoder"),
            decoder=pick("decoder"),
            joiner=pick("joiner"),
            tokens=os.path.join(base, "tokens.txt"),
            num_threads=num_threads,
            sample_rate=sample_rate,
            feature_dim=80,
            model_type="nemo_transducer",
        )
        self.load_time = time.perf_counter() - t0

    def transcribe(self, samples: np.ndarray) -> str:
        """samples : float32 mono à self.sample_rate, valeurs dans [-1, 1]."""
        stream = self.recognizer.create_stream()
        stream.accept_waveform(self.sample_rate, samples)
        self.recognizer.decode_stream(stream)
        return stream.result.text.strip()
