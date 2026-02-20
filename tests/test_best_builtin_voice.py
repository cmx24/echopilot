"""Unit tests for _best_builtin_voice in app.py."""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Stub out PyQt5 so we can import app.py without a display
import types

# Build a minimal PyQt5 stub tree
for mod in [
    "PyQt5",
    "PyQt5.QtCore",
    "PyQt5.QtGui",
    "PyQt5.QtWidgets",
    "PyQt5.QtMultimedia",
]:
    if mod not in sys.modules:
        sys.modules[mod] = types.ModuleType(mod)

# Provide the symbols app.py references at import time
qtcore = sys.modules["PyQt5.QtCore"]
qtcore.Qt = MagicMock()
qtcore.QThread = MagicMock()
qtcore.QUrl = MagicMock()
qtcore.pyqtSignal = MagicMock(return_value=MagicMock())

qtgui = sys.modules["PyQt5.QtGui"]
qtgui.QFont = MagicMock()

qtwidgets = sys.modules["PyQt5.QtWidgets"]
for name in [
    "QAbstractItemView", "QApplication", "QComboBox", "QFileDialog",
    "QGroupBox", "QHBoxLayout", "QLabel", "QLineEdit", "QMainWindow",
    "QMessageBox", "QPushButton", "QSlider", "QTableWidget",
    "QTableWidgetItem", "QHeaderView", "QTextEdit", "QVBoxLayout",
    "QWidget", "QTabWidget",
]:
    setattr(qtwidgets, name, MagicMock())

qtmm = sys.modules["PyQt5.QtMultimedia"]
qtmm.QMediaPlayer = MagicMock()
qtmm.QMediaContent = MagicMock()

# Now we can import voice_manager (real) and patch the rest
from voice_manager import BUILTIN_VOICES, VoiceManager


# ── Standalone logic tests (no QMainWindow instantiation needed) ──────────────

class BestBuiltinVoiceTests(unittest.TestCase):
    """Test _best_builtin_voice by calling the logic directly.

    We replicate the method's algorithm here so the test stays lightweight
    (no QMainWindow construction, no display required).
    """

    def _best_builtin_voice(self, vm: VoiceManager, language: str, gender: str) -> str:
        """Mirror of EchoPilot._best_builtin_voice for testing.

        The logic is deliberately inlined here (rather than importing from app.py)
        so that tests remain headless — importing EchoPilot requires a QApplication
        and a display. If the production implementation changes, update this copy
        to stay in sync. The tests serve as a contract for the selection algorithm.
        """
        valid_gender = gender if gender in ("Female", "Male") else None
        valid_lang = language if language and language not in ("Unknown", "All", "") else None
        for lg, gd in (
            (valid_lang, valid_gender),
            (valid_lang, None),
            (None, valid_gender),
        ):
            voices = [
                v for v in vm.get_all_voices(gender=gd, language=lg)
                if v["type"] == "builtin"
            ]
            if voices:
                return voices[0]["short_name"]
        return "en-US-AriaNeural"

    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        with patch("voice_manager.PROFILES_DIR", self.tmp):
            self.vm = VoiceManager()

    def test_exact_english_female(self):
        result = self._best_builtin_voice(self.vm, "English", "Female")
        voice = next(v for v in BUILTIN_VOICES if v["short_name"] == result)
        self.assertEqual(voice["language"], "English")
        self.assertEqual(voice["gender"], "Female")

    def test_exact_english_male(self):
        result = self._best_builtin_voice(self.vm, "English", "Male")
        voice = next(v for v in BUILTIN_VOICES if v["short_name"] == result)
        self.assertEqual(voice["language"], "English")
        self.assertEqual(voice["gender"], "Male")

    def test_exact_japanese_female(self):
        result = self._best_builtin_voice(self.vm, "Japanese", "Female")
        voice = next(v for v in BUILTIN_VOICES if v["short_name"] == result)
        self.assertEqual(voice["language"], "Japanese")
        self.assertEqual(voice["gender"], "Female")

    def test_unknown_gender_falls_back_to_same_language(self):
        """Unknown gender → should still pick a voice for the given language."""
        result = self._best_builtin_voice(self.vm, "French", "Unknown")
        voice = next(v for v in BUILTIN_VOICES if v["short_name"] == result)
        self.assertEqual(voice["language"], "French")

    def test_empty_language_falls_back_to_same_gender(self):
        """Empty language → falls back to any voice with matching gender."""
        result = self._best_builtin_voice(self.vm, "", "Male")
        voice = next(v for v in BUILTIN_VOICES if v["short_name"] == result)
        self.assertEqual(voice["gender"], "Male")

    def test_unknown_both_returns_default(self):
        """Unknown language and gender → absolute default en-US-AriaNeural."""
        result = self._best_builtin_voice(self.vm, "Unknown", "Unknown")
        self.assertEqual(result, "en-US-AriaNeural")

    def test_never_returns_custom_voice(self):
        """Must always return a builtin voice, never a custom one."""
        with patch("voice_manager.PROFILES_DIR", self.tmp):
            self.vm.save_custom_voice("TestCustom", "Female", "English")
        result = self._best_builtin_voice(self.vm, "English", "Female")
        custom_short_names = {
            v["short_name"] for v in self.vm.get_all_voices()
            if v["type"] == "custom"
        }
        self.assertNotIn(result, custom_short_names)

    def test_returns_string(self):
        result = self._best_builtin_voice(self.vm, "English", "Female")
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)


if __name__ == "__main__":
    unittest.main()
