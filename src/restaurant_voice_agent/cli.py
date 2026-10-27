from time import time

from restaurant_voice_agent.agent import Agent, LLMOllama
from restaurant_voice_agent.audio import CHANNELS, play, record
from restaurant_voice_agent.constants import CANONICAL_SAMPLE_RATE
from restaurant_voice_agent.speech_to_text import STTWhisper
from restaurant_voice_agent.text_to_speech import TTSPiper
from restaurant_voice_agent.tools import TOOLS


def main() -> None:
    print("Initializing models")
    stt_model = STTWhisper()
    agent = Agent(LLMOllama(), TOOLS)
    tts_model = TTSPiper()

    play(
        tts_model.synthesize("Olá, Sou o Léo. O que posso fazer por você?")
    )

    while True:
        input("Press Enter to start recording an utterance...")
        audio = record()
        start = time()
        transcript = stt_model.transcribe(audio, "pt")

        bytes_per_sample = 2  # int16
        frame_count = len(audio) // (bytes_per_sample * CHANNELS)
        duration = frame_count / CANONICAL_SAMPLE_RATE
        print("Transcription:", (mid1 := time()) - start)
        print(f"Captured {frame_count} frames ({duration:.2f}s) at {CANONICAL_SAMPLE_RATE}Hz mono int16.")
        print(transcript)
        print("Before response: ", (mid3 := time()) - mid1)
        for reply in agent.run(transcript):
            print(reply)
            play(tts_model.synthesize(reply))

        print("Response took:", time() - mid3)
