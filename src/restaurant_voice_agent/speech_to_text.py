from abc import ABC, abstractmethod

import numpy as np
from faster_whisper import WhisperModel


class STTAdapter(ABC):
    @abstractmethod
    def transcribe(self, audio_buffer: bytes, language: str) -> str:
        ...


class STTWhisper(STTAdapter):
    def __init__(self):
        self.model = WhisperModel(
            # "large-v3", #
            "small",
            device="cpu",       # use "cuda" if you have an NVIDIA GPU
            compute_type="int16",  # use "float16" on CUDA for better speed
        )

    def transcribe(self, audio_buffer: bytes, language: str) -> str:
        samples = np.frombuffer(audio_buffer, dtype=np.int16).astype(np.float32) / 32768.0

        segments, info = self.model.transcribe(
            samples,
            beam_size=5,
            language=language,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
        )

        print(f"Detected language: {info.language} ({info.language_probability:.2f})")
        return "".join(segment.text for segment in segments).strip()
