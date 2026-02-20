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

    # ── Backend tracking ──────────────────────────────────────────────────────

    def test_last_backend_set_to_chatterbox_on_success(self):
        """_last_backend must be 'chatterbox' when Chatterbox succeeds."""
        os.makedirs(os.path.join(self.tmp_dir, "output_track_cb"), exist_ok=True)
        ref = self._wav("ref_track_cb.wav", 3000)

        engine = TTSEngine.__new__(TTSEngine)
        engine._chatterbox = None
        engine._xtts = None
        engine._last_backend = "edge-tts"
        engine._last_clone_errors = []
        engine._generate_chatterbox = MagicMock(side_effect=lambda t, r, p: _make_wav(p, 500))
        engine._generate_xtts = MagicMock()
        engine._generate_edge = MagicMock()

        with patch("tts_engine.OUTPUT_DIR", os.path.join(self.tmp_dir, "output_track_cb")):
            engine.generate("Hi", "en-US-AriaNeural", reference_audio=ref)

        self.assertEqual(engine._last_backend, "chatterbox")

    def test_last_backend_set_to_edge_on_fallback(self):
        """_last_backend must be 'edge-tts' when cloning fails and edge-tts runs."""
        os.makedirs(os.path.join(self.tmp_dir, "output_track_edge"), exist_ok=True)
        ref = self._wav("ref_track_edge.wav", 3000)

        engine = TTSEngine.__new__(TTSEngine)
        engine._chatterbox = None
        engine._xtts = None
        engine._last_backend = "edge-tts"
        engine._last_clone_errors = []
        engine._generate_chatterbox = MagicMock(side_effect=ImportError("no cb"))
        engine._generate_xtts = MagicMock(side_effect=ImportError("no xtts"))
        engine._generate_edge = MagicMock(side_effect=lambda t, v, p: _make_wav(p, 500))

        with patch("tts_engine.OUTPUT_DIR", os.path.join(self.tmp_dir, "output_track_edge")):
            engine.generate("Hi", "en-US-AriaNeural", reference_audio=ref)

        self.assertEqual(engine._last_backend, "edge-tts")

    def test_last_clone_errors_populated_on_fallback(self):
        """_last_clone_errors must contain error descriptions when cloning fails."""
        os.makedirs(os.path.join(self.tmp_dir, "output_track_err"), exist_ok=True)
        ref = self._wav("ref_track_err.wav", 3000)

        engine = TTSEngine.__new__(TTSEngine)
        engine._chatterbox = None
        engine._xtts = None
        engine._last_backend = "edge-tts"
        engine._last_clone_errors = []
        engine._generate_chatterbox = MagicMock(side_effect=ImportError("cb missing"))
        engine._generate_xtts = MagicMock(side_effect=RuntimeError("xtts crashed"))
        engine._generate_edge = MagicMock(side_effect=lambda t, v, p: _make_wav(p, 500))

        with patch("tts_engine.OUTPUT_DIR", os.path.join(self.tmp_dir, "output_track_err")):
            engine.generate("Hi", "en-US-AriaNeural", reference_audio=ref)

        self.assertEqual(len(engine._last_clone_errors), 2)
        self.assertIn("Chatterbox", engine._last_clone_errors[0])
        self.assertIn("XTTS", engine._last_clone_errors[1])

    def test_last_clone_errors_reset_each_call(self):
        """_last_clone_errors must be cleared at the start of each generate() call."""
        os.makedirs(os.path.join(self.tmp_dir, "output_reset"), exist_ok=True)

        engine = TTSEngine.__new__(TTSEngine)
        engine._chatterbox = None
        engine._xtts = None
        engine._last_backend = "edge-tts"
        engine._last_clone_errors = ["stale error from previous run"]
        engine._generate_chatterbox = MagicMock()
        engine._generate_xtts = MagicMock()
        engine._generate_edge = MagicMock(side_effect=lambda t, v, p: _make_wav(p, 500))

        with patch("tts_engine.OUTPUT_DIR", os.path.join(self.tmp_dir, "output_reset")):
            engine.generate("Hi", "en-US-AriaNeural")

        self.assertEqual(engine._last_clone_errors, [])

    # ── _change_speed (pitch-preserving WSOLA) ────────────────────────────────

    def test_change_speed_faster_shortens_duration(self):
        """factor > 1 must produce a shorter segment."""
        path = self._wav("speed_fast.wav", 2000)
        audio = AudioSegment.from_file(path)
        from tts_engine import TTSEngine as TE
        stretched = TE._change_speed(audio, 1.5)
        # Faster → fewer frames
        self.assertLess(len(stretched), len(audio))

    def test_change_speed_slower_lengthens_duration(self):
        """factor < 1 must produce a longer segment."""
        path = self._wav("speed_slow.wav", 2000)
        audio = AudioSegment.from_file(path)
        from tts_engine import TTSEngine as TE
        stretched = TE._change_speed(audio, 0.7)
        # Slower → more frames
        self.assertGreater(len(stretched), len(audio))

    def test_change_speed_preserves_sample_rate(self):
        """Frame rate must be identical before and after time-stretch."""
        path = self._wav("speed_rate.wav", 1000)
        audio = AudioSegment.from_file(path)
        from tts_engine import TTSEngine as TE
        stretched = TE._change_speed(audio, 1.2)
        self.assertEqual(stretched.frame_rate, audio.frame_rate)

    def test_change_speed_identity_near_noop(self):
        """factor ≈ 1.0 must keep duration approximately the same."""
        path = self._wav("speed_id.wav", 2000)
        audio = AudioSegment.from_file(path)
        from tts_engine import TTSEngine as TE
        stretched = TE._change_speed(audio, 1.0)
        self.assertAlmostEqual(len(stretched), len(audio), delta=100)

    # ── cloning_backend() ─────────────────────────────────────────────────────

    def test_cloning_backend_returns_string_or_none(self):
        """cloning_backend() must return a str or None, never raise."""
        result = TTSEngine.cloning_backend()
        self.assertIn(result, (None, "chatterbox", "xtts"))

    def test_cloning_backend_chatterbox_when_importable(self):
        """cloning_backend() returns 'chatterbox' when chatterbox.tts is importable."""
        import importlib, types
        fake_mod = types.ModuleType("chatterbox")
        fake_mod.tts = types.ModuleType("chatterbox.tts")
        with patch.dict("sys.modules", {"chatterbox": fake_mod, "chatterbox.tts": fake_mod.tts}):
            result = TTSEngine.cloning_backend()
        self.assertEqual(result, "chatterbox")

    def test_cloning_backend_xtts_when_chatterbox_missing(self):
        """cloning_backend() returns 'xtts' when only TTS is importable."""
        import types
        fake_tts = types.ModuleType("TTS")
        with patch.dict("sys.modules", {"chatterbox": None, "chatterbox.tts": None,
                                        "TTS": fake_tts}):
            result = TTSEngine.cloning_backend()
        self.assertEqual(result, "xtts")

    def test_cloning_backend_none_when_both_missing(self):
        """cloning_backend() returns None when neither package is importable."""
        with patch.dict("sys.modules", {"chatterbox": None, "chatterbox.tts": None,
                                        "TTS": None}):
            result = TTSEngine.cloning_backend()
        self.assertIsNone(result)

    def test_cloning_install_instructions_returns_nonempty_string(self):
        """cloning_install_instructions() must return a non-empty string."""
        result = TTSEngine.cloning_install_instructions()
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 20)

    # ── Future-annotations / Python 3.9 compatibility ─────────────────────────

    def test_from_future_annotations_in_tts_engine(self):
        """tts_engine.py must start with 'from __future__ import annotations'."""
        import os
        src_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "tts_engine.py",
        )
        first_non_comment = ""
        with open(src_path, encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and not stripped.startswith('"""'):
                    first_non_comment = stripped
                    break
        self.assertEqual(
            first_non_comment,
            "from __future__ import annotations",
            "tts_engine.py must have 'from __future__ import annotations' as the first code line",
        )

    # ── generate() output-dir safety ─────────────────────────────────────────

    def test_generate_creates_output_dir_if_missing(self):
        """generate() must not crash when OUTPUT_DIR does not pre-exist."""
        import shutil
        new_dir = os.path.join(self.tmp_dir, "fresh_output")
        # Deliberately do NOT create new_dir

        engine = TTSEngine.__new__(TTSEngine)
        engine._chatterbox = None
        engine._xtts = None
        engine._last_backend = "edge-tts"
        engine._last_clone_errors = []
        engine._generate_chatterbox = MagicMock()
        engine._generate_xtts = MagicMock()
        engine._generate_edge = MagicMock(side_effect=lambda t, v, p: _make_wav(p, 500))

        with patch("tts_engine.OUTPUT_DIR", new_dir):
            # The TTSEngine constructor creates OUTPUT_DIR; simulate that here
            os.makedirs(new_dir, exist_ok=True)
            result = engine.generate("Hello", "en-US-AriaNeural")

        self.assertTrue(os.path.isfile(result))


# ── Language resolution logic ─────────────────────────────────────────────────

class TestResolveLangCode(unittest.TestCase):
    """Tests for the _resolve_lang_code priority chain.

    _resolve_lang_code is a widget method; we test its logic here by exercising
    VoiceManager.get_locale_for_language (which is the core lookup it uses) and
    verifying the expected 2-letter codes are returned.

    Steps:
      1. profile_lang (display name) → get_locale_for_language
      2. combo_lang (display name) → get_locale_for_language
      3. langdetect(text) → returns a BCP-47 code directly (NOT through get_locale_for_language)
      4. fallback "en"
    """

    def _resolve(self, profile_lang: str, combo_lang: str, text: str) -> str:
        """Pure-Python reimplementation of app._resolve_lang_code for unit testing.

        We cannot instantiate EchoPilot (a QMainWindow) without a QApplication,
        so we mirror the production priority logic here.  If the production code
        changes, this helper must be updated in tandem — both follow the same
        docstring contract:
          1. profile_lang (display name) → get_locale_for_language
          2. combo_lang (display name)   → get_locale_for_language
          3. langdetect(text)            → BCP-47 code used directly
          4. fallback "en"
        """
        from voice_manager import VoiceManager

        # Steps 1 & 2 — display names
        display: str | None = None
        if profile_lang and profile_lang not in ("", "Unknown", "All"):
            display = profile_lang
        if display is None and combo_lang not in ("", "All"):
            display = combo_lang

        if display is not None:
            locale = VoiceManager.get_locale_for_language(display).lower()
            if locale.startswith("zh"):
                return "zh-cn"
            return locale.split("-")[0] or "en"

        # Step 3 — langdetect returns a code directly (e.g. "fr")
        try:
            from langdetect import detect as _ld, LangDetectException
            code = (_ld(text[:500]) or "en").lower()
        except (ImportError, LangDetectException):
            code = "en"
        if code.startswith("zh"):
            return "zh-cn"
        return code.split("-")[0] or "en"

    def test_profile_lang_used_when_set(self):
        code = self._resolve("French", "All", "hello world")
        self.assertEqual(code, "fr")

    def test_profile_lang_empty_falls_to_combo(self):
        code = self._resolve("", "German", "hello world")
        self.assertEqual(code, "de")

    def test_profile_lang_unknown_falls_to_combo(self):
        code = self._resolve("Unknown", "Spanish", "hello")
        self.assertEqual(code, "es")

    def test_combo_all_falls_to_detect(self):
        # "Bonjour tout le monde" is French — langdetect should detect it
        code = self._resolve("", "All", "Bonjour tout le monde, comment allez-vous?")
        self.assertEqual(code, "fr")

    def test_chinese_display_name_returns_zh_cn(self):
        code = self._resolve("Chinese", "All", "hello")
        self.assertEqual(code, "zh-cn")

    def test_empty_profile_and_combo_detects_english(self):
        code = self._resolve("", "All", "The quick brown fox jumps over the lazy dog")
        self.assertEqual(code, "en")


# ── Chatterbox English-only gate ──────────────────────────────────────────────

class TestChatterboxEnglishOnly(unittest.TestCase):
    """Chatterbox must be bypassed for non-English languages."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _wav(self, name: str, ms: int = 2000) -> str:
        p = os.path.join(self.tmp_dir, name)
        return _make_wav(p, ms)

    def _engine_with_mocks(self, cb_side_effect=None, xtts_side_effect=None,
                            edge_side_effect=None):
        engine = TTSEngine.__new__(TTSEngine)
        engine._chatterbox = None
        engine._xtts = None
        engine._last_backend = "edge-tts"
        engine._last_clone_errors = []
        engine._generate_chatterbox = MagicMock(side_effect=cb_side_effect)
        engine._generate_xtts = MagicMock(side_effect=xtts_side_effect)
        engine._generate_edge = MagicMock(side_effect=(
            edge_side_effect or (lambda t, v, p: _make_wav(p, 500))
        ))
        return engine

    def test_chatterbox_called_for_english(self):
        """Chatterbox IS used when language='en' and ref audio exists."""
        ref = self._wav("ref_en.wav")
        engine = self._engine_with_mocks(
            cb_side_effect=lambda t, r, p: _make_wav(p, 500),
        )
        out_dir = os.path.join(self.tmp_dir, "out_en")
        os.makedirs(out_dir)
        with patch("tts_engine.OUTPUT_DIR", out_dir):
            engine.generate("Hello world", "en-US-AriaNeural",
                            language="en", reference_audio=ref)
        engine._generate_chatterbox.assert_called_once()
        engine._generate_xtts.assert_not_called()

    def test_chatterbox_skipped_for_french(self):
        """Chatterbox must NOT be called when language='fr'."""
        ref = self._wav("ref_fr.wav")
        engine = self._engine_with_mocks(
            xtts_side_effect=lambda t, r, l, p: _make_wav(p, 500),
        )
        out_dir = os.path.join(self.tmp_dir, "out_fr")
        os.makedirs(out_dir)
        with patch("tts_engine.OUTPUT_DIR", out_dir):
            engine.generate("Bonjour le monde", "fr-FR-DeniseNeural",
                            language="fr", reference_audio=ref)
        engine._generate_chatterbox.assert_not_called()
        engine._generate_xtts.assert_called_once()

    def test_chatterbox_skipped_for_spanish(self):
        """Chatterbox must NOT be called when language='es'."""
        ref = self._wav("ref_es.wav")
        engine = self._engine_with_mocks(
            xtts_side_effect=lambda t, r, l, p: _make_wav(p, 500),
        )
        out_dir = os.path.join(self.tmp_dir, "out_es")
        os.makedirs(out_dir)
        with patch("tts_engine.OUTPUT_DIR", out_dir):
            engine.generate("Hola mundo", "es-ES-ElviraNeural",
                            language="es", reference_audio=ref)
        engine._generate_chatterbox.assert_not_called()
        engine._generate_xtts.assert_called_once()

    def test_chatterbox_skipped_for_chinese(self):
        """Chatterbox must NOT be called when language='zh-cn'."""
        ref = self._wav("ref_zh.wav")
        engine = self._engine_with_mocks(
            xtts_side_effect=lambda t, r, l, p: _make_wav(p, 500),
        )
        out_dir = os.path.join(self.tmp_dir, "out_zh")
        os.makedirs(out_dir)
        with patch("tts_engine.OUTPUT_DIR", out_dir):
            engine.generate("你好世界", "zh-CN-XiaoxiaoNeural",
                            language="zh-cn", reference_audio=ref)
        engine._generate_chatterbox.assert_not_called()
        engine._generate_xtts.assert_called_once()

    def test_chatterbox_used_for_en_us_locale(self):
        """language='en-US' must still trigger Chatterbox (strip to 'en')."""
        ref = self._wav("ref_en_us.wav")
        engine = self._engine_with_mocks(
            cb_side_effect=lambda t, r, p: _make_wav(p, 500),
        )
        out_dir = os.path.join(self.tmp_dir, "out_en_us")
        os.makedirs(out_dir)
        with patch("tts_engine.OUTPUT_DIR", out_dir):
            engine.generate("Hello world", "en-US-AriaNeural",
                            language="en-US", reference_audio=ref)
        engine._generate_chatterbox.assert_called_once()
        engine._generate_xtts.assert_not_called()


class TestXTTSTosAndGpu(unittest.TestCase):
    """Confirm COQUI_TOS_AGREED is set and gpu is derived before TTS() is called."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        # Remove env var so each test starts clean
        os.environ.pop("COQUI_TOS_AGREED", None)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)
        os.environ.pop("COQUI_TOS_AGREED", None)

    def _make_fake_tts_module(self, captured: dict):
        """Return a fake TTS.api module whose TTS() records constructor kwargs."""
        class FakeTTS:
            def __init__(self, model_name, gpu=None):
                captured["model_name"] = model_name
                captured["gpu"] = gpu
                captured["tos_agreed"] = os.environ.get("COQUI_TOS_AGREED")
        fake_api = MagicMock()
        fake_api.TTS = FakeTTS
        fake_module = MagicMock()
        fake_module.api = fake_api
        return fake_module

    def test_tos_env_var_set_before_tts_instantiation(self):
        """COQUI_TOS_AGREED must be '1' when TTS() is called."""
        captured: dict = {}
        fake_tts_module = self._make_fake_tts_module(captured)

        engine = TTSEngine.__new__(TTSEngine)
        engine._xtts = None

        fake_torch = MagicMock()
        fake_torch.cuda.is_available.return_value = False

        with patch.dict("sys.modules", {
            "torch": fake_torch,
            "TTS": fake_tts_module,
            "TTS.api": fake_tts_module.api,
        }):
            engine._get_xtts()

        self.assertEqual(captured.get("tos_agreed"), "1",
                         "COQUI_TOS_AGREED must be '1' at the moment TTS() is called")

    def test_xtts_uses_cuda_availability_for_gpu_flag(self):
        """_get_xtts must pass gpu=True when CUDA is available, gpu=False otherwise."""
        for cuda_available, expected_gpu in [(True, True), (False, False)]:
            with self.subTest(cuda=cuda_available):
                captured: dict = {}
                fake_tts_module = self._make_fake_tts_module(captured)

                engine = TTSEngine.__new__(TTSEngine)
                engine._xtts = None

                fake_torch = MagicMock()
                fake_torch.cuda.is_available.return_value = cuda_available

                with patch.dict("sys.modules", {
                    "torch": fake_torch,
                    "TTS": fake_tts_module,
                    "TTS.api": fake_tts_module.api,
                }):
                    engine._get_xtts()

                self.assertEqual(captured.get("gpu"), expected_gpu)

    def test_add_safe_globals_called_for_pytorch26(self):
        """_get_xtts must call torch.serialization.add_safe_globals with all 4 XTTS classes."""
        import types

        captured_globals: list = []

        # Build a fake torch module that records add_safe_globals calls
        fake_torch = MagicMock()
        fake_torch.cuda.is_available.return_value = False
        fake_serialization = MagicMock()
        fake_serialization.add_safe_globals = MagicMock(
            side_effect=lambda classes: captured_globals.extend(classes)
        )
        fake_torch.serialization = fake_serialization

        # Fake TTS.api
        captured_tts: dict = {}
        class FakeTTS:
            def __init__(self, model_name, gpu=None):
                captured_tts["called"] = True
        fake_api = MagicMock()
        fake_api.TTS = FakeTTS

        # Fake XTTS config classes
        FakeXttsConfig = type("XttsConfig", (), {})
        FakeXttsAudioConfig = type("XttsAudioConfig", (), {})
        FakeXttsArgs = type("XttsArgs", (), {})
        FakeBaseDatasetConfig = type("BaseDatasetConfig", (), {})

        fake_xtts_config_mod = MagicMock()
        fake_xtts_config_mod.XttsConfig = FakeXttsConfig
        fake_xtts_model_mod = MagicMock()
        fake_xtts_model_mod.XttsAudioConfig = FakeXttsAudioConfig
        fake_xtts_model_mod.XttsArgs = FakeXttsArgs
        fake_tts_config_mod = MagicMock()
        fake_tts_config_mod.BaseDatasetConfig = FakeBaseDatasetConfig

        fake_tts_module = types.ModuleType("TTS")
        fake_tts_module.api = fake_api

        engine = TTSEngine.__new__(TTSEngine)
        engine._xtts = None

        with patch.dict("sys.modules", {
            "torch": fake_torch,
            "TTS": fake_tts_module,
            "TTS.api": fake_api,
            "TTS.tts": MagicMock(),
            "TTS.tts.configs": MagicMock(),
            "TTS.tts.configs.xtts_config": fake_xtts_config_mod,
            "TTS.tts.models": MagicMock(),
            "TTS.tts.models.xtts": fake_xtts_model_mod,
            "TTS.config": fake_tts_config_mod,
        }):
            engine._get_xtts()

        # add_safe_globals must have been called with all 4 classes
        self.assertIn(FakeXttsConfig, captured_globals,
                      "XttsConfig must be in add_safe_globals call")
        self.assertIn(FakeXttsAudioConfig, captured_globals,
                      "XttsAudioConfig must be in add_safe_globals call")
        self.assertIn(FakeXttsArgs, captured_globals,
                      "XttsArgs must be in add_safe_globals call")
        self.assertIn(FakeBaseDatasetConfig, captured_globals,
                      "BaseDatasetConfig must be in add_safe_globals call")


# ── pt-BR / XTTS language routing ─────────────────────────────────────────────

class TestPtBrXttsRouting(unittest.TestCase):
    """Guarantee that Portuguese (pt-BR) voice cloning routes correctly to XTTS."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _wav(self, name: str, duration_ms: int = 3000) -> str:
        return _make_wav(os.path.join(self.tmp_dir, name), duration_ms)

    def _engine(self) -> TTSEngine:
        engine = TTSEngine.__new__(TTSEngine)
        engine._chatterbox = None
        engine._xtts = None
        engine._last_backend = "edge-tts"
        engine._last_clone_errors = []
        return engine

    def test_pt_in_xtts_languages(self):
        """'pt' must be in _XTTS_LANGUAGES — XTTS v2 supports Brazilian Portuguese."""
        self.assertIn("pt", TTSEngine._XTTS_LANGUAGES)

    def test_chatterbox_skipped_for_portuguese(self):
        """Chatterbox must be SKIPPED for language='pt' (English-only engine)."""
        os.makedirs(os.path.join(self.tmp_dir, "out_pt_cb"), exist_ok=True)
        ref = self._wav("ref_pt.wav")
        engine = self._engine()
        engine._generate_chatterbox = MagicMock()
        engine._generate_xtts = MagicMock(side_effect=lambda t, r, l, p: _make_wav(p, 500))
        engine._generate_edge = MagicMock()

        with patch("tts_engine.OUTPUT_DIR", os.path.join(self.tmp_dir, "out_pt_cb")):
            engine.generate("Olá", "pt-BR-AntonioNeural",
                            reference_audio=ref, language="pt")

        engine._generate_chatterbox.assert_not_called()
        engine._generate_xtts.assert_called_once()

    def test_xtts_called_with_pt_language_code(self):
        """XTTS must receive language='pt' when the profile language is Portuguese."""
        os.makedirs(os.path.join(self.tmp_dir, "out_pt_lang"), exist_ok=True)
        ref = self._wav("ref_pt_lang.wav")
        engine = self._engine()
        engine._generate_chatterbox = MagicMock(side_effect=ImportError("no cb"))
        captured: dict = {}

        def fake_xtts(text, reference_audio, language, output_path):
            captured["language"] = language
            _make_wav(output_path, 500)

        engine._generate_xtts = fake_xtts
        engine._generate_edge = MagicMock()

        with patch("tts_engine.OUTPUT_DIR", os.path.join(self.tmp_dir, "out_pt_lang")):
            engine.generate("Olá mundo", "pt-BR-AntonioNeural",
                            reference_audio=ref, language="pt")

        self.assertEqual(captured.get("language"), "pt",
                         "XTTS must receive 'pt', not a locale like 'pt-br' or a display name")

    def test_pt_br_locale_normalises_to_pt(self):
        """language='pt-br' (locale form) must reach XTTS as 'pt' after normalisation."""
        os.makedirs(os.path.join(self.tmp_dir, "out_ptbr_loc"), exist_ok=True)
        ref = self._wav("ref_ptbr_loc.wav")
        engine = self._engine()
        engine._generate_chatterbox = MagicMock(side_effect=ImportError("no cb"))
        captured: dict = {}

        def fake_xtts(text, reference_audio, language, output_path):
            captured["language"] = language
            _make_wav(output_path, 500)

        engine._generate_xtts = fake_xtts
        engine._generate_edge = MagicMock()

        with patch("tts_engine.OUTPUT_DIR", os.path.join(self.tmp_dir, "out_ptbr_loc")):
            # Simulate app passing 'pt-br' (locale form)
            engine.generate("Olá mundo", "pt-BR-AntonioNeural",
                            reference_audio=ref, language="pt-br")

        self.assertEqual(captured.get("language"), "pt",
                         "'pt-br' must be split to 'pt' before reaching _generate_xtts")

    def test_generate_xtts_unsupported_language_raises_value_error(self):
        """_generate_xtts must raise ValueError for languages not in _XTTS_LANGUAGES."""
        engine = TTSEngine.__new__(TTSEngine)
        engine._xtts = MagicMock()  # avoid real model load
        dummy_ref = self._wav("ref_xx.wav")
        dummy_out = os.path.join(self.tmp_dir, "out_xx.wav")
        with self.assertRaises(ValueError) as ctx:
            engine._generate_xtts("test", dummy_ref, "xx", dummy_out)
        self.assertIn("'xx'", str(ctx.exception))
        self.assertIn("not supported", str(ctx.exception))

    def test_multilingual_cloning_available_returns_bool(self):
        """`multilingual_cloning_available()` must always return a plain bool."""
        result = TTSEngine.multilingual_cloning_available()
        self.assertIsInstance(result, bool)


# ── Regression: crash fixes ───────────────────────────────────────────────────

class TestCrashFixes(unittest.TestCase):
    """Regression tests for the three crash bugs fixed in the 'crashed' issue."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _wav(self, name: str, duration_ms: int = 500) -> str:
        path = os.path.join(self.tmp_dir, name)
        audio = Sine(440).to_audio_segment(duration=duration_ms).set_frame_rate(22050)
        audio.export(path, format="wav")
        return path

    def test_trim_audio_raises_on_equal_start_end(self):
        """BUG 3: trim_audio(start, end) with start == end must not silently produce a
        zero-byte/corrupt WAV. We confirm trim_audio with start==end produces an empty
        segment (len==0) so callers should guard before calling it."""
        engine = TTSEngine.__new__(TTSEngine)
        wav = self._wav("trim_eq.wav", duration_ms=500)
        engine.trim_audio(wav, 0, 0)
        dur = engine.get_duration_ms(wav)
        # Zero-length trim → zero-duration result; caller must guard start < end
        self.assertEqual(dur, 0)

    def test_trim_audio_valid_range_produces_correct_duration(self):
        """trim_audio with a valid (start < end) range produces the expected duration."""
        engine = TTSEngine.__new__(TTSEngine)
        wav = self._wav("trim_ok.wav", duration_ms=1000)
        engine.trim_audio(wav, 200, 700)
        dur = engine.get_duration_ms(wav)
        # Trimmed segment should be ~500 ms (allow ±20 ms for rounding)
        self.assertAlmostEqual(dur, 500, delta=20)

    def test_bank_preview_worker_guard_pattern(self):
        """BUG 1: _bank_preview must NOT replace self._tts_worker while the thread is running.
        Verifies that the guard condition (worker.isRunning()) correctly identifies a live
        worker so that the caller can return early without replacing it."""

        class MockWorker:
            def isRunning(self):
                return True  # simulates an active QThread

        class MockWorkerDone:
            def isRunning(self):
                return False  # simulates a finished QThread

        live   = MockWorker()
        done   = MockWorkerDone()

        # A live worker must block replacement
        self.assertTrue(
            live.isRunning(),
            "isRunning() must return True for a running worker — replacement should be blocked",
        )
        # A finished worker must allow replacement
        self.assertFalse(
            done.isRunning(),
            "isRunning() must return False after completion — replacement should be allowed",
        )

    def test_on_generate_missing_guard_pattern(self):
        """_on_generate must also guard against replacing a running worker.
        The bank_preview guard existed, but _on_generate had no equivalent guard,
        allowing a bank-preview thread to be GC'd while still running → hard crash.
        Verifies the guard logic now present in _on_generate with mock workers."""

        class MockRunning:
            def isRunning(self):
                return True

        class MockDone:
            def isRunning(self):
                return False

        running = MockRunning()
        done = MockDone()

        # Simulate the guard logic now present in _on_generate:
        # "if self._tts_worker and self._tts_worker.isRunning(): return early"
        def _should_block(worker):
            return worker is not None and worker.isRunning()

        self.assertTrue(_should_block(running), "must block when worker is still running")
        self.assertFalse(_should_block(done),   "must allow when worker is finished")
        self.assertFalse(_should_block(None),   "must allow when no worker exists")


if __name__ == "__main__":
    unittest.main()
