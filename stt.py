"""Moteur de transcription — Parakeet-tdt-0.6b-v3 via sherpa-onnx (CPU, offline)."""

import os
import tempfile
import time

import numpy as np
import sherpa_onnx


def _ensure_bpe_vocab(model_dir: str) -> str:
    """Fabrique un bpe.vocab depuis tokens.txt s'il n'existe pas.

    Le modèle exporté ne fournit pas le sentencepiece d'origine ; des scores
    uniformes négatifs donnent une segmentation « longest-match » qui colle à
    ce que le décodeur émet réellement (validé : biasing effectif sur fr.wav).
    """
    path = os.path.join(model_dir, "bpe_from_tokens.vocab")
    if not os.path.exists(path):
        with open(os.path.join(model_dir, "tokens.txt"), encoding="utf-8") as f, open(
            path, "w", encoding="utf-8"
        ) as out:
            for line in f:
                piece = line.rstrip("\n").split()
                if piece and not piece[0].startswith("<"):  # saute <blk>, <unk>…
                    out.write(f"{piece[0]}\t-1.0\n")
    return path


class Transcriber:
    def __init__(
        self,
        model_dir: str,
        num_threads: int = 4,
        sample_rate: int = 16000,
        vocab: list[str] | None = None,
        vocab_score: float = 2.0,
    ):
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

        kw = dict(
            encoder=pick("encoder"),
            decoder=pick("decoder"),
            joiner=pick("joiner"),
            tokens=os.path.join(base, "tokens.txt"),
            num_threads=num_threads,
            sample_rate=sample_rate,
            feature_dim=80,
            model_type="nemo_transducer",
        )

        # Vocabulaire custom → biasing du décodeur (nécessite le beam search).
        # Sans vocab : greedy, plus rapide.
        self.boosted = len(vocab) if vocab else 0
        if vocab:
            tmp = tempfile.NamedTemporaryFile(
                "w", suffix=".txt", delete=False, encoding="utf-8"
            )
            tmp.write("\n".join(vocab) + "\n")
            tmp.close()
            kw.update(
                decoding_method="modified_beam_search",
                hotwords_file=tmp.name,
                hotwords_score=vocab_score,
                modeling_unit="bpe",
                bpe_vocab=_ensure_bpe_vocab(base),
            )

        t0 = time.perf_counter()
        self.recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(**kw)
        self.load_time = time.perf_counter() - t0

    def transcribe(self, samples: np.ndarray) -> str:
        """samples : float32 mono à self.sample_rate, valeurs dans [-1, 1]."""
        stream = self.recognizer.create_stream()
        stream.accept_waveform(self.sample_rate, samples)
        self.recognizer.decode_stream(stream)
        return stream.result.text.strip()
