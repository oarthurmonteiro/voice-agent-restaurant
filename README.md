# Voice Agent Restaurant

Local voice assistant for a restaurant: speech to text, an LLM agent with tools, text to speech.

## Requirements

- Python 3.13
- [uv](https://docs.astral.sh/uv/)
- PortAudio (audio capture/playback)
- [Ollama](https://ollama.com), running locally

## Setup

Install PortAudio, needed by `sounddevice`:

- **Linux (Debian/Ubuntu)**: `sudo apt install libportaudio2` (Fedora: `portaudio`, Arch: `portaudio`)
- **macOS**: bundled with the `sounddevice` wheel, nothing to install. If missing: `brew install portaudio`
- **Windows**: bundled with the `sounddevice` wheel, nothing to install

Install Ollama and pull the model:

```sh
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2
```

Install the Python dependencies:

```sh
uv sync
```

Download a Portuguese (pt_BR) Piper voice. The default is `pt_BR-jeff-medium`:

```sh
uv run python -m piper.download_voices pt_BR-jeff-medium
```

This saves `pt_BR-jeff-medium.onnx` and `pt_BR-jeff-medium.onnx.json` in the current directory.

## Run

```sh
uv run -m main
```

Press Enter to start recording, speak, press Enter to stop.
