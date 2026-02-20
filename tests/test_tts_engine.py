"""Unit tests for tts_engine.TTSEngine."""

import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

# Ensure the repo root is on the path so tts_engine can be imported without
# installing the package.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pydub import AudioSegment
from pydub.generators import Sine

from tts_engine import TTSEngine, TONES


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_wav(path: str, duration_ms: int = 1000, sample_rate: int = 44100) -> str:
    """Write a 440 Hz sine-wave WAV file and return *path*."""
    audio = Sine(440).to_audio_segment(duration=duration_ms).set_frame_rate(sample_rate)
    audio.export(path, format="wav")
    return path


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestTTSEngineMeta(unittest.TestCase):
    def test_tones_list(self):
        """TONES must contain at least the four expected preset names."""
        for expected in ("Normal", "Upbeat", "Angry", "Excited"):
            self.assertIn(expected, TONES)


class TestTTSEngineAudioOps(unittest.TestCase):
    """Tests for pure audio-processing methods that do not require a network."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.engine = TTSEngine.__new__(TTSEngine)  # skip __init__ to avoid mkdir

    def _wav(self, name: str, duration_ms: int = 1000) -> str:
        return _make_wav(os.path.join(self.tmp_dir, name), duration_ms)

    # ── get_duration_ms ───────────────────────────────────────────────────────

    def test_get_duration_ms_returns_correct_value(self):
        path = self._wav("dur.wav", 2000)
        dur = self.engine.get_duration_ms(path)
        # pydub may be off by a few ms due to rounding; allow ±50 ms
        self.assertAlmostEqual(dur, 2000, delta=50)

    # ── trim_audio ────────────────────────────────────────────────────────────

    def test_trim_audio_shortens_file(self):
        path = self._wav("trim.wav", 3000)
        self.engine.trim_audio(path, 500, 2000)
        trimmed_dur = self.engine.get_duration_ms(path)
        self.assertAlmostEqual(trimmed_dur, 1500, delta=50)

    def test_trim_audio_returns_same_path(self):
        path = self._wav("trim_ret.wav", 2000)
        result = self.engine.trim_audio(path, 0, 1000)
        self.assertEqual(result, path)

    # ── save_as ───────────────────────────────────────────────────────────────

    def test_save_as_wav_creates_file(self):
        src = self._wav("src.wav", 500)
        dst = os.path.join(self.tmp_dir, "out.wav")
        self.engine.save_as(src, dst, "wav")
        self.assertTrue(os.path.isfile(dst))

    def test_save_as_wav_standard_params(self):
        src = self._wav("src2.wav", 500)
        dst = os.path.join(self.tmp_dir, "out2.wav")
        self.engine.save_as(src, dst, "wav")
        audio = AudioSegment.from_file(dst)
        self.assertEqual(audio.frame_rate, 44100)
        self.assertEqual(audio.sample_width, 2)
        self.assertEqual(audio.channels, 1)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
    def test_save_as_mp3_creates_file(self):
        src = self._wav("src3.wav", 500)
        dst = os.path.join(self.tmp_dir, "out3.mp3")
        self.engine.save_as(src, dst, "mp3")
        self.assertTrue(os.path.isfile(dst))

    def test_save_as_returns_output_path(self):
        src = self._wav("src4.wav", 500)
        dst = os.path.join(self.tmp_dir, "out4.wav")
        result = self.engine.save_as(src, dst, "wav")
        self.assertEqual(result, dst)

    # ── _change_speed ─────────────────────────────────────────────────────────

    def test_change_speed_faster_shortens_duration(self):
        audio = AudioSegment.from_file(self._wav("spd1.wav", 1000))
        faster = TTSEngine._change_speed(audio, 2.0)
        self.assertLess(len(faster), len(audio))

    def test_change_speed_slower_extends_duration(self):
        audio = AudioSegment.from_file(self._wav("spd2.wav", 1000))
        slower = TTSEngine._change_speed(audio, 0.5)
        self.assertGreater(len(slower), len(audio))

    def test_change_speed_one_unchanged(self):
        audio = AudioSegment.from_file(self._wav("spd3.wav", 1000))
        same = TTSEngine._change_speed(audio, 1.0)
        self.assertEqual(len(same), len(audio))

    def test_change_speed_preserves_frame_rate(self):
        audio = AudioSegment.from_file(self._wav("spd4.wav", 1000))
        result = TTSEngine._change_speed(audio, 1.5)
        self.assertEqual(result.frame_rate, audio.frame_rate)

    # ── _apply_tone_mood ──────────────────────────────────────────────────────

    def test_apply_tone_mood_normal_mood5_no_change(self):
        """Normal tone with neutral mood must leave file virtually unchanged."""
        path = self._wav("tone_noop.wav", 1000)
        original_dur = self.engine.get_duration_ms(path)
        self.engine._apply_tone_mood(path, "Normal", 5)
        new_dur = self.engine.get_duration_ms(path)
        self.assertAlmostEqual(new_dur, original_dur, delta=50)

    def test_apply_tone_mood_upbeat_increases_speed(self):
        """Upbeat tone should produce a slightly shorter result (speed > 1)."""
        path = self._wav("tone_upbeat.wav", 2000)
        original_dur = self.engine.get_duration_ms(path)
        self.engine._apply_tone_mood(path, "Upbeat", 5)
        new_dur = self.engine.get_duration_ms(path)
        self.assertLess(new_dur, original_dur)

    def test_apply_tone_mood_excited_high_mood_increases_speed(self):
        path = self._wav("tone_excited.wav", 2000)
        original_dur = self.engine.get_duration_ms(path)
        self.engine._apply_tone_mood(path, "Excited", 10)
        new_dur = self.engine.get_duration_ms(path)
        self.assertLess(new_dur, original_dur)

    # ── apply_tone_mood (public wrapper) ──────────────────────────────────────

    def test_apply_tone_mood_public_normal_mood5_is_noop(self):
        """Public apply_tone_mood with Normal/5 must not modify the file."""
        path = self._wav("pub_noop.wav", 1000)
        original_dur = self.engine.get_duration_ms(path)
        result = self.engine.apply_tone_mood(path, "Normal", 5)
        self.assertEqual(result, path)
        self.assertAlmostEqual(self.engine.get_duration_ms(path), original_dur, delta=50)

    def test_apply_tone_mood_public_returns_path(self):
        path = self._wav("pub_ret.wav", 1000)
        result = self.engine.apply_tone_mood(path, "Normal", 5)
        self.assertEqual(result, path)

    def test_apply_tone_mood_public_upbeat_shortens(self):
        """Public wrapper must delegate to _apply_tone_mood for non-Normal tone."""
        path = self._wav("pub_upbeat.wav", 2000)
        original_dur = self.engine.get_duration_ms(path)
        self.engine.apply_tone_mood(path, "Upbeat", 5)
        self.assertLess(self.engine.get_duration_ms(path), original_dur)

    def test_apply_tone_mood_public_mood_shift_triggers_processing(self):
        """Mood != 5 with Normal tone must still trigger processing (vol change)."""
        path = self._wav("pub_mood.wav", 1000)
        # Should not raise; file is modified in place
        self.engine.apply_tone_mood(path, "Normal", 8)
        self.assertTrue(os.path.isfile(path))

    # ── generate (mocked backends) ────────────────────────────────────────────

    def test_generate_returns_wav_path(self):
        """generate() with a mocked edge-tts backend must return a .wav path."""
        os.makedirs(os.path.join(self.tmp_dir, "output"), exist_ok=True)

        def fake_generate_edge(text, voice, output_path):
            _make_wav(output_path, 500)

        engine = TTSEngine.__new__(TTSEngine)
        engine._generate_edge = fake_generate_edge

        with patch("tts_engine.OUTPUT_DIR", os.path.join(self.tmp_dir, "output")):
            result = engine.generate("Hello", "en-US-AriaNeural")

        self.assertTrue(result.endswith(".wav"))
        self.assertTrue(os.path.isfile(result))

    def test_generate_falls_back_to_pyttsx3_on_edge_failure(self):
        """When edge-tts raises, pyttsx3 fallback must be attempted."""
        os.makedirs(os.path.join(self.tmp_dir, "output2"), exist_ok=True)

        def fail_edge(text, voice, output_path):
            raise RuntimeError("network unavailable")

        def fake_pyttsx3(text, output_path):
            _make_wav(output_path, 500)

        engine = TTSEngine.__new__(TTSEngine)
        engine._generate_edge = fail_edge
        engine._generate_pyttsx3 = staticmethod(lambda t, p: _make_wav(p, 500))

        with patch("tts_engine.OUTPUT_DIR", os.path.join(self.tmp_dir, "output2")):
            result = engine.generate("Hello fallback", "en-US-AriaNeural")

        self.assertTrue(os.path.isfile(result))

    def test_generate_raises_when_both_backends_fail(self):
        """RuntimeError must bubble up when both backends fail."""
        os.makedirs(os.path.join(self.tmp_dir, "output3"), exist_ok=True)

        engine = TTSEngine.__new__(TTSEngine)
        engine._generate_edge = MagicMock(side_effect=RuntimeError("edge"))
        engine._generate_pyttsx3 = MagicMock(side_effect=RuntimeError("pyttsx3"))

        with patch("tts_engine.OUTPUT_DIR", os.path.join(self.tmp_dir, "output3")):
            with self.assertRaises(RuntimeError):
                engine.generate("fail", "en-US-AriaNeural")

    def test_generate_uses_custom_output_path(self):
        out = os.path.join(self.tmp_dir, "custom_out.wav")

        def fake_edge(text, voice, output_path):
            _make_wav(output_path, 300)

        engine = TTSEngine.__new__(TTSEngine)
        engine._generate_edge = fake_edge

        with patch("tts_engine.OUTPUT_DIR", self.tmp_dir):
            result = engine.generate("Hello", "en-US-AriaNeural", output_path=out)

        self.assertEqual(result, out)
        self.assertTrue(os.path.isfile(out))

    # ── Chatterbox routing (primary cloning backend) ─────────────────────────

    def test_generate_uses_chatterbox_when_reference_audio_provided(self):
        """Chatterbox must be the first cloning attempt when ref audio exists."""
        os.makedirs(os.path.join(self.tmp_dir, "output_cb"), exist_ok=True)
        ref = self._wav("ref_cb.wav", 3000)

        engine = TTSEngine.__new__(TTSEngine)
        engine._chatterbox = None
        engine._xtts = None
        engine._generate_chatterbox = MagicMock(
            side_effect=lambda t, r, p: _make_wav(p, 500)
        )
        engine._generate_xtts = MagicMock()   # must NOT be called
        engine._generate_edge = MagicMock()   # must NOT be called

        with patch("tts_engine.OUTPUT_DIR", os.path.join(self.tmp_dir, "output_cb")):
            result = engine.generate("Hello", "en-US-AriaNeural", reference_audio=ref)

        engine._generate_chatterbox.assert_called_once()
        engine._generate_xtts.assert_not_called()
        engine._generate_edge.assert_not_called()
        self.assertTrue(os.path.isfile(result))

    def test_generate_falls_back_to_xtts_when_chatterbox_import_error(self):
        """ImportError from Chatterbox → try XTTS v2 next."""
        os.makedirs(os.path.join(self.tmp_dir, "output_cbfb"), exist_ok=True)
        ref = self._wav("ref_cbfb.wav", 3000)

        engine = TTSEngine.__new__(TTSEngine)
        engine._chatterbox = None
        engine._xtts = None
        engine._generate_chatterbox = MagicMock(
            side_effect=ImportError("chatterbox-tts not installed")
        )
        engine._generate_xtts = MagicMock(
            side_effect=lambda t, r, l, p: _make_wav(p, 500)
        )
        engine._generate_edge = MagicMock()

        with patch("tts_engine.OUTPUT_DIR", os.path.join(self.tmp_dir, "output_cbfb")):
            result = engine.generate("Hello", "en-US-AriaNeural", reference_audio=ref)

        engine._generate_chatterbox.assert_called_once()
        engine._generate_xtts.assert_called_once()
        engine._generate_edge.assert_not_called()
        self.assertTrue(os.path.isfile(result))

    def test_generate_falls_back_to_edge_when_both_cloners_fail(self):
        """If both Chatterbox and XTTS fail, edge-tts must be used."""
        os.makedirs(os.path.join(self.tmp_dir, "output_bothfail"), exist_ok=True)
        ref = self._wav("ref_bothfail.wav", 3000)

        engine = TTSEngine.__new__(TTSEngine)
        engine._chatterbox = None
        engine._xtts = None
        engine._generate_chatterbox = MagicMock(side_effect=ImportError("no chatterbox"))
        engine._generate_xtts = MagicMock(side_effect=ImportError("no TTS"))
        engine._generate_edge = MagicMock(side_effect=lambda t, v, p: _make_wav(p, 500))

        with patch("tts_engine.OUTPUT_DIR", os.path.join(self.tmp_dir, "output_bothfail")):
            result = engine.generate("Hello", "en-US-AriaNeural", reference_audio=ref)

        engine._generate_chatterbox.assert_called_once()
        engine._generate_xtts.assert_called_once()
        engine._generate_edge.assert_called_once()
        self.assertTrue(os.path.isfile(result))

    def test_generate_skips_cloning_when_reference_audio_missing(self):
        """No reference audio → neither Chatterbox nor XTTS called."""
        os.makedirs(os.path.join(self.tmp_dir, "output_noref2"), exist_ok=True)

        engine = TTSEngine.__new__(TTSEngine)
        engine._chatterbox = None
        engine._xtts = None
        engine._generate_chatterbox = MagicMock()
        engine._generate_xtts = MagicMock()
        engine._generate_edge = MagicMock(side_effect=lambda t, v, p: _make_wav(p, 500))

        with patch("tts_engine.OUTPUT_DIR", os.path.join(self.tmp_dir, "output_noref2")):
            engine.generate("Hello", "en-US-AriaNeural",
                            reference_audio="/nonexistent/path.wav")

        engine._generate_chatterbox.assert_not_called()
        engine._generate_xtts.assert_not_called()
        engine._generate_edge.assert_called_once()

    # ── XTTS routing ─────────────────────────────────────────────────────────

    def test_generate_uses_xtts_when_reference_audio_provided(self):
        """When reference_audio exists and Chatterbox fails, XTTS must be called."""
        os.makedirs(os.path.join(self.tmp_dir, "output_xtts"), exist_ok=True)
        ref = self._wav("ref.wav", 3000)

        engine = TTSEngine.__new__(TTSEngine)
        engine._chatterbox = None
        engine._xtts = None
        engine._generate_chatterbox = MagicMock(side_effect=ImportError("no cb"))
        engine._generate_xtts = MagicMock(side_effect=lambda t, r, l, p: _make_wav(p, 500))
        engine._generate_edge = MagicMock()  # must NOT be called

        with patch("tts_engine.OUTPUT_DIR", os.path.join(self.tmp_dir, "output_xtts")):
            result = engine.generate("Hello", "en-US-AriaNeural", reference_audio=ref)

        engine._generate_xtts.assert_called_once()
        engine._generate_edge.assert_not_called()
        self.assertTrue(os.path.isfile(result))

    def test_generate_falls_back_to_edge_when_xtts_raises_import_error(self):
        """ImportError from _generate_xtts → silently fall back to edge-tts."""
        os.makedirs(os.path.join(self.tmp_dir, "output_xfb"), exist_ok=True)
        ref = self._wav("ref_fb.wav", 3000)

        engine = TTSEngine.__new__(TTSEngine)
        engine._chatterbox = None
        engine._xtts = None
        engine._generate_chatterbox = MagicMock(side_effect=ImportError("no cb"))
        engine._generate_xtts = MagicMock(side_effect=ImportError("TTS not installed"))
        engine._generate_edge = MagicMock(side_effect=lambda t, v, p: _make_wav(p, 500))

        with patch("tts_engine.OUTPUT_DIR", os.path.join(self.tmp_dir, "output_xfb")):
            result = engine.generate("Hello", "en-US-AriaNeural", reference_audio=ref)

        engine._generate_edge.assert_called_once()
        self.assertTrue(os.path.isfile(result))

    def test_generate_falls_back_to_edge_when_xtts_inference_fails(self):
        """Any exception from _generate_xtts → silently fall back to edge-tts."""
        os.makedirs(os.path.join(self.tmp_dir, "output_xerr"), exist_ok=True)
        ref = self._wav("ref_err.wav", 3000)

        engine = TTSEngine.__new__(TTSEngine)
        engine._chatterbox = None
        engine._xtts = None
        engine._generate_chatterbox = MagicMock(side_effect=ImportError("no cb"))
        engine._generate_xtts = MagicMock(side_effect=RuntimeError("CUDA OOM"))
        engine._generate_edge = MagicMock(side_effect=lambda t, v, p: _make_wav(p, 500))

        with patch("tts_engine.OUTPUT_DIR", os.path.join(self.tmp_dir, "output_xerr")):
            result = engine.generate("Hello", "en-US-AriaNeural", reference_audio=ref)

        engine._generate_edge.assert_called_once()
        self.assertTrue(os.path.isfile(result))

    def test_generate_skips_xtts_when_reference_audio_missing(self):
        """If reference_audio path doesn't exist, edge-tts must be used directly."""
        os.makedirs(os.path.join(self.tmp_dir, "output_noref"), exist_ok=True)

        engine = TTSEngine.__new__(TTSEngine)
        engine._chatterbox = None
        engine._xtts = None
        engine._generate_chatterbox = MagicMock()
        engine._generate_xtts = MagicMock()
        engine._generate_edge = MagicMock(side_effect=lambda t, v, p: _make_wav(p, 500))

        with patch("tts_engine.OUTPUT_DIR", os.path.join(self.tmp_dir, "output_noref")):
            engine.generate("Hello", "en-US-AriaNeural",
                            reference_audio="/nonexistent/path.wav")

        engine._generate_xtts.assert_not_called()
        engine._generate_edge.assert_called_once()

    def test_generate_passes_language_to_xtts(self):
        """The *language* parameter must reach _generate_xtts unchanged."""
        os.makedirs(os.path.join(self.tmp_dir, "output_lang"), exist_ok=True)
        ref = self._wav("ref_lang.wav", 3000)

        engine = TTSEngine.__new__(TTSEngine)
        engine._chatterbox = None
        engine._xtts = None
        engine._generate_chatterbox = MagicMock(side_effect=ImportError("no cb"))
        captured = {}
        def fake_xtts(text, reference_audio, language, output_path):
            captured["language"] = language
            _make_wav(output_path, 500)
        engine._generate_xtts = fake_xtts
        engine._generate_edge = MagicMock()

        with patch("tts_engine.OUTPUT_DIR", os.path.join(self.tmp_dir, "output_lang")):
            engine.generate("Bonjour", "fr-FR-DeniseNeural",
                            reference_audio=ref, language="fr")

        self.assertEqual(captured["language"], "fr")


if __name__ == "__main__":
    unittest.main()

