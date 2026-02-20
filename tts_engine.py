"""TTS engine for EchoPilot — edge-tts primary, pyttsx3 offline fallback."""

from __future__ import annotations

import asyncio
import os
import tempfile

from pydub import AudioSegment

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

TONES = ["Normal", "Upbeat", "Angry", "Excited"]

# (speed_factor, volume_dB) for each tone preset
_TONE_PARAMS = {
    "Normal":  (1.00,  0),
    "Upbeat":  (1.10, +2),
    "Angry":   (0.95, +4),
    "Excited": (1.15, +3),
}


class TTSEngine:
    def __init__(self):
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        self._xtts = None         # Coqui XTTS v2 instance, loaded on demand
        self._chatterbox = None   # ChatterboxTTS instance, loaded on demand
        self._last_backend: str = "edge-tts"    # updated after each generate()
        self._last_clone_errors: list = []      # errors from failed clone attempts

    # ── Public API ───────────────────────────────────────────────────────────

    def generate(self, text: str, voice_short_name: str,
                 tone: str = "Normal", mood: int = 5,
                 output_path: str = None,
                 reference_audio: str = None,
                 language: str = "en") -> str:
        """
        Synthesise *text* using *voice_short_name* (edge-tts voice ID).

        When *reference_audio* is a valid file path, voice cloning is attempted:

        1. **ChatterboxTTS** — zero-shot cloning, **English only**, Python 3.10–3.11
           (numpy 1.24–1.25 has no pre-built wheels for Python 3.12+).
           Skipped automatically for non-English languages.
        2. **Coqui XTTS v2** — zero-shot cloning, multilingual (16 languages),
           Python 3.9–3.11 only, ~2 GB model.
        3. **edge-tts** — neural TTS without cloning (fallback).
        4. **pyttsx3** — offline system TTS (last resort).

        After generation ``self._last_backend`` names the backend that produced
        the audio.  ``self._last_clone_errors`` lists any errors that caused
        cloning to fall back, so the UI can surface them to the user.

        :param tone:            One of TONES; applies speed/volume post-processing.
        :param mood:            1–10 scale; 5 is neutral (no extra effect).
        :param reference_audio: Path to a WAV/MP3 reference recording (≥ 5 s recommended).
        :param language:        2-letter BCP-47 code (e.g. ``'en'``, ``'fr'``).
        :returns: Path to the generated WAV file.
        """
        if output_path is None:
            fd, output_path = tempfile.mkstemp(suffix=".wav", dir=OUTPUT_DIR)
            os.close(fd)

        self._last_clone_errors = []

        # Normalise language to a 2-letter code for comparisons below
        lang_2 = (language or "en").lower().split("-")[0]

        # 1. Try Chatterbox voice cloning — English only (PerthNet architecture,
        #    trained on English corpus only; non-English text produces wrong language).
        #    Skipped automatically when lang_2 != "en".
        if reference_audio and os.path.isfile(reference_audio) and lang_2 == "en":
            try:
                self._generate_chatterbox(text, reference_audio, output_path)
                self._last_backend = "chatterbox"
                if tone != "Normal" or mood != 5:
                    self._apply_tone_mood(output_path, tone, mood)
                return output_path
            except ImportError as exc:
                self._last_clone_errors.append(f"ChatterboxTTS not installed: {exc}")
            except Exception as exc:
                self._last_clone_errors.append(f"ChatterboxTTS error: {exc}")

        # 2. Try Coqui XTTS v2 — multilingual (Python 3.9–3.11 only)
        if reference_audio and os.path.isfile(reference_audio):
            try:
                self._generate_xtts(text, reference_audio, lang_2, output_path)
                self._last_backend = "xtts"
                if tone != "Normal" or mood != 5:
                    self._apply_tone_mood(output_path, tone, mood)
                return output_path
            except ImportError as exc:
                self._last_clone_errors.append(f"XTTS v2 not installed: {exc}")
            except Exception as exc:
                self._last_clone_errors.append(f"XTTS v2 error: {exc}")

        # 3. edge-tts (primary neural voices)
        try:
            self._generate_edge(text, voice_short_name, output_path)
            self._last_backend = "edge-tts"
        except Exception as edge_err:
            # 4. pyttsx3 offline fallback
            try:
                self._generate_pyttsx3(text, output_path)
                self._last_backend = "pyttsx3"
            except Exception as tts_err:
                raise RuntimeError(
                    f"edge-tts failed ({edge_err}); offline fallback also failed ({tts_err})"
                ) from tts_err

        if tone != "Normal" or mood != 5:
            self._apply_tone_mood(output_path, tone, mood)

        return output_path

    def trim_audio(self, audio_path: str, start_ms: int, end_ms: int) -> str:
        """Trim *audio_path* to [start_ms, end_ms] in place."""
        audio = AudioSegment.from_file(audio_path)
        audio[int(start_ms):int(end_ms)].export(audio_path, format="wav")
        return audio_path

    def save_as(self, audio_path: str, output_path: str, fmt: str = "wav") -> str:
        """
        Export audio to *output_path*.

        :param fmt: ``'wav'`` → 44100 Hz, 16-bit mono  |  ``'mp3'`` → 192 kbps
        """
        audio = AudioSegment.from_file(audio_path)
        if fmt == "wav":
            audio = audio.set_frame_rate(44100).set_sample_width(2).set_channels(1)
            audio.export(output_path, format="wav")
        else:
            audio.export(output_path, format="mp3", bitrate="192k")
        return output_path

    def get_duration_ms(self, audio_path: str) -> int:
        """Return duration of *audio_path* in milliseconds."""
        return len(AudioSegment.from_file(audio_path))

    @staticmethod
    def cloning_backend() -> str | None:
        """Return the name of the first available voice-cloning backend, or None.

        Probes import availability without loading model weights.

        :returns: ``"chatterbox"``, ``"xtts"``, or ``None`` if neither is installed.
        """
        try:
            import chatterbox.tts  # noqa: F401
            return "chatterbox"
        except ImportError:
            pass
        try:
            import TTS  # noqa: F401
            return "xtts"
        except ImportError:
            pass
        return None

    @staticmethod
    def cloning_install_instructions() -> str:
        """Return a user-facing string with install instructions for voice cloning."""
        import sys
        py = sys.version_info
        if py >= (3, 12):
            return (
                f"Voice cloning is not available on Python {py.major}.{py.minor}.\n\n"
                "Re-run setup.bat — it will automatically install Python 3.11,\n"
                "create a virtual environment, and install both cloning engines:\n"
                "  • Chatterbox TTS  (English cloning,  ~400 MB model)\n"
                "  • Coqui XTTS v2   (pt-BR / fr / es / zh / …, ~2 GB model)\n\n"
                "The app works now with 400+ Microsoft Edge TTS neural voices.\n"
                "Voice cloning (sounds like the reference speaker) needs Python 3.11."
            )
        return (
            "Re-run setup.bat to install the voice cloning engines:\n\n"
            "  • Chatterbox TTS  — English cloning (~400 MB, downloaded on first use)\n"
            "  • Coqui XTTS v2   — multilingual cloning: pt-BR, fr, es, zh, …\n"
            "                       (~2 GB model, downloaded on first use)\n\n"
            "setup.bat handles everything automatically."
        )

    def apply_tone_mood(self, audio_path: str, tone: str, mood: int) -> str:
        """
        Apply *tone* preset and *mood* (1–10) to *audio_path* in place.

        Identical to the post-processing step in :meth:`generate`.
        This public method allows external callers (e.g. the Edit tab) to
        apply tweaks to an already-synthesised file without re-generating.

        :returns: *audio_path* (unchanged path, file is modified in place).
        """
        if tone != "Normal" or mood != 5:
            self._apply_tone_mood(audio_path, tone, mood)
        return audio_path

    # ── Backends ─────────────────────────────────────────────────────────────

    # ── Chatterbox TTS (primary cloning backend, Python 3.10+) ───────────────

    def _get_chatterbox(self):
        """Lazy-load and cache the ChatterboxTTS model.

        Downloads ~400 MB from HuggingFace on first use.
        Raises ``ImportError`` if the ``chatterbox-tts`` package is not installed.
        """
        if self._chatterbox is None:
            from chatterbox.tts import ChatterboxTTS  # noqa: PLC0415
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
            self._chatterbox = ChatterboxTTS.from_pretrained(device=device)
        return self._chatterbox

    def _generate_chatterbox(self, text: str, reference_audio: str, output_path: str):
        """Clone the voice in *reference_audio* and synthesise *text* via Chatterbox.

        **English only** — PerthNet (the underlying architecture) was trained on an
        English corpus and cannot produce correct speech in other languages.
        The caller (``generate``) skips this backend when ``language != "en"``.

        ChatterboxTTS supports Python 3.10–3.11.  On Python 3.12+ the required
        numpy 1.24–1.25 wheels are unavailable, so this path raises ImportError
        and the caller falls through to XTTS v2 or edge-tts.

        :raises ImportError: if the ``chatterbox-tts`` package is not installed.
        """
        import soundfile as sf  # noqa: PLC0415

        tts = self._get_chatterbox()
        wav = tts.generate(text, audio_prompt_path=reference_audio)
        sf.write(output_path, wav.squeeze().numpy(), tts.sr)

    # ── XTTS v2 (secondary cloning backend, Python 3.9–3.11 only) ────────────

    # Language codes accepted by XTTS v2
    _XTTS_LANGUAGES = {
        "en", "es", "fr", "de", "it", "pt", "pl", "tr",
        "ru", "nl", "cs", "ar", "zh-cn", "ja", "hu", "ko",
    }

    def _get_xtts(self):
        """Lazy-load and cache the Coqui XTTS v2 model.

        Downloads ~2 GB on first use (stored in the user's TTS model cache).
        Raises ``ImportError`` if the ``TTS`` package is not installed.
        """
        if self._xtts is None:
            from TTS.api import TTS as CoquiTTS  # noqa: PLC0415
            self._xtts = CoquiTTS("tts_models/multilingual/multi-dataset/xtts_v2")
        return self._xtts

    def _generate_xtts(self, text: str, reference_audio: str,
                       language: str, output_path: str):
        """Clone the voice in *reference_audio* and synthesise *text*.

        Uses Coqui XTTS v2 for zero-shot cross-lingual voice cloning.
        The reference recording should be 3–30 s of clean speech.

        :raises ImportError: if the ``TTS`` package is not installed.
        """
        lang = language.lower()
        # Normalise Chinese variants to XTTS's expected code
        if lang.startswith("zh"):
            lang = "zh-cn"
        if lang not in self._XTTS_LANGUAGES:
            lang = "en"  # safe fallback

        tts = self._get_xtts()
        tts.tts_to_file(
            text=text,
            speaker_wav=reference_audio,
            language=lang,
            file_path=output_path,
        )

    def _generate_edge(self, text: str, voice: str, output_path: str):
        """Synthesise with edge-tts and write a WAV to *output_path*."""
        import edge_tts

        tmp_mp3 = output_path + ".tmp.mp3"
        asyncio.run(self._edge_communicate(text, voice, tmp_mp3))
        audio = AudioSegment.from_file(tmp_mp3, format="mp3")
        os.remove(tmp_mp3)
        audio.export(output_path, format="wav")

    @staticmethod
    async def _edge_communicate(text: str, voice: str, path: str):
        import edge_tts
        await edge_tts.Communicate(text=text, voice=voice).save(path)

    @staticmethod
    def _generate_pyttsx3(text: str, output_path: str):
        """Offline fallback using the system's pyttsx3 engine."""
        import pyttsx3
        engine = pyttsx3.init()
        engine.save_to_file(text, output_path)
        engine.runAndWait()

    # ── Post-processing ──────────────────────────────────────────────────────

    def _apply_tone_mood(self, audio_path: str, tone: str, mood: int):
        """Apply tone preset scaled by mood (1–10, 5 = neutral) in place."""
        speed, vol_db = _TONE_PARAMS.get(tone, _TONE_PARAMS["Normal"])

        # Mood 5 → scale=1.0; mood 1 → scale=0.2; mood 10 → scale=2.0
        scale = (mood - 5) / 5.0 + 1.0  # maps [1..10] → [0.2..2.0]

        audio = AudioSegment.from_file(audio_path)

        if abs(speed - 1.0) > 0.001:
            adjusted = max(0.5, min(2.5, 1.0 + (speed - 1.0) * scale))
            audio = self._change_speed(audio, adjusted)

        if vol_db:
            audio = audio + (vol_db * scale)

        audio.export(audio_path, format="wav")

    @staticmethod
    def _change_speed(audio: AudioSegment, factor: float) -> AudioSegment:
        """Pitch-preserving time-stretch using WSOLA (via librosa).

        Unlike the naive frame-rate resampling approach, this stretches or
        compresses the waveform in the time domain so speed changes without
        altering the speaker's pitch — critical for keeping cloned voices
        recognisable after tone/mood post-processing.
        """
        import numpy as np
        import librosa

        # Convert to float32 mono
        raw = np.array(audio.get_array_of_samples(), dtype=np.float32)
        peak = float(1 << (8 * audio.sample_width - 1))
        samples = raw / peak
        if audio.channels == 2:
            samples = samples.reshape(-1, 2).mean(axis=1)

        # WSOLA time-stretch (rate > 1 → faster, rate < 1 → slower)
        stretched = librosa.effects.time_stretch(samples, rate=float(factor))

        # Back to pydub int samples
        stretched_int = (stretched * peak).clip(-peak, peak - 1).astype(
            np.dtype(f"<i{audio.sample_width}")
        )
        return audio._spawn(
            stretched_int.tobytes(),
            overrides={
                "frame_rate": audio.frame_rate,
                "channels": 1,
                "sample_width": audio.sample_width,
            },
        )