# Design notes => AI Written # TODO For Human: rewrite and refine

Design rationale and decisions behind the Restaurant Voice Agent, companion to the milestone roadmap in `PROJECT.md`.

### Audio source and sink as adapters

Milestone 1 starts with a local mic (desktop/browser). Later the plan is to listen on a real phone line instead. To make that swap easy, capture and playback should be built as adapters from the start, not hardcoded to the mic/speaker.

Local mic and phone audio differ in a few ways that the adapter needs to absorb, not leak into the rest of the pipeline.

Pull vs push: a local mic is something you ask for audio from, you decide when to start and stop recording. A phone call pushes audio at you continuously from the moment it connects. There is no hold-to-talk on a phone line.

Format: desktop/browser audio is typically 16kHz. Telephony is almost always 8kHz mulaw, arriving as small base64 chunks over a websocket, not a WAV file. Resampling and decoding should happen at the edge of the adapter, so everything downstream only ever sees one canonical format.

Utterance boundaries: push-to-talk works for the desktop prototype but has no equivalent on a phone call. That means the phone adapter cannot ship without VAD (milestone 3), even though the mic adapter can get away without it in milestone 1. The mic shortcut should not be assumed to carry forward.

Playback: output is "write to the speaker" locally, but "stream audio chunks back over the call" for telephony. The sink side needs the same adapter treatment as the source side.

Practical shape: define two small roles, an audio source and an audio sink, both speaking one fixed internal format. STT, the agent, and TTS only ever see that canonical format and never know whether it came from a mic or a phone line. Frame the source interface as "here is a stream of audio, here is when an utterance ended" rather than "block until the user stops talking," even though milestone 1 implements it the simple way. That framing is what lets the milestone 3 VAD work slot in later instead of forcing a rewrite.

### Codec decode vs sample rate, and why 16kHz is the canonical rate

Each future backend (Twilio, Asterisk/SIP, WhatsApp, Linphone) bundles two separate problems that are worth not conflating. First, codec decoding: most of these hand over compressed audio, not raw PCM. Phone legs typically use G.711 (mulaw/alaw), SIP can negotiate G.722, WhatsApp uses Opus. That has to be decoded to linear PCM first. Second, sample rate conversion: phone audio is 8kHz (narrowband), desktop/browser mics and most STT/TTS models are 16kHz (wideband). Each source/sink adapter owns both steps at its own edge; nothing downstream ever sees a codec or a rate other than the canonical one.

Upsampling (8kHz to 16kHz, phone audio coming in) and downsampling (16kHz to 8kHz, TTS audio going out to a phone) are not symmetric. Upsampling is interpolation, like enlarging a low-res image: it does not recover anything, but it does not destroy anything either, because the real loss already happened upstream when the phone network band-limited the signal to roughly 300-3400Hz and the codec compressed its amplitude resolution. Downsampling is the opposite: it is genuinely lossy, a proper resampler has to low-pass filter before discarding samples to avoid aliasing, and that permanently cuts the 3.4kHz-8kHz range that a 16kHz TTS output actually contains. If that audio needs to be kept for logging or analysis, keep the original 16kHz copy, not just the downsampled one.

This asymmetry is also why the canonical rate should be 16kHz, not 8kHz. The mic path (milestones 1-2, the one being built and tested first) captures real 16kHz audio with no inherent ceiling, and TTS output is generated at 16kHz or higher for naturalness. Making 8kHz canonical would force a lossy downsample onto that path for no benefit. A phone call, on the other hand, is physically limited to about 3.4kHz of real content no matter what: upsampling it to 16kHz on the way in costs nothing extra (lossless, per above), and the eventual downsample back to 8kHz on the way out is unavoidable regardless of the canonical choice, since the phone line cannot carry more than 8kHz either way. So 16kHz as canonical relocates no loss onto a path that previously had none, while 8kHz as canonical would. This could be revisited if phone traffic ever becomes the dominant channel and the mic becomes a minor/dev-only path, purely as a CPU-cost tradeoff, not a quality one.

### Stack and sequencing

Backend is Python with FastAPI. The ecosystem fits every piece of the roadmap: STT/TTS/LLM SDKs, Silero-VAD/webrtcvad for milestone 3, and asyncio tasks with native cancellation for milestone 4. Async generators, already named as a milestone 2 learning goal, are a native Python concept, so the stack follows the roadmap rather than the other way around.

Milestone 1 starts as a desktop app with direct mic access, no server at all. A server only gets introduced when the browser input is added, since a browser client needs a backend to avoid exposing API keys and to serve the page. The same server will later also host the websocket endpoint a phone adapter (Twilio Media Streams, Asterisk ARI) needs to receive and send call audio, so it does not get built twice.

### Agent tool-call loop

The agent is not the LLM. The LLM only predicts one step at a time, a final answer or a request to call a specific tool with specific arguments, it has no memory and cannot execute anything itself. The agent is the surrounding loop: it holds conversation history, calls the LLM, executes whatever tool the LLM asks for, feeds the real result back, and decides when the turn is done. Swapping LLM providers changes only which `LLMAdapter` the agent holds, not the agent loop itself.

There are two nested loops. The outer one is per-utterance: record, transcribe, call the agent once, speak the result, repeat. The inner one lives inside a single agent call and may bounce off the LLM more than once before producing an answer worth speaking.

The inner loop: append the user's message to history, call the model. If the response is final text, append it to history and return it. If it is a tool call request, look the tool up in the registry, validate its arguments, run it, append both the call and its result to history, and call the LLM again with the updated history. Repeat until final text comes back.

Validation and execution failures (bad arguments, or the tool itself raising, e.g. a backend being down) are both fed back into history as the tool's result, rather than crashing the turn, so the model can see the failure and try to self-correct. The stop condition for the loop is not a flat iteration cap, it is a consecutive-failure counter that resets on any success: an isolated failure followed by a success is normal, but several failures in a row with no success between them means the model is stuck, and the loop bails out with a fallback response instead of looping forever or letting a long, legitimate multi-step success (several tool calls, no failures) hit an arbitrary limit.

A model response can request more than one tool call at once (parallel), and the agent runs every one of them, not just the first, a round only counts as a failure for the consecutive-failure counter if every call in it failed; one success anywhere in the batch counts as progress and resets the counter.

### Mic capture

Mic capture on desktop uses `sounddevice` (NumPy-native, more reliable cross-platform installs than `PyAudio`). It offers three tiers: simple convenience functions (`sd.rec()`/`sd.play()`) for quick scripts, blocking read/write streams where the calling thread blocks on each `.read()`/`.write()` call, and callback-based streams where PortAudio calls your function from a background thread.

Milestone 1 uses the blocking read/write stream tier: the whole milestone is explicitly synchronous (record, transcribe, call the LLM, synthesize, play, one step after another), there is no server or event loop yet, so blocking the calling thread during `.read()` costs nothing. This stops being the right tool once milestone 3 (continuous capture alongside VAD) and milestone 4 (interruption/cancellation) move this code inside the FastAPI/asyncio server, where a blocking call would stall the event loop. At that point the source adapter swaps internally to the callback-based stream, pushing frames into an async queue, without changing its external interface (canonical-format audio, utterance-end signal).

### Why `record()` returns raw bytes, not a NumPy array

`record()` hands back raw `bytes`, not a NumPy array, and that is deliberate: every consumer needs a different in-memory representation anyway, so there is no single array dtype that would save work for all of them. Whisper needs `float32` normalized to -1.0..1.0 (its model was trained on that range, not a format choice, a hard requirement of the model). Playback needs `int16` to match the canonical format. A future phone adapter needs actual bytes to send over a websocket, a NumPy array cannot go on the wire without calling `.tobytes()` on it first anyway. Picking any one dtype to return would only save a step for the one consumer that happens to want it, and cost a step for every other one. Bytes is the one representation that is neutral to all of them, and it matches the canonical format being defined as a wire format in the first place (16kHz mono int16 PCM), not an in-memory Python type.

This is also why `audio.py`'s capture loop is built on `sd.RawInputStream` instead of the array-based `sd.InputStream`: it avoids needing NumPy in the capture path at all, since nothing in capturing itself needs array math, only the consumers (STT, eventually playback-side processing) do. Converting bytes to a NumPy array (`np.frombuffer`) is one line whenever a consumer actually needs it, so nothing is lost by not doing that conversion upfront inside `record()` itself.

### Text to speech: Piper, not the generically "most common" option

The Python TTS landscape splits into three tiers. `pyttsx3` wraps the OS's native speech engine (SAPI on Windows, espeak on Linux), fully offline and dead simple, but on Linux that's espeak's voice underneath, robotic and dated, not something a restaurant customer should hear. Coqui/Bark-style deep models give much better voice quality but are heavy and slow (multi-second generation per sentence), a poor fit for a voice agent where latency is the whole game, per milestone 5. Piper is the one actually built for this use case: it's the TTS engine behind Home Assistant Voice and most of the open-source local voice-assistant stack, ONNX-based, fast enough for real-time on CPU, and ships real multilingual voices including Portuguese.

Checking the actual voices (GitHub's VOICES.md): Brazilian Portuguese has cadu, edresson, faber, jeff, all medium quality except edresson, which is low. That matters here: Piper's low tier outputs 16kHz, matching the canonical rate exactly, so no resampling adapter is needed yet, same "don't build it before a second case forces it" call as the mic/phone discussion. `pt_BR-edresson-low` is the pick for that reason, not because it's the best-sounding option.
