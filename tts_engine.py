"""TTS engine for EchoPilot — edge-tts primary, pyttsx3 offline fallback."""

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
        self._xtts = None  # Coqui XTTS v2 instance, loaded on demand

    # ── Public API ───────────────────────────────────────────────────────────

    def generate(self, text: str, voice_short_name: str,
                 tone: str = "Normal", mood: int = 5,
                 output_path: str = None,
                 reference_audio: str = None,
                 language: str = "en") -> str:
        """
        Synthesise *text* using *voice_short_name* (edge-tts voice ID).

        When *reference_audio* is a valid file path, Coqui XTTS v2 is used
        for zero-shot voice cloning so the output sounds like the speaker in
        the recording.  Falls back to edge-tts when the ``TTS`` package is not
        installed, and to pyttsx3 when edge-tts is unavailable.

        :param tone:            One of TONES; applies speed/volume post-processing.
        :param mood:            1–10 scale; 5 is neutral (no extra effect).
        :param reference_audio: Path to a WAV/MP3 reference recording (≥ 3 s).
        :param language:        2-letter BCP-47 code for XTTS (e.g. ``'en'``, ``'fr'``).
        :returns: Path to the generated WAV file.
        """
        if output_path is None:
            fd, output_path = tempfile.mkstemp(suffix=".wav", dir=OUTPUT_DIR)
            os.close(fd)

        # 1. Try XTTS v2 voice cloning when a reference recording is available
        if reference_audio and os.path.isfile(reference_audio):
            try:
                self._generate_xtts(text, reference_audio, language, output_path)
                if tone != "Normal" or mood != 5:
                    self._apply_tone_mood(output_path, tone, mood)
                return output_path
            except ImportError:
                pass  # TTS package not installed → fall through to edge-tts
            except Exception:
                pass  # XTTS inference error → fall through to edge-tts

        # 2. edge-tts (primary neural voices)
        try:
            self._generate_edge(text, voice_short_name, output_path)
        except Exception as edge_err:
            # 3. pyttsx3 offline fallback
            try:
                self._generate_pyttsx3(text, output_path)
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

    # XTlanguage codes accepted by XTTS v2
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
        """Resample to change playback speed (also shifts pitch slightly)."""
        new_rate = int(audio.frame_rate * factor)
        return audio._spawn(
            audio.raw_data, overrides={"frame_rate": new_rate}
        ).set_frame_rate(audio.frame_rate)