"""Unit tests for voice_manager.VoiceManager."""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from voice_manager import (
    BUILTIN_VOICES,
    LANGUAGE_MAP,
    LOCALE_MAP,
    VoiceManager,
)


class TestBuiltinVoiceData(unittest.TestCase):
    """Validate the integrity of the static built-in voice list."""

    def test_builtin_voices_not_empty(self):
        self.assertGreater(len(BUILTIN_VOICES), 0)

    def test_every_builtin_has_required_keys(self):
        required = {"name", "short_name", "gender", "language", "type"}
        for v in BUILTIN_VOICES:
            missing = required - v.keys()
            self.assertFalse(missing, f"Voice {v.get('name')} missing keys: {missing}")

    def test_all_builtins_have_type_builtin(self):
        for v in BUILTIN_VOICES:
            self.assertEqual(v["type"], "builtin", f"{v['name']} has wrong type")

    def test_gender_values_are_valid(self):
        valid = {"Female", "Male"}
        for v in BUILTIN_VOICES:
            self.assertIn(v["gender"], valid, f"{v['name']} has unexpected gender")

    def test_short_names_are_unique(self):
        short_names = [v["short_name"] for v in BUILTIN_VOICES]
        self.assertEqual(len(short_names), len(set(short_names)), "Duplicate short_name found")


class TestVoiceManagerFilters(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        with patch("voice_manager.PROFILES_DIR", self.tmp_dir):
            self.vm = VoiceManager()

    def test_get_all_voices_no_filter_returns_all_builtins(self):
        voices = self.vm.get_all_voices()
        names = [v["name"] for v in voices]
        for bv in BUILTIN_VOICES:
            self.assertIn(bv["name"], names)

    def test_get_all_voices_filter_female(self):
        voices = self.vm.get_all_voices(gender="Female")
        for v in voices:
            self.assertEqual(v["gender"].lower(), "female")

    def test_get_all_voices_filter_male(self):
        voices = self.vm.get_all_voices(gender="Male")
        for v in voices:
            self.assertEqual(v["gender"].lower(), "male")

    def test_get_all_voices_filter_english(self):
        voices = self.vm.get_all_voices(language="English")
        for v in voices:
            self.assertEqual(v["language"].lower(), "english")

    def test_get_all_voices_filter_all_gender(self):
        """Passing gender='All' must behave identically to no filter."""
        voices_all = self.vm.get_all_voices(gender="All")
        voices_none = self.vm.get_all_voices()
        self.assertEqual(len(voices_all), len(voices_none))

    def test_get_all_voices_combined_filter(self):
        voices = self.vm.get_all_voices(gender="Male", language="English")
        for v in voices:
            self.assertEqual(v["gender"].lower(), "male")
            self.assertEqual(v["language"].lower(), "english")

    def test_get_all_genders(self):
        genders = self.vm.get_all_genders()
        self.assertIn("All", genders)
        self.assertIn("Female", genders)
        self.assertIn("Male", genders)

    def test_get_all_languages_contains_english(self):
        langs = self.vm.get_all_languages()
        self.assertIn("All", langs)
        self.assertIn("English", langs)

    def test_get_all_languages_sorted(self):
        langs = self.vm.get_all_languages()
        # "All" is first; the rest should be sorted
        rest = langs[1:]
        self.assertEqual(rest, sorted(rest))


class TestVoiceManagerCustomProfiles(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        with patch("voice_manager.PROFILES_DIR", self.tmp_dir):
            self.vm = VoiceManager()

    # ── save_custom_voice ─────────────────────────────────────────────────────

    def test_save_custom_voice_returns_dict(self):
        with patch("voice_manager.PROFILES_DIR", self.tmp_dir):
            profile = self.vm.save_custom_voice("Test Voice", "Female", "English")
        self.assertIsInstance(profile, dict)
        self.assertEqual(profile["name"], "Test Voice")

    def test_save_custom_voice_persists_json(self):
        with patch("voice_manager.PROFILES_DIR", self.tmp_dir):
            self.vm.save_custom_voice("Persist Voice", "Male", "French")
        files = [f for f in os.listdir(self.tmp_dir) if f.endswith(".json")]
        self.assertTrue(any("Persist Voice" in f for f in files))

    def test_save_custom_voice_stores_all_fields(self):
        with patch("voice_manager.PROFILES_DIR", self.tmp_dir):
            profile = self.vm.save_custom_voice(
                "Full Profile", "Female", "German",
                reference_audio="/tmp/ref.wav", notes="Test note",
            )
        self.assertEqual(profile["gender"], "Female")
        self.assertEqual(profile["language"], "German")
        self.assertEqual(profile["reference_audio"], "/tmp/ref.wav")
        self.assertEqual(profile["notes"], "Test note")
        self.assertEqual(profile["type"], "custom")
        self.assertIn("created", profile)

    def test_save_custom_voice_appears_in_get_all_voices(self):
        with patch("voice_manager.PROFILES_DIR", self.tmp_dir):
            self.vm.save_custom_voice("My Voice", "Female", "English")
        names = [v["name"] for v in self.vm.get_all_voices()]
        self.assertIn("My Voice", names)

    def test_save_custom_voice_invalid_name_raises(self):
        with patch("voice_manager.PROFILES_DIR", self.tmp_dir):
            with self.assertRaises(ValueError):
                self.vm.save_custom_voice("!!!###", "Female", "English")

    def test_save_custom_voice_short_name_lowercase(self):
        with patch("voice_manager.PROFILES_DIR", self.tmp_dir):
            profile = self.vm.save_custom_voice("Hello World", "Male", "English")
        self.assertEqual(profile["short_name"], "hello_world")

    # ── delete_custom_voice ───────────────────────────────────────────────────

    def test_delete_custom_voice_removes_from_memory(self):
        with patch("voice_manager.PROFILES_DIR", self.tmp_dir):
            self.vm.save_custom_voice("Delete Me", "Female", "English")
            self.vm.delete_custom_voice("Delete Me")
        names = [v["name"] for v in self.vm.get_all_voices()]
        self.assertNotIn("Delete Me", names)

    def test_delete_custom_voice_removes_json_file(self):
        with patch("voice_manager.PROFILES_DIR", self.tmp_dir):
            self.vm.save_custom_voice("Del File", "Male", "Spanish")
            fpath = os.path.join(self.tmp_dir, "Del File.json")
            self.assertTrue(os.path.isfile(fpath))
            self.vm.delete_custom_voice("Del File")
        self.assertFalse(os.path.isfile(fpath))

    def test_delete_nonexistent_voice_is_noop(self):
        """Deleting a voice that doesn't exist must not raise."""
        with patch("voice_manager.PROFILES_DIR", self.tmp_dir):
            self.vm.delete_custom_voice("Nonexistent")

    # ── profile reload from disk ──────────────────────────────────────────────

    def test_load_custom_profiles_from_disk(self):
        """A JSON file written manually must be picked up on init."""
        profile = {
            "name": "Disk Voice",
            "short_name": "disk_voice",
            "gender": "Female",
            "language": "Italian",
            "type": "custom",
            "reference_audio": "",
            "notes": "",
            "created": "2024-01-01T00:00:00+00:00",
        }
        fpath = os.path.join(self.tmp_dir, "Disk Voice.json")
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(profile, f)

        with patch("voice_manager.PROFILES_DIR", self.tmp_dir):
            vm2 = VoiceManager()
        names = [v["name"] for v in vm2.get_all_voices()]
        self.assertIn("Disk Voice", names)

    def test_malformed_json_is_skipped(self):
        """A malformed JSON file must be silently skipped."""
        bad = os.path.join(self.tmp_dir, "bad.json")
        with open(bad, "w") as f:
            f.write("{not valid json}")
        with patch("voice_manager.PROFILES_DIR", self.tmp_dir):
            vm2 = VoiceManager()  # must not raise
        self.assertIsInstance(vm2, VoiceManager)


class TestLanguageDetection(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        with patch("voice_manager.PROFILES_DIR", self.tmp_dir):
            self.vm = VoiceManager()

    def test_detect_english_text(self):
        lang = self.vm.detect_language_from_text(
            "The quick brown fox jumps over the lazy dog"
        )
        self.assertEqual(lang, "English")

    def test_detect_returns_string(self):
        result = self.vm.detect_language_from_text("Hello world")
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)

    def test_detect_empty_falls_back_to_english(self):
        result = self.vm.detect_language_from_text("   ")
        self.assertEqual(result, "English")

    def test_detect_unknown_code_returns_uppercase_code(self):
        """If langdetect returns a code not in LANGUAGE_MAP the code is
        returned uppercased (current behaviour)."""
        with patch("voice_manager._langdetect", return_value="xx"):
            result = self.vm.detect_language_from_text("whatever")
        self.assertEqual(result, "XX")


class TestLocaleMapping(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        with patch("voice_manager.PROFILES_DIR", self.tmp_dir):
            self.vm = VoiceManager()

    def test_english_maps_to_en_us(self):
        self.assertEqual(self.vm.get_locale_for_language("English"), "en-US")

    def test_french_maps_to_fr_fr(self):
        self.assertEqual(self.vm.get_locale_for_language("French"), "fr-FR")

    def test_japanese_maps_to_ja_jp(self):
        self.assertEqual(self.vm.get_locale_for_language("Japanese"), "ja-JP")

    def test_unknown_language_defaults_to_en_us(self):
        self.assertEqual(self.vm.get_locale_for_language("Klingon"), "en-US")


class TestGenderDetection(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        with patch("voice_manager.PROFILES_DIR", self.tmp_dir):
            self.vm = VoiceManager()

    def _make_wav(self, path: str, duration_ms: int = 500) -> str:
        from pydub.generators import Sine
        from pydub import AudioSegment
        audio = Sine(440).to_audio_segment(duration=duration_ms)
        audio.export(path, format="wav")
        return path

    def test_detect_gender_returns_string(self):
        wav = self._make_wav(os.path.join(self.tmp_dir, "audio.wav"))
        result = self.vm.detect_gender_from_audio(wav)
        self.assertIn(result, ("Male", "Female", "Unknown"))

    def test_detect_gender_high_f0_returns_female(self):
        """Mock librosa.pyin to return a high F0 → Female."""
        import librosa
        high_f0 = np.array([250.0, 260.0, 240.0])
        voiced = np.array([True, True, True])
        wav = self._make_wav(os.path.join(self.tmp_dir, "hi_f0.wav"))
        with patch("voice_manager.librosa") as mock_lib:
            mock_lib.load.return_value = (np.zeros(22050), 22050)
            mock_lib.note_to_hz.return_value = 100.0
            mock_lib.pyin.return_value = (high_f0, voiced, None)
            result = self.vm.detect_gender_from_audio(wav)
        self.assertEqual(result, "Female")

    def test_detect_gender_low_f0_returns_male(self):
        """Mock librosa.pyin to return a low F0 → Male."""
        low_f0 = np.array([110.0, 120.0, 115.0])
        voiced = np.array([True, True, True])
        wav = self._make_wav(os.path.join(self.tmp_dir, "lo_f0.wav"))
        with patch("voice_manager.librosa") as mock_lib:
            mock_lib.load.return_value = (np.zeros(22050), 22050)
            mock_lib.note_to_hz.return_value = 100.0
            mock_lib.pyin.return_value = (low_f0, voiced, None)
            result = self.vm.detect_gender_from_audio(wav)
        self.assertEqual(result, "Male")

    def test_detect_gender_unvoiced_returns_unknown(self):
        """No voiced frames → Unknown."""
        f0 = np.array([200.0, 250.0])
        voiced = np.array([False, False])
        wav = self._make_wav(os.path.join(self.tmp_dir, "unvoiced.wav"))
        with patch("voice_manager.librosa") as mock_lib:
            mock_lib.load.return_value = (np.zeros(22050), 22050)
            mock_lib.note_to_hz.return_value = 100.0
            mock_lib.pyin.return_value = (f0, voiced, None)
            result = self.vm.detect_gender_from_audio(wav)
        self.assertEqual(result, "Unknown")

    def test_detect_gender_exception_returns_unknown(self):
        """Any exception inside the method must be swallowed → Unknown."""
        with patch("voice_manager.librosa") as mock_lib:
            mock_lib.load.side_effect = RuntimeError("cannot load audio")
            wav = self._make_wav(os.path.join(self.tmp_dir, "err.wav"))
            result = self.vm.detect_gender_from_audio(wav)
        self.assertEqual(result, "Unknown")


if __name__ == "__main__":
    unittest.main()
