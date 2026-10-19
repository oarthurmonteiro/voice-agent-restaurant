import sys
import threading

import sounddevice as sd

from restaurant_voice_agent.constants import CANONICAL_SAMPLE_RATE

CHANNELS = 1
CHUNK_DURATION = 0.1  # seconds per read; small enough to check the stop flag often
CHUNK_FRAMES = int(CANONICAL_SAMPLE_RATE * CHUNK_DURATION)

def _wait_for_enter(stop_event: threading.Event) -> None:
    """Runs on its own thread so it can wait for input while the main
    thread is busy blocking on stream.read()."""
    input()
    stop_event.set()


def record() -> bytes:
    stop_event = threading.Event()
    listener = threading.Thread(target=_wait_for_enter, args=(stop_event,), daemon=True)

    chunks: list[bytes] = []
    with sd.RawInputStream(samplerate=CANONICAL_SAMPLE_RATE, channels=CHANNELS, dtype="int16") as stream:
        listener.start()
        while not stop_event.is_set():
            data, overflowed = stream.read(CHUNK_FRAMES)
            if overflowed:
                print("warning: input overflowed, some audio was dropped", file=sys.stderr)
            chunks.append(bytes(data))

    return b"".join(chunks)

def play(audio: bytes) -> None:
    with sd.RawOutputStream(samplerate=CANONICAL_SAMPLE_RATE, channels=CHANNELS, dtype="int16") as stream:
        stream.write(audio)
