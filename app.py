"""EchoPilot — Text-to-Speech Studio (PyQt5 GUI)."""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile

from PyQt5.QtCore import Qt, QSettings, QThread, QUrl, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QTabWidget,
)

try:
    from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
    _HAS_QTMULTIMEDIA = True
except (ImportError, RuntimeError):
    _HAS_QTMULTIMEDIA = False

from tts_engine import TTSEngine, TONES
from voice_manager import VoiceManager

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# ── Worker threads ────────────────────────────────────────────────────────────

class TTSWorker(QThread):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, engine: TTSEngine, params: dict):
        super().__init__()
        self.engine = engine
        self.params = params

    def run(self):
        try:
            self.finished.emit(self.engine.generate(**self.params))
        except Exception as exc:
            self.error.emit(str(exc))


class AnalyzeWorker(QThread):
    result = pyqtSignal(str)   # detected gender
    error = pyqtSignal(str)

    def __init__(self, vm: VoiceManager, audio_path: str):
        super().__init__()
        self.vm = vm
        self.audio_path = audio_path

    def run(self):
        try:
            self.result.emit(self.vm.detect_gender_from_audio(self.audio_path))
        except Exception as exc:
            self.error.emit(str(exc))


# ── Main window ───────────────────────────────────────────────────────────────

class EchoPilot(QMainWindow):
    _STYLE = """
        QMainWindow, QWidget { background-color: #1e1e2e; color: #cdd6f4; font-size: 13px; }
        QTabWidget::pane { border: none; background: #1e1e2e; }
        QTabBar::tab {
            background: #313244; color: #cdd6f4; padding: 8px 18px;
            border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px;
            font-weight: bold;
        }
        QTabBar::tab:selected { background: #45475a; color: #89b4fa; }
        QGroupBox {
            border: 1px solid #45475a; border-radius: 6px; margin-top: 10px;
            padding: 6px; font-weight: bold; color: #89b4fa;
        }
        QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
        QPushButton {
            background-color: #89b4fa; color: #1e1e2e; border: none;
            border-radius: 5px; padding: 6px 16px; font-weight: bold;
        }
        QPushButton:hover { background-color: #b4befe; }
        QPushButton:disabled { background-color: #45475a; color: #6c7086; }
        QTextEdit, QLineEdit {
            background: #313244; color: #cdd6f4;
            border: 1px solid #45475a; border-radius: 4px; padding: 4px;
        }
        QComboBox {
            background: #313244; color: #cdd6f4;
            border: 1px solid #45475a; border-radius: 4px; padding: 4px; min-width: 120px;
        }
        QComboBox QAbstractItemView { background: #313244; color: #cdd6f4; }
        QSlider::groove:horizontal {
            height: 6px; background: #45475a; border-radius: 3px;
        }
        QSlider::handle:horizontal {
            width: 16px; height: 16px; background: #89b4fa;
            border-radius: 8px; margin: -5px 0;
        }
        QSlider::sub-page:horizontal { background: #89b4fa; border-radius: 3px; }
        QTableWidget {
            background: #313244; color: #cdd6f4;
            gridline-color: #45475a; border: none; alternate-background-color: #2a2a3e;
        }
        QHeaderView::section {
            background-color: #45475a; color: #89b4fa;
            padding: 6px; border: none; font-weight: bold;
        }
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("EchoPilot — TTS Studio")
        self.setMinimumSize(920, 680)
        self.vm = VoiceManager()
        self.engine = TTSEngine()
        self._current_audio: str = None
        self._edit_audio: str = None
        self._tts_worker: TTSWorker = None
        self._analyze_worker: AnalyzeWorker = None
        self._play_proc: subprocess.Popen = None
        self._font_size: int = 13
        self._cloning_backend: str | None = TTSEngine.cloning_backend()
        self._cloning_warn_shown: bool = False   # only show the install-instructions dialog once

        # In-app audio player (avoids launching the system media app)
        if _HAS_QTMULTIMEDIA:
            try:
                self._player = QMediaPlayer()
                self._player.error.connect(
                    lambda e: QMessageBox.warning(
                        self, "Playback Error",
                        self._player.errorString() or f"Playback error {e}",
                    )
                )
            except Exception:
                self._player = None
        else:
            self._player = None

        tabs = QTabWidget()
        self.setCentralWidget(tabs)
        tabs.addTab(self._build_generate_tab(),  "🎙  Generate")
        tabs.addTab(self._build_clone_tab(),      "🧬  Clone Voice")
        tabs.addTab(self._build_bank_tab(),       "📂  Voice Bank")
        tabs.addTab(self._build_edit_tab(),       "✂   Edit & Save")
        self.setStyleSheet(self._STYLE)

        # Restore settings from previous session
        self._restore_settings()

        # Warn at startup if no voice cloning backend is available
        if self._cloning_backend is None:
            py = sys.version_info
            if py >= (3, 12):
                self.statusBar().showMessage(
                    f"⚠ Voice cloning unavailable on Python {py.major}.{py.minor} "
                    f"— re-run setup.bat to auto-install Python 3.11 and enable cloning.",
                    0,
                )
            else:
                self.statusBar().showMessage(
                    "⚠ Voice cloning package not installed — re-run setup.bat to enable it.",
                    0,
                )

    # ── Settings persistence ──────────────────────────────────────────────────

    _SETTINGS_ORG  = "EchoPilot"
    _SETTINGS_APP  = "TTS Studio"

    def _save_settings(self):
        """Persist Generate-tab state so it survives app restarts."""
        try:
            s = QSettings(self._SETTINGS_ORG, self._SETTINGS_APP)
            s.setValue("gen/text",      self.gen_text.toPlainText())
            s.setValue("gen/lang",      self.gen_lang_combo.currentText())
            s.setValue("gen/gender",    self.gen_gender_combo.currentText())
            s.setValue("gen/voice",     self.gen_voice_combo.currentText())
            s.setValue("gen/tone",      self.gen_tone_combo.currentText())
            s.setValue("gen/mood",      self.gen_mood_slider.value())
            s.setValue("app/font_size", self._font_size)
            s.sync()
        except Exception:  # noqa: BLE001 — best-effort; never crash on save
            pass

    def _restore_settings(self):
        """Reload persisted Generate-tab state after widgets are built."""
        s = QSettings(self._SETTINGS_ORG, self._SETTINGS_APP)

        text = s.value("gen/text", "")
        if text:
            self.gen_text.setPlainText(text)

        # Language + Gender — must come before voice repopulation
        for combo, key in (
            (self.gen_lang_combo,   "gen/lang"),
            (self.gen_gender_combo, "gen/gender"),
        ):
            val = s.value(key, "")
            if val:
                idx = combo.findText(val)
                if idx >= 0:
                    combo.setCurrentIndex(idx)

        # Repopulate voice list for restored language/gender, then restore voice
        self._populate_gen_voice_combo()
        voice_text = s.value("gen/voice", "")
        if voice_text:
            idx = self.gen_voice_combo.findText(voice_text)
            if idx >= 0:
                self.gen_voice_combo.setCurrentIndex(idx)

        tone = s.value("gen/tone", "")
        if tone:
            idx = self.gen_tone_combo.findText(tone)
            if idx >= 0:
                self.gen_tone_combo.setCurrentIndex(idx)

        mood = s.value("gen/mood", None)
        if mood is not None:
            try:
                self.gen_mood_slider.setValue(int(mood))
            except (TypeError, ValueError):
                pass

        font = s.value("app/font_size", None)
        if font is not None:
            try:
                self._font_size = max(9, min(24, int(font)))
                self._apply_font_size()
            except (TypeError, ValueError):
                pass

    def closeEvent(self, event):
        self._save_settings()
        super().closeEvent(event)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _play_file(self, path: str):
        """Play *path* inside the app via QMediaPlayer; subprocess fallback on Linux/macOS."""
        self._stop_playback()
        if not path or not os.path.isfile(path):
            return
        if self._player is not None:
            self._player.setMedia(
                QMediaContent(QUrl.fromLocalFile(os.path.abspath(path)))
            )
            self._player.play()
            return
        # Subprocess fallback (Linux / macOS — these don't open a GUI window)
        system = platform.system()
        try:
            if system == "Linux":
                for player in ("ffplay", "aplay", "paplay", "mpv", "mplayer"):
                    if shutil.which(player):
                        args = [player]
                        if player == "ffplay":
                            args += ["-nodisp", "-autoexit", "-loglevel", "quiet"]
                        self._play_proc = subprocess.Popen(
                            args + [path],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                        return
                QMessageBox.warning(
                    self, "Playback Error",
                    "No audio player found. Install ffplay, aplay, or mpv.",
                )
            elif system == "Darwin":
                self._play_proc = subprocess.Popen(["afplay", path])
        except Exception as exc:
            QMessageBox.warning(self, "Playback Error", str(exc))

    def _stop_playback(self):
        if self._player is not None:
            self._player.stop()
        if self._play_proc and self._play_proc.poll() is None:
            self._play_proc.terminate()
        self._play_proc = None

    # ── Zoom support (Ctrl + mouse-wheel) ─────────────────────────────────────

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            self._font_size = max(9, min(24, self._font_size + (1 if delta > 0 else -1)))
            self._apply_font_size()
            event.accept()
        else:
            super().wheelEvent(event)

    def _apply_font_size(self):
        style = re.sub(r'font-size:\s*\d+px', f'font-size: {self._font_size}px', self._STYLE)
        self.setStyleSheet(style)

    # ── Voice helpers ─────────────────────────────────────────────────────────

    def _best_builtin_voice(self, language: str, gender: str) -> str:
        """Return the short_name of the best built-in voice for *language* / *gender*.

        Tries in order: exact language+gender → same language any gender →
        any language same gender → absolute default.
        """
        valid_gender = gender if gender in ("Female", "Male") else None
        valid_lang = language if language and language not in ("Unknown", "All", "") else None
        for lg, gd in (
            (valid_lang, valid_gender),
            (valid_lang, None),
            (None, valid_gender),
        ):
            voices = [
                v for v in self.vm.get_all_voices(gender=gd, language=lg)
                if v["type"] == "builtin"
            ]
            if voices:
                return voices[0]["short_name"]
        return "en-US-AriaNeural"

    @staticmethod
    def _hbox(*widgets) -> QHBoxLayout:
        row = QHBoxLayout()
        for w in widgets:
            if w is None:
                row.addStretch()
            else:
                row.addWidget(w)
        return row

    # ══════════════════════════════════════════════════════════════════════════
    # Tab 1 — Generate
    # ══════════════════════════════════════════════════════════════════════════

    def _build_generate_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # — Text input —
        text_grp = QGroupBox("Text to Speak")
        tl = QVBoxLayout(text_grp)
        self.gen_text = QTextEdit()
        self.gen_text.setPlaceholderText("Type or paste the text you want to synthesise…")
        self.gen_text.setMinimumHeight(100)
        tl.addWidget(self.gen_text)
        layout.addWidget(text_grp)

        # — Voice & settings —
        vc_grp = QGroupBox("Voice & Settings")
        vl = QVBoxLayout(vc_grp)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Voice:"))
        self.gen_voice_combo = QComboBox()
        self.gen_voice_combo.setMinimumWidth(210)
        row1.addWidget(self.gen_voice_combo)
        row1.addWidget(QLabel("Language:"))
        self.gen_lang_combo = QComboBox()
        row1.addWidget(self.gen_lang_combo)
        row1.addWidget(QLabel("Gender:"))
        self.gen_gender_combo = QComboBox()
        row1.addWidget(self.gen_gender_combo)
        row1.addStretch()
        vl.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Tone:"))
        self.gen_tone_combo = QComboBox()
        self.gen_tone_combo.addItems(TONES)
        row2.addWidget(self.gen_tone_combo)
        row2.addWidget(QLabel("Mood (1–10):"))
        self.gen_mood_slider = QSlider(Qt.Horizontal)
        self.gen_mood_slider.setRange(1, 10)
        self.gen_mood_slider.setValue(5)
        self.gen_mood_slider.setMaximumWidth(200)
        self.gen_mood_slider.setTickPosition(QSlider.TicksBelow)
        self.gen_mood_slider.setTickInterval(1)
        row2.addWidget(self.gen_mood_slider)
        self.gen_mood_val = QLabel("5")
        self.gen_mood_val.setMinimumWidth(20)
        self.gen_mood_slider.valueChanged.connect(lambda v: self.gen_mood_val.setText(str(v)))
        row2.addWidget(self.gen_mood_val)
        row2.addStretch()
        vl.addLayout(row2)
        layout.addWidget(vc_grp)

        # — Generate button —
        row3 = QHBoxLayout()
        self.gen_btn = QPushButton("▶  Generate Speech")
        self.gen_btn.setMinimumHeight(36)
        self.gen_btn.clicked.connect(self._on_generate)
        row3.addWidget(self.gen_btn)
        self.gen_status = QLabel("")
        row3.addWidget(self.gen_status)
        row3.addStretch()
        layout.addLayout(row3)

        # — Playback / export —
        pb_grp = QGroupBox("Playback & Export")
        pl = QHBoxLayout(pb_grp)
        self.gen_play_btn = QPushButton("▶  Play")
        self.gen_play_btn.setEnabled(False)
        self.gen_play_btn.clicked.connect(lambda: self._play_file(self._current_audio))
        pl.addWidget(self.gen_play_btn)
        self.gen_stop_btn = QPushButton("■  Stop")
        self.gen_stop_btn.setEnabled(False)
        self.gen_stop_btn.clicked.connect(self._stop_playback)
        pl.addWidget(self.gen_stop_btn)
        self.gen_save_btn = QPushButton("💾  Save Audio…")
        self.gen_save_btn.setEnabled(False)
        self.gen_save_btn.clicked.connect(self._save_current_audio)
        pl.addWidget(self.gen_save_btn)
        self.gen_audio_info = QLabel("No audio generated yet.")
        pl.addWidget(self.gen_audio_info)
        pl.addStretch()
        layout.addWidget(pb_grp)

        layout.addStretch()

        # populate filters
        self._refresh_gen_filters()
        self.gen_lang_combo.currentTextChanged.connect(self._populate_gen_voice_combo)
        self.gen_gender_combo.currentTextChanged.connect(self._populate_gen_voice_combo)
        return tab

    def _refresh_gen_filters(self):
        for combo, getter in (
            (self.gen_lang_combo,    self.vm.get_all_languages),
            (self.gen_gender_combo,  self.vm.get_all_genders),
        ):
            cur = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(getter())
            idx = combo.findText(cur)
            combo.setCurrentIndex(max(0, idx))
            combo.blockSignals(False)
        self._populate_gen_voice_combo()

    def _populate_gen_voice_combo(self):
        lang   = self.gen_lang_combo.currentText()
        gender = self.gen_gender_combo.currentText()
        voices = self.vm.get_all_voices(
            gender=None if gender == "All" else gender,
            language=None if lang == "All" else lang,
        )
        self.gen_voice_combo.blockSignals(True)
        self.gen_voice_combo.clear()
        for v in voices:
            tag = "🔵" if v["type"] == "builtin" else "🟢"
            self.gen_voice_combo.addItem(f"{tag} {v['name']}", v)
        self.gen_voice_combo.blockSignals(False)

    def _resolve_lang_code(self, profile_language: str, text: str) -> str:
        """Return a 2-letter language code for cloning backends.

        Priority:
        1. Language saved in the voice profile (if set and not placeholder)
        2. Language currently selected in the Generate tab filter (if not "All")
        3. Auto-detect from the input text via langdetect (returns a code directly)
        4. Hard fallback: "en"

        ``profile_language`` and the combo value are display names (e.g. "French").
        langdetect returns 2-letter codes (e.g. "fr") — those are used directly
        without going through ``get_locale_for_language``.
        """
        # Steps 1 and 2 — display names (e.g. "French")
        display_name: str | None = None
        if profile_language and profile_language not in ("", "Unknown", "All"):
            display_name = profile_language
        if display_name is None:
            combo_lang = self.gen_lang_combo.currentText()
            if combo_lang not in ("", "All"):
                display_name = combo_lang

        if display_name is not None:
            locale = self.vm.get_locale_for_language(display_name).lower()
            if locale.startswith("zh"):
                return "zh-cn"
            return locale.split("-")[0] or "en"

        # Step 3 — langdetect returns a BCP-47 code like "fr" directly
        try:
            from langdetect import detect as _ld, LangDetectException  # noqa: PLC0415
            code = (_ld(text[:500]) or "en").lower()
        except (ImportError, LangDetectException):
            code = "en"

        if code.startswith("zh"):
            return "zh-cn"
        return code.split("-")[0] or "en"

    def _on_generate(self):
        # Guard: do not replace a still-running worker — GC of a live QThread crashes PyQt5.
        # This can happen if a Bank tab preview is in progress and the user switches to
        # Generate and clicks Generate before the preview thread finishes.
        if self._tts_worker and self._tts_worker.isRunning():
            QMessageBox.information(
                self, "Busy",
                "Please wait for the current operation to finish before generating.",
            )
            return

        text = self.gen_text.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "Empty Text", "Please enter some text to synthesise.")
            return
        voice_data = self.gen_voice_combo.currentData()
        if voice_data is None:
            QMessageBox.warning(self, "No Voice", "Please select a voice.")
            return

        params = {
            "text": text,
            "tone": self.gen_tone_combo.currentText(),
            "mood": self.gen_mood_slider.value(),
        }

        if voice_data.get("type") == "custom":
            language = voice_data.get("language", "")
            gender = voice_data.get("gender", "")
            short_name = self._best_builtin_voice(language, gender)
            params["voice_short_name"] = short_name

            ref = voice_data.get("reference_audio", "")
            if ref and os.path.isfile(ref):
                # Derive the 2-letter language code via priority fallback
                lang_code = self._resolve_lang_code(language, text)
                params["reference_audio"] = ref
                params["language"] = lang_code
                if lang_code == "en":
                    hint = "⏳ Cloning voice (English)… first run downloads ~400 MB"
                else:
                    hint = (
                        f"⏳ Cloning voice ({lang_code.upper()}) via XTTS v2…"
                        " first run downloads ~2 GB"
                    )
                self.gen_status.setText(hint)
            else:
                self.gen_status.setText(f"ℹ No reference audio — using {short_name}")
        else:
            params["voice_short_name"] = voice_data.get("short_name", "en-US-AriaNeural")

        self.gen_btn.setEnabled(False)
        self.gen_play_btn.setEnabled(False)
        self.gen_save_btn.setEnabled(False)
        if "⏳" not in self.gen_status.text():
            self.gen_status.setText("⏳ Generating…")

        self._tts_worker = TTSWorker(self.engine, params)
        self._tts_worker.finished.connect(self._on_generate_done)
        self._tts_worker.error.connect(self._on_generate_error)
        self._tts_worker.start()

    def _on_generate_done(self, path: str):
        self._current_audio = path
        dur = self.engine.get_duration_ms(path) / 1000.0
        self.gen_audio_info.setText(f"✔ {os.path.basename(path)}  ({dur:.1f} s)")

        backend = self.engine._last_backend
        errors  = self.engine._last_clone_errors
        if backend in ("chatterbox", "xtts"):
            label = "ChatterboxTTS" if backend == "chatterbox" else "XTTS v2"
            self.gen_status.setText(f"✔ Done — voice cloned with {label}")
        elif errors:
            # Cloning was attempted but fell back; show actionable information
            reason = errors[0].split(":")[0]   # e.g. "ChatterboxTTS not installed"
            self.gen_status.setText(f"⚠ Cloning failed ({reason}) — used {backend}")
            # Show the dialog once per session for ANY cloning failure
            # (not just "not installed" — also covers TosAgreementError, CUDA errors, etc.)
            if not self._cloning_warn_shown:
                self._cloning_warn_shown = True
                detail = "\n".join(f"  • {e}" for e in errors)
                is_missing = any("not installed" in e for e in errors)
                if is_missing:
                    hint = TTSEngine.cloning_install_instructions()
                else:
                    hint = ("Re-run setup.bat if the error persists, or check your internet "
                            "connection (XTTS v2 downloads ~2 GB on first use).")
                body = (
                    "⚠  Voice cloning failed — the output uses a standard neural voice "
                    "and does NOT sound like your reference speaker.\n\n"
                    f"Error detail:\n{detail}\n\n{hint}"
                )
                QMessageBox.warning(self, "Voice Cloning Failed", body)
        else:
            self.gen_status.setText(f"✔ Done — {backend}")

        self.gen_btn.setEnabled(True)
        self.gen_play_btn.setEnabled(True)
        self.gen_stop_btn.setEnabled(True)
        self.gen_save_btn.setEnabled(True)

    def _on_generate_error(self, msg: str):
        self.gen_status.setText("✘ Error")
        self.gen_btn.setEnabled(True)
        self.gen_play_btn.setEnabled(self._current_audio is not None)
        self.gen_stop_btn.setEnabled(True)
        self.gen_save_btn.setEnabled(self._current_audio is not None)
        QMessageBox.critical(self, "Generation Error", msg)

    def _save_current_audio(self):
        if not self._current_audio or not os.path.isfile(self._current_audio):
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Audio", "speech.wav",
            "WAV files (*.wav);;MP3 files (*.mp3);;All Files (*)",
        )
        if not path:
            return
        fmt = "mp3" if path.lower().endswith(".mp3") else "wav"
        try:
            self.engine.save_as(self._current_audio, path, fmt)
            QMessageBox.information(self, "Saved", f"Saved to:\n{path}")
        except Exception as exc:  # pydub raises various errors (CouldntEncodeError, OSError…)
            QMessageBox.critical(self, "Save Error", str(exc))

    # ══════════════════════════════════════════════════════════════════════════
    # Tab 2 — Clone Voice
    # ══════════════════════════════════════════════════════════════════════════

    def _build_clone_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # — Reference audio —
        ref_grp = QGroupBox("Reference Audio  (mp3 / wav)")
        rl = QVBoxLayout(ref_grp)
        row = QHBoxLayout()
        self.clone_file_edit = QLineEdit()
        self.clone_file_edit.setReadOnly(True)
        self.clone_file_edit.setPlaceholderText("Select a speaker reference audio file…")
        row.addWidget(self.clone_file_edit)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_reference)
        row.addWidget(browse_btn)
        rl.addLayout(row)

        # Duration + quality hint row
        dur_row = QHBoxLayout()
        self.clone_ref_duration = QLabel("Duration: —  |  Recommend ≥ 5 s of clean speech for best cloning")
        self.clone_ref_duration.setStyleSheet("color: #a6adc8; font-size: 11px;")
        dur_row.addWidget(self.clone_ref_duration)
        dur_row.addStretch()
        rl.addLayout(dur_row)

        # Cloning backend availability banner
        if self._cloning_backend is None:
            py = sys.version_info
            warn_label = QLabel(
                f"⚠  Voice cloning is NOT available — "
                + (
                    f"Python {py.major}.{py.minor} detected.  "
                    "Re-run setup.bat — it will automatically install Python 3.11 and enable cloning."
                    if py >= (3, 12) else
                    "Re-run setup.bat to install the chatterbox-tts package."
                )
            )
            warn_label.setStyleSheet(
                "color: #f38ba8; font-size: 11px; font-weight: bold; "
                "padding: 4px; background: #45475a; border-radius: 4px;"
            )
            warn_label.setWordWrap(True)
            rl.addWidget(warn_label)
        else:
            xtts_ok = TTSEngine.multilingual_cloning_available()
            if xtts_ok:
                # Language sample list mirrors TTSEngine._XTTS_LANGUAGES subset
                banner_text = (
                    "✔  Voice cloning ready  ·  "
                    "English (Chatterbox, ~400 MB on first use)  ·  "
                    "Multilingual pt-BR / fr / es / zh / … (XTTS v2, ~2 GB on first use)"
                )
                banner_style = "color: #a6e3a1; font-size: 11px;"
            else:
                # Language sample list mirrors TTSEngine._XTTS_LANGUAGES subset
                banner_text = (
                    "✔  English cloning ready (Chatterbox, ~400 MB on first use)  ·  "
                    "⚠ Multilingual cloning (pt-BR, fr, es…) unavailable — "
                    "re-run setup.bat to install Coqui XTTS v2."
                )
                banner_style = "color: #f9e2af; font-size: 11px;"
            ok_label = QLabel(banner_text)
            ok_label.setStyleSheet(banner_style)
            ok_label.setWordWrap(True)
            rl.addWidget(ok_label)

        detect_row = QHBoxLayout()
        self.clone_detect_btn = QPushButton("🔍  Auto-Detect Gender")
        self.clone_detect_btn.setEnabled(False)
        self.clone_detect_btn.clicked.connect(self._detect_gender)
        detect_row.addWidget(self.clone_detect_btn)
        self.clone_gender_detected = QLabel("Detected gender: —")
        detect_row.addWidget(self.clone_gender_detected)
        preview_ref_btn = QPushButton("▶  Preview Reference")
        preview_ref_btn.clicked.connect(
            lambda: self._play_file(self.clone_file_edit.text())
            if os.path.isfile(self.clone_file_edit.text()) else None
        )
        detect_row.addWidget(preview_ref_btn)
        detect_row.addStretch()
        rl.addLayout(detect_row)
        layout.addWidget(ref_grp)

        # — Profile metadata —
        meta_grp = QGroupBox("Voice Profile Details")
        ml = QVBoxLayout(meta_grp)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Voice Name:"))
        self.clone_name_edit = QLineEdit()
        self.clone_name_edit.setPlaceholderText("e.g.  My Custom Voice")
        name_row.addWidget(self.clone_name_edit)
        ml.addLayout(name_row)

        meta_row = QHBoxLayout()
        meta_row.addWidget(QLabel("Gender:"))
        self.clone_gender_combo = QComboBox()
        self.clone_gender_combo.addItems(["Female", "Male", "Unknown"])
        meta_row.addWidget(self.clone_gender_combo)
        meta_row.addWidget(QLabel("Language:"))
        self.clone_lang_combo = QComboBox()
        self.clone_lang_combo.addItems(
            [lang for lang in self.vm.get_all_languages() if lang != "All"]
        )
        meta_row.addWidget(self.clone_lang_combo)
        meta_row.addStretch()
        ml.addLayout(meta_row)

        notes_row = QHBoxLayout()
        notes_row.addWidget(QLabel("Notes:"))
        self.clone_notes_edit = QLineEdit()
        self.clone_notes_edit.setPlaceholderText("Optional description")
        notes_row.addWidget(self.clone_notes_edit)
        ml.addLayout(notes_row)
        layout.addWidget(meta_grp)

        # — Language auto-detect from sample text —
        lang_row = QHBoxLayout()
        self.clone_lang_text_edit = QLineEdit()
        self.clone_lang_text_edit.setPlaceholderText(
            "Paste a short sample text to auto-detect its language…"
        )
        lang_row.addWidget(self.clone_lang_text_edit)
        detect_lang_btn = QPushButton("🌐  Detect Language")
        detect_lang_btn.clicked.connect(self._detect_language_from_text)
        lang_row.addWidget(detect_lang_btn)
        layout.addLayout(lang_row)

        # — Save —
        save_row = QHBoxLayout()
        save_btn = QPushButton("💾  Save Voice Profile")
        save_btn.setMinimumHeight(36)
        save_btn.clicked.connect(self._save_clone_profile)
        save_row.addWidget(save_btn)
        self.clone_status = QLabel("")
        save_row.addWidget(self.clone_status)
        save_row.addStretch()
        layout.addLayout(save_row)

        layout.addStretch()
        return tab

    def _browse_reference(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Reference Audio", "",
            "Audio Files (*.mp3 *.wav *.ogg *.flac);;All Files (*)",
        )
        if path:
            self.clone_file_edit.setText(path)
            self.clone_detect_btn.setEnabled(True)
            self.clone_status.setText("")
            self._update_ref_duration(path)

    def _update_ref_duration(self, path: str):
        """Display reference audio duration and warn if too short for cloning."""
        try:
            dur_s = self.engine.get_duration_ms(path) / 1000.0
            if dur_s < 3:
                label = f"Duration: {dur_s:.1f} s  ⚠ Too short — minimum 3 s required"
                self.clone_ref_duration.setStyleSheet("color: #f38ba8; font-size: 11px;")
            elif dur_s < 5:
                label = f"Duration: {dur_s:.1f} s  ⚠ Short — 5–15 s recommended for best results"
                self.clone_ref_duration.setStyleSheet("color: #fab387; font-size: 11px;")
            else:
                label = f"Duration: {dur_s:.1f} s  ✔ Good length for voice cloning"
                self.clone_ref_duration.setStyleSheet("color: #a6e3a1; font-size: 11px;")
            self.clone_ref_duration.setText(label)
        except Exception:
            self.clone_ref_duration.setText("Duration: unable to read file")
            self.clone_ref_duration.setStyleSheet("color: #a6adc8; font-size: 11px;")

    def _detect_gender(self):
        path = self.clone_file_edit.text()
        if not path or not os.path.isfile(path):
            return
        # Guard: do not start a second analysis while one is already running
        if self._analyze_worker and self._analyze_worker.isRunning():
            return
        self.clone_detect_btn.setEnabled(False)
        self.clone_gender_detected.setText("Detecting…")
        self._analyze_worker = AnalyzeWorker(self.vm, path)
        self._analyze_worker.result.connect(self._on_gender_detected)
        self._analyze_worker.error.connect(self._on_gender_detect_error)
        self._analyze_worker.start()

    def _on_gender_detect_error(self, msg: str):
        self.clone_gender_detected.setText(f"Error: {msg}")
        self.clone_detect_btn.setEnabled(True)

    def _on_gender_detected(self, gender: str):
        self.clone_gender_detected.setText(f"Detected gender: {gender}")
        idx = self.clone_gender_combo.findText(gender)
        if idx >= 0:
            self.clone_gender_combo.setCurrentIndex(idx)
        self.clone_detect_btn.setEnabled(True)

    def _detect_language_from_text(self):
        text = self.clone_lang_text_edit.text().strip()
        if not text:
            return
        lang = self.vm.detect_language_from_text(text)
        idx = self.clone_lang_combo.findText(lang)
        if idx >= 0:
            self.clone_lang_combo.setCurrentIndex(idx)
        self.clone_status.setText(f"Detected language: {lang}")

    def _save_clone_profile(self):
        name = self.clone_name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Missing Name", "Please enter a voice name.")
            return
        gender   = self.clone_gender_combo.currentText()
        language = self.clone_lang_combo.currentText()
        notes    = self.clone_notes_edit.text()
        ref_src  = self.clone_file_edit.text()

        # Warn if reference audio is too short for quality cloning
        if ref_src and os.path.isfile(ref_src):
            try:
                dur_s = self.engine.get_duration_ms(ref_src) / 1000.0
                if dur_s < 3:
                    QMessageBox.warning(
                        self, "Reference Too Short",
                        f"The reference recording is only {dur_s:.1f} s.\n\n"
                        "Voice cloning requires at least 3 seconds, and works best\n"
                        "with 5–15 seconds of clean, noise-free speech.\n\n"
                        "Please select a longer recording.",
                    )
                    return
                if dur_s < 5:
                    ans = QMessageBox.question(
                        self, "Short Reference Recording",
                        f"The reference is {dur_s:.1f} s (recommended: ≥ 5 s).\n\n"
                        "Short recordings may produce poor voice similarity.\n"
                        "Save anyway?",
                    )
                    if ans != QMessageBox.Yes:
                        return
            except Exception:
                pass

        # Copy reference audio into profiles/
        ref_dest = ""
        if ref_src and os.path.isfile(ref_src):
            profiles_dir = os.path.join(BASE_DIR, "profiles")
            os.makedirs(profiles_dir, exist_ok=True)
            ext = os.path.splitext(ref_src)[1]
            # Sanitize name to prevent path-traversal; mirrors VoiceManager.save_custom_voice
            safe = re.sub(r"[^\w\s\-]", "", name).strip().replace(" ", "_")
            ref_dest = os.path.join(profiles_dir, f"{safe}_ref{ext}")
            if os.path.abspath(ref_src) != os.path.abspath(ref_dest):
                shutil.copy2(ref_src, ref_dest)

        try:
            self.vm.save_custom_voice(name, gender, language, ref_dest, notes)
            self.clone_status.setText(f"✔ Voice '{name}' saved.")
            self._refresh_gen_filters()
            self._refresh_bank_table()
        except Exception as exc:
            QMessageBox.critical(self, "Save Error", str(exc))

    # ══════════════════════════════════════════════════════════════════════════
    # Tab 3 — Voice Bank
    # ══════════════════════════════════════════════════════════════════════════

    def _build_bank_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # — Filters —
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Gender:"))
        self.bank_gender_filter = QComboBox()
        self.bank_gender_filter.addItems(["All", "Female", "Male", "Unknown"])
        self.bank_gender_filter.currentTextChanged.connect(self._refresh_bank_table)
        filter_row.addWidget(self.bank_gender_filter)
        filter_row.addWidget(QLabel("Language:"))
        self.bank_lang_filter = QComboBox()
        self.bank_lang_filter.addItems(self.vm.get_all_languages())
        self.bank_lang_filter.currentTextChanged.connect(self._refresh_bank_table)
        filter_row.addWidget(self.bank_lang_filter)
        filter_row.addWidget(QLabel("Type:"))
        self.bank_type_filter = QComboBox()
        self.bank_type_filter.addItems(["All", "Builtin", "Custom"])
        self.bank_type_filter.currentTextChanged.connect(self._refresh_bank_table)
        filter_row.addWidget(self.bank_type_filter)
        clear_btn = QPushButton("✕  Clear")
        clear_btn.clicked.connect(self._clear_bank_filters)
        filter_row.addWidget(clear_btn)
        filter_row.addStretch()
        layout.addLayout(filter_row)

        # — Table —
        self.bank_table = QTableWidget()
        self.bank_table.setColumnCount(5)
        self.bank_table.setHorizontalHeaderLabels(["Name", "Gender", "Language", "Type", "Notes"])
        self.bank_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.bank_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.bank_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.bank_table.setAlternatingRowColors(True)
        layout.addWidget(self.bank_table)

        # — Actions —
        btn_row = QHBoxLayout()
        preview_btn = QPushButton("▶  Preview Voice")
        preview_btn.clicked.connect(self._bank_preview)
        btn_row.addWidget(preview_btn)
        load_btn = QPushButton("📥  Load in Generate")
        load_btn.clicked.connect(self._bank_load_in_generate)
        btn_row.addWidget(load_btn)
        del_btn = QPushButton("🗑  Delete Custom Voice")
        del_btn.clicked.connect(self._bank_delete)
        btn_row.addWidget(del_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._refresh_bank_table()
        return tab

    def _clear_bank_filters(self):
        for combo in (self.bank_gender_filter, self.bank_lang_filter, self.bank_type_filter):
            combo.setCurrentIndex(0)

    def _refresh_bank_table(self):
        gender = self.bank_gender_filter.currentText()
        lang   = self.bank_lang_filter.currentText()
        vtype  = self.bank_type_filter.currentText()

        voices = self.vm.get_all_voices(
            gender=None if gender == "All" else gender,
            language=None if lang == "All" else lang,
        )
        if vtype != "All":
            voices = [v for v in voices if v.get("type", "builtin").lower() == vtype.lower()]

        self.bank_table.setRowCount(len(voices))
        for row, v in enumerate(voices):
            for col, key in enumerate(("name", "gender", "language", "type", "notes")):
                item = QTableWidgetItem(v.get(key, ""))
                self.bank_table.setItem(row, col, item)
            self.bank_table.item(row, 0).setData(Qt.UserRole, v)

    def _selected_bank_voice(self):
        row = self.bank_table.currentRow()
        if row < 0:
            return None
        item = self.bank_table.item(row, 0)
        return item.data(Qt.UserRole) if item else None

    def _bank_preview(self):
        voice = self._selected_bank_voice()
        if not voice:
            QMessageBox.information(self, "No Selection", "Select a voice to preview.")
            return
        if voice.get("type") == "custom":
            ref = voice.get("reference_audio", "")
            if ref and os.path.isfile(ref):
                self._play_file(ref)
                return
        # Guard: do not replace a still-running worker — GC of a live QThread crashes PyQt5
        if self._tts_worker and self._tts_worker.isRunning():
            QMessageBox.information(self, "Busy", "Please wait for the current generation to finish.")
            return
        short_name = voice.get("short_name", "en-US-AriaNeural")
        self._tts_worker = TTSWorker(self.engine, {
            "text": "Hello, this is a voice preview.",
            "voice_short_name": short_name,
            "tone": "Normal",
            "mood": 5,
        })
        self._tts_worker.finished.connect(self._play_file)
        self._tts_worker.error.connect(lambda e: QMessageBox.warning(self, "Preview Error", e))
        self._tts_worker.start()

    def _bank_load_in_generate(self):
        voice = self._selected_bank_voice()
        if not voice:
            return
        # Switch to Generate tab
        self.centralWidget().setCurrentIndex(0)
        lang = voice.get("language", "All")
        idx = self.gen_lang_combo.findText(lang)
        if idx >= 0:
            self.gen_lang_combo.setCurrentIndex(idx)
        self._populate_gen_voice_combo()
        name = voice.get("name", "")
        for i in range(self.gen_voice_combo.count()):
            v = self.gen_voice_combo.itemData(i)
            if v and v.get("name") == name:
                self.gen_voice_combo.setCurrentIndex(i)
                break

    def _bank_delete(self):
        voice = self._selected_bank_voice()
        if not voice:
            QMessageBox.information(self, "No Selection", "Select a custom voice to delete.")
            return
        if voice.get("type", "builtin") == "builtin":
            QMessageBox.warning(self, "Cannot Delete", "Built-in voices cannot be deleted.")
            return
        if QMessageBox.question(
            self, "Delete Voice",
            f"Delete voice '{voice['name']}'?",
            QMessageBox.Yes | QMessageBox.No,
        ) == QMessageBox.Yes:
            self.vm.delete_custom_voice(voice["name"])
            self._refresh_bank_table()
            self._refresh_gen_filters()

    # ══════════════════════════════════════════════════════════════════════════
    # Tab 4 — Edit & Save
    # ══════════════════════════════════════════════════════════════════════════

    def _build_edit_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # — Load —
        load_grp = QGroupBox("Load Audio")
        ll = QHBoxLayout(load_grp)
        self.edit_file_edit = QLineEdit()
        self.edit_file_edit.setReadOnly(True)
        self.edit_file_edit.setPlaceholderText("Load an audio file to trim and export…")
        ll.addWidget(self.edit_file_edit)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_edit_audio)
        ll.addWidget(browse_btn)
        use_gen_btn = QPushButton("Use Generated Audio")
        use_gen_btn.clicked.connect(self._load_generated_audio)
        ll.addWidget(use_gen_btn)
        layout.addWidget(load_grp)

        self.edit_dur_label = QLabel("Duration: —")
        layout.addWidget(self.edit_dur_label)

        # — Trim —
        trim_grp = QGroupBox("Trim")
        tl = QVBoxLayout(trim_grp)
        for attr, label in (("start", "Start (ms):"), ("end", "End (ms):  ")):
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            slider = QSlider(Qt.Horizontal)
            slider.setRange(0, 60000)
            slider.setValue(0 if attr == "start" else 60000)
            slider.valueChanged.connect(self._on_trim_slider_changed)
            setattr(self, f"edit_{attr}_slider", slider)
            row.addWidget(slider)
            lbl = QLabel(f"{'0' if attr == 'start' else '60000'} ms")
            lbl.setMinimumWidth(80)
            setattr(self, f"edit_{attr}_lbl", lbl)
            row.addWidget(lbl)
            tl.addLayout(row)

        trim_btn_row = QHBoxLayout()
        self.play_orig_btn = QPushButton("▶  Play Original")
        self.play_orig_btn.setEnabled(False)
        self.play_orig_btn.clicked.connect(lambda: self._play_file(self._edit_audio))
        trim_btn_row.addWidget(self.play_orig_btn)
        self.trim_btn = QPushButton("✂  Apply Trim & Preview")
        self.trim_btn.setEnabled(False)
        self.trim_btn.clicked.connect(self._apply_trim)
        trim_btn_row.addWidget(self.trim_btn)
        trim_btn_row.addStretch()
        tl.addLayout(trim_btn_row)
        layout.addWidget(trim_grp)

        # — Live Tweaks —
        tweak_grp = QGroupBox("Live Tweaks (non-destructive until Apply)")
        twl = QVBoxLayout(tweak_grp)

        tweak_row1 = QHBoxLayout()
        tweak_row1.addWidget(QLabel("Tone:"))
        self.edit_tone_combo = QComboBox()
        self.edit_tone_combo.addItems(TONES)
        tweak_row1.addWidget(self.edit_tone_combo)
        tweak_row1.addWidget(QLabel("Mood (1–10):"))
        self.edit_mood_slider = QSlider(Qt.Horizontal)
        self.edit_mood_slider.setRange(1, 10)
        self.edit_mood_slider.setValue(5)
        self.edit_mood_slider.setMaximumWidth(200)
        self.edit_mood_slider.setTickPosition(QSlider.TicksBelow)
        self.edit_mood_slider.setTickInterval(1)
        tweak_row1.addWidget(self.edit_mood_slider)
        self.edit_mood_val = QLabel("5")
        self.edit_mood_val.setMinimumWidth(20)
        self.edit_mood_slider.valueChanged.connect(
            lambda v: self.edit_mood_val.setText(str(v))
        )
        tweak_row1.addWidget(self.edit_mood_val)
        tweak_row1.addStretch()
        twl.addLayout(tweak_row1)

        tweak_row2 = QHBoxLayout()
        self.preview_tweaks_btn = QPushButton("▶  Preview Tweaks")
        self.preview_tweaks_btn.setEnabled(False)
        self.preview_tweaks_btn.clicked.connect(self._preview_tweaks)
        tweak_row2.addWidget(self.preview_tweaks_btn)
        self.apply_tweaks_btn = QPushButton("✔  Apply Tweaks")
        self.apply_tweaks_btn.setEnabled(False)
        self.apply_tweaks_btn.clicked.connect(self._apply_tweaks)
        tweak_row2.addWidget(self.apply_tweaks_btn)
        tweak_row2.addStretch()
        twl.addLayout(tweak_row2)
        layout.addWidget(tweak_grp)

        # — Export —
        export_grp = QGroupBox("Export Audio")
        el = QHBoxLayout(export_grp)
        el.addWidget(QLabel("Format:"))
        self.edit_fmt_combo = QComboBox()
        self.edit_fmt_combo.addItems(["WAV  (44100 Hz, 16-bit)", "MP3  (192 kbps)"])
        el.addWidget(self.edit_fmt_combo)
        self.export_btn = QPushButton("💾  Export…")
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self._export_audio)
        el.addWidget(self.export_btn)
        self.edit_status = QLabel("")
        el.addWidget(self.edit_status)
        el.addStretch()
        layout.addWidget(export_grp)

        layout.addStretch()
        return tab

    def _browse_edit_audio(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Audio", "",
            "Audio Files (*.mp3 *.wav *.ogg *.flac);;All Files (*)",
        )
        if path:
            self._load_audio_for_edit(path)

    def _load_generated_audio(self):
        if self._current_audio and os.path.isfile(self._current_audio):
            self._load_audio_for_edit(self._current_audio)
        else:
            QMessageBox.information(self, "No Audio", "Generate audio first in the Generate tab.")

    @staticmethod
    def _fmt_dur(dur_ms: int) -> str:
        """Format *dur_ms* milliseconds as a human-readable duration label."""
        return f"Duration: {dur_ms / 1000:.2f} s  ({dur_ms} ms)"

    def _load_audio_for_edit(self, path: str):
        try:
            dur = self.engine.get_duration_ms(path)
        except Exception as exc:
            QMessageBox.critical(self, "Load Error", f"Cannot read audio file:\n{exc}")
            return
        self._edit_audio = path
        self.edit_file_edit.setText(path)
        self.edit_dur_label.setText(self._fmt_dur(dur))
        for slider in (self.edit_start_slider, self.edit_end_slider):
            slider.setRange(0, dur)
        self.edit_start_slider.setValue(0)
        self.edit_end_slider.setValue(dur)
        self.edit_start_lbl.setText("0 ms")
        self.edit_end_lbl.setText(f"{dur} ms")
        self.play_orig_btn.setEnabled(True)
        self.trim_btn.setEnabled(True)
        self.preview_tweaks_btn.setEnabled(True)
        self.apply_tweaks_btn.setEnabled(True)
        self.export_btn.setEnabled(True)
        self.edit_status.setText("")

    def _preview_tweaks(self):
        """Apply tone/mood to a temporary copy and play it (non-destructive)."""
        if not self._edit_audio or not os.path.isfile(self._edit_audio):
            return
        tmp = self._copy_edit_to_temp()
        tone = self.edit_tone_combo.currentText()
        mood = self.edit_mood_slider.value()
        try:
            self.engine.apply_tone_mood(tmp, tone, mood)
        except Exception as exc:
            QMessageBox.warning(self, "Preview Error", str(exc))
            return
        self.edit_status.setText(f"▶ Previewing: {tone}, mood {mood}")
        self._play_file(tmp)

    def _apply_tweaks(self):
        """Apply tone/mood to a new working copy, making it the current audio."""
        if not self._edit_audio or not os.path.isfile(self._edit_audio):
            return
        tmp = self._copy_edit_to_temp()
        tone = self.edit_tone_combo.currentText()
        mood = self.edit_mood_slider.value()
        try:
            self.engine.apply_tone_mood(tmp, tone, mood)
        except Exception as exc:
            QMessageBox.warning(self, "Apply Error", str(exc))
            return
        self._edit_audio = tmp
        self.edit_dur_label.setText(self._fmt_dur(self.engine.get_duration_ms(tmp)))
        self.edit_status.setText(f"✔ Applied: {tone}, mood {mood}")

    def _copy_edit_to_temp(self) -> str:
        """Copy the current edit audio to a new temp WAV and return its path."""
        out_dir = os.path.join(BASE_DIR, "output")
        os.makedirs(out_dir, exist_ok=True)
        fd, tmp = tempfile.mkstemp(suffix=".wav", dir=out_dir)
        os.close(fd)
        shutil.copy2(self._edit_audio, tmp)
        return tmp

    def _on_trim_slider_changed(self):
        start = self.edit_start_slider.value()
        end   = self.edit_end_slider.value()
        if start >= end:
            if self.sender() is self.edit_start_slider:
                self.edit_start_slider.setValue(end - 1)
            else:
                self.edit_end_slider.setValue(start + 1)
        self.edit_start_lbl.setText(f"{self.edit_start_slider.value()} ms")
        self.edit_end_lbl.setText(f"{self.edit_end_slider.value()} ms")

    def _apply_trim(self):
        if not self._edit_audio or not os.path.isfile(self._edit_audio):
            return
        start = self.edit_start_slider.value()
        end   = self.edit_end_slider.value()
        if start >= end:
            QMessageBox.warning(
                self, "Invalid Trim Range",
                f"Start ({start} ms) must be less than End ({end} ms).",
            )
            return
        # Work on a copy so original is preserved
        out_dir = os.path.join(BASE_DIR, "output")
        os.makedirs(out_dir, exist_ok=True)
        fd, tmp = tempfile.mkstemp(suffix=".wav", dir=out_dir)
        os.close(fd)
        shutil.copy2(self._edit_audio, tmp)
        self.engine.trim_audio(tmp, start, end)
        self._edit_audio = tmp
        dur = self.engine.get_duration_ms(tmp)
        self.edit_dur_label.setText(f"Duration (trimmed): {dur / 1000:.2f} s  ({dur} ms)")
        self.edit_status.setText(f"✔ Trimmed to {start}–{end} ms")
        self._play_file(tmp)

    def _export_audio(self):
        if not self._edit_audio or not os.path.isfile(self._edit_audio):
            return
        fmt = "wav" if "WAV" in self.edit_fmt_combo.currentText() else "mp3"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Audio", f"export.{fmt}",
            f"Audio (*.{fmt});;All Files (*)",
        )
        if path:
            try:
                self.engine.save_as(self._edit_audio, path, fmt)
                self.edit_status.setText(f"✔ Saved: {os.path.basename(path)}")
            except Exception as exc:  # pydub raises various errors (CouldntEncodeError, OSError…)
                QMessageBox.critical(self, "Export Error", str(exc))


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("EchoPilot")
    window = EchoPilot()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()