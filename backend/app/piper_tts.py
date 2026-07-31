"""Local, offline text-to-speech via Piper (github.com/OHF-Voice/piper1-gpl).

Confirmed decision (2026-07-28): Joshua wanted "forever free, no payment"
for Frank's voice, which cloud TTS (ElevenLabs, app/main.py's earlier
`/speak` implementation) can't actually offer -- their free tier explicitly
blocks API access to Voice Library voices, restricting free usage to
voices you already own. Piper is genuinely free forever (MIT license, no
account, no API key, no per-request cost) and runs fully offline as part
of this same embedded Python backend -- consistent with everything else
in this project defaulting to local-first. Real, named trade-off: Piper
is a clear step up from Apple's on-device voices, but doesn't match
ElevenLabs' expressive, stylized character voices (e.g. "dark and tough")
-- that gap is inherent to what a free local model can do today, not a
configuration problem to fix.

The voice model (en_US-ryan-high, one of Piper's better-quality US male
voices) is downloaded once into data/piper_voices/ and loaded lazily on
first use -- not at import time, so importing this module doesn't require
the model to already be present.
"""

import io
import wave
from pathlib import Path

from piper import PiperVoice

VOICE_DIR = Path(__file__).parent.parent / "data" / "piper_voices"
MODEL_PATH = VOICE_DIR / "en_US-ryan-high.onnx"

_voice: PiperVoice | None = None


def _get_voice() -> PiperVoice:
    global _voice
    if _voice is None:
        _voice = PiperVoice.load(MODEL_PATH)
    return _voice


def synthesize_wav_bytes(text: str) -> bytes:
    """Renders `text` to a complete in-memory WAV file -- simplest form
    Piper offers (`synthesize_wav` writes directly into a `wave.Wave_write`),
    and WAV needs no separate decode step on the Swift side (`AVAudioPlayer`
    reads it directly, same as it already does for ElevenLabs' MP3)."""
    voice = _get_voice()
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        voice.synthesize_wav(text, wav_file)
    return buffer.getvalue()
