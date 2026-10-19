from abc import ABC, abstractmethod

from piper import PiperVoice
from soxr import np, resample

from restaurant_voice_agent.constants import CANONICAL_SAMPLE_RATE


class TTSAdapter(ABC):
    @abstractmethod
    def synthesize(self, text: str) -> bytes:
        ...


class TTSPiper(TTSAdapter):
    def __init__(self, model_path: str = "pt_BR-jeff-medium.onnx"):
        self.voice = PiperVoice.load(model_path)

    def synthesize(self, text: str) -> bytes:
        raw = b"".join(chunk.audio_int16_bytes for chunk in self.voice.synthesize(text))
        samples = np.frombuffer(raw, dtype=np.int16)
        return resample(
            samples,
            self.voice.config.sample_rate,
            CANONICAL_SAMPLE_RATE
        ).tobytes()
