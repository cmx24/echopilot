"""Voice profile manager for EchoPilot TTS application."""

import datetime
import json
import os
import re

import librosa
import numpy as np
from langdetect import detect as _langdetect, DetectorFactory

DetectorFactory.seed = 0  # deterministic language detection

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILES_DIR = os.path.join(BASE_DIR, "profiles")

LANGUAGE_MAP = {
    "en": "English", "fr": "French", "de": "German", "es": "Spanish",
    "it": "Italian", "pt": "Portuguese", "pl": "Polish", "tr": "Turkish",
    "ru": "Russian", "nl": "Dutch", "cs": "Czech", "ar": "Arabic",
    "zh": "Chinese", "zh-cn": "Chinese", "zh-tw": "Chinese",
    "ja": "Japanese", "ko": "Korean", "hu": "Hungarian", "hi": "Hindi",
    "sv": "Swedish", "da": "Danish", "fi": "Finnish", "no": "Norwegian",
    "uk": "Ukrainian",
}

LOCALE_MAP = {
    "en": "en-US", "fr": "fr-FR", "de": "de-DE", "es": "es-ES",
    "it": "it-IT", "pt": "pt-BR", "pl": "pl-PL", "tr": "tr-TR",
    "ru": "ru-RU", "nl": "nl-NL", "cs": "cs-CZ", "ar": "ar-SA",
    "zh": "zh-CN", "ja": "ja-JP", "ko": "ko-KR", "hu": "hu-HU",
    "hi": "hi-IN", "sv": "sv-SE", "da": "da-DK", "fi": "fi-FI",
    "no": "nb-NO", "uk": "uk-UA",
}

# Pre-loaded open-source / edge-tts built-in voices
BUILTIN_VOICES = [
    {"name": "Aria (US)",        "short_name": "en-US-AriaNeural",       "gender": "Female", "language": "English",    "type": "builtin"},
    {"name": "Jenny (US)",       "short_name": "en-US-JennyNeural",      "gender": "Female", "language": "English",    "type": "builtin"},
    {"name": "Sara (US)",        "short_name": "en-US-SaraNeural",       "gender": "Female", "language": "English",    "type": "builtin"},
    {"name": "Nancy (US)",       "short_name": "en-US-NancyNeural",      "gender": "Female", "language": "English",    "type": "builtin"},
    {"name": "Michelle (US)",    "short_name": "en-US-MichelleNeural",   "gender": "Female", "language": "English",    "type": "builtin"},
    {"name": "Guy (US)",         "short_name": "en-US-GuyNeural",        "gender": "Male",   "language": "English",    "type": "builtin"},
    {"name": "Davis (US)",       "short_name": "en-US-DavisNeural",      "gender": "Male",   "language": "English",    "type": "builtin"},
    {"name": "Tony (US)",        "short_name": "en-US-TonyNeural",       "gender": "Male",   "language": "English",    "type": "builtin"},
    {"name": "Jason (US)",       "short_name": "en-US-JasonNeural",      "gender": "Male",   "language": "English",    "type": "builtin"},
    {"name": "Sonia (GB)",       "short_name": "en-GB-SoniaNeural",      "gender": "Female", "language": "English",    "type": "builtin"},
    {"name": "Mia (GB)",         "short_name": "en-GB-MiaNeural",        "gender": "Female", "language": "English",    "type": "builtin"},
    {"name": "Ryan (GB)",        "short_name": "en-GB-RyanNeural",       "gender": "Male",   "language": "English",    "type": "builtin"},
    {"name": "Thomas (GB)",      "short_name": "en-GB-ThomasNeural",     "gender": "Male",   "language": "English",    "type": "builtin"},
    {"name": "Natasha (AU)",     "short_name": "en-AU-NatashaNeural",    "gender": "Female", "language": "English",    "type": "builtin"},
    {"name": "William (AU)",     "short_name": "en-AU-WilliamNeural",    "gender": "Male",   "language": "English",    "type": "builtin"},
    {"name": "Denise (FR)",      "short_name": "fr-FR-DeniseNeural",     "gender": "Female", "language": "French",     "type": "builtin"},
    {"name": "Eloise (FR)",      "short_name": "fr-FR-EloiseNeural",     "gender": "Female", "language": "French",     "type": "builtin"},
    {"name": "Henri (FR)",       "short_name": "fr-FR-HenriNeural",      "gender": "Male",   "language": "French",     "type": "builtin"},
    {"name": "Katja (DE)",       "short_name": "de-DE-KatjaNeural",      "gender": "Female", "language": "German",     "type": "builtin"},
    {"name": "Seraphina (DE)",   "short_name": "de-DE-SeraphinaNeural",  "gender": "Female", "language": "German",     "type": "builtin"},
    {"name": "Conrad (DE)",      "short_name": "de-DE-ConradNeural",     "gender": "Male",   "language": "German",     "type": "builtin"},
    {"name": "Elvira (ES)",      "short_name": "es-ES-ElviraNeural",     "gender": "Female", "language": "Spanish",    "type": "builtin"},
    {"name": "Alvaro (ES)",      "short_name": "es-ES-AlvaroNeural",     "gender": "Male",   "language": "Spanish",    "type": "builtin"},
    {"name": "Dalia (MX)",       "short_name": "es-MX-DaliaNeural",      "gender": "Female", "language": "Spanish",    "type": "builtin"},
    {"name": "Jorge (MX)",       "short_name": "es-MX-JorgeNeural",      "gender": "Male",   "language": "Spanish",    "type": "builtin"},
    {"name": "Elsa (IT)",        "short_name": "it-IT-ElsaNeural",       "gender": "Female", "language": "Italian",    "type": "builtin"},
    {"name": "Diego (IT)",       "short_name": "it-IT-DiegoNeural",      "gender": "Male",   "language": "Italian",    "type": "builtin"},
    {"name": "Francisca (BR)",   "short_name": "pt-BR-FranciscaNeural",  "gender": "Female", "language": "Portuguese", "type": "builtin"},
    {"name": "Antonio (BR)",     "short_name": "pt-BR-AntonioNeural",    "gender": "Male",   "language": "Portuguese", "type": "builtin"},
    {"name": "Zofia (PL)",       "short_name": "pl-PL-ZofiaNeural",      "gender": "Female", "language": "Polish",     "type": "builtin"},
    {"name": "Marek (PL)",       "short_name": "pl-PL-MarekNeural",      "gender": "Male",   "language": "Polish",     "type": "builtin"},
    {"name": "Svetlana (RU)",    "short_name": "ru-RU-SvetlanaNeural",   "gender": "Female", "language": "Russian",    "type": "builtin"},
    {"name": "Dmitry (RU)",      "short_name": "ru-RU-DmitryNeural",     "gender": "Male",   "language": "Russian",    "type": "builtin"},
    {"name": "Nanami (JP)",      "short_name": "ja-JP-NanamiNeural",     "gender": "Female", "language": "Japanese",   "type": "builtin"},
    {"name": "Keita (JP)",       "short_name": "ja-JP-KeitaNeural",      "gender": "Male",   "language": "Japanese",   "type": "builtin"},
    {"name": "SunHi (KR)",       "short_name": "ko-KR-SunHiNeural",      "gender": "Female", "language": "Korean",     "type": "builtin"},
    {"name": "InJoon (KR)",      "short_name": "ko-KR-InJoonNeural",     "gender": "Male",   "language": "Korean",     "type": "builtin"},
    {"name": "Xiaoxiao (CN)",    "short_name": "zh-CN-XiaoxiaoNeural",   "gender": "Female", "language": "Chinese",    "type": "builtin"},
    {"name": "Yunxi (CN)",       "short_name": "zh-CN-YunxiNeural",      "gender": "Male",   "language": "Chinese",    "type": "builtin"},
    {"name": "HiuGaai (HK)",     "short_name": "zh-HK-HiuGaaiNeural",   "gender": "Female", "language": "Chinese",    "type": "builtin"},
    {"name": "Zariyah (SA)",     "short_name": "ar-SA-ZariyahNeural",    "gender": "Female", "language": "Arabic",     "type": "builtin"},
    {"name": "Hamed (SA)",       "short_name": "ar-SA-HamedNeural",      "gender": "Male",   "language": "Arabic",     "type": "builtin"},
    {"name": "Swara (IN)",       "short_name": "hi-IN-SwaraNeural",      "gender": "Female", "language": "Hindi",      "type": "builtin"},
    {"name": "Madhur (IN)",      "short_name": "hi-IN-MadhurNeural",     "gender": "Male",   "language": "Hindi",      "type": "builtin"},
    {"name": "Hilda (SE)",       "short_name": "sv-SE-HildaNeural",      "gender": "Female", "language": "Swedish",    "type": "builtin"},
    {"name": "Mattias (SE)",     "short_name": "sv-SE-MattiasNeural",    "gender": "Male",   "language": "Swedish",    "type": "builtin"},
    {"name": "Christel (DK)",    "short_name": "da-DK-ChristelNeural",   "gender": "Female", "language": "Danish",     "type": "builtin"},
    {"name": "Jeppe (DK)",       "short_name": "da-DK-JeppeNeural",      "gender": "Male",   "language": "Danish",     "type": "builtin"},
    {"name": "Noora (FI)",       "short_name": "fi-FI-NooraNeural",      "gender": "Female", "language": "Finnish",    "type": "builtin"},
    {"name": "Harri (FI)",       "short_name": "fi-FI-HarriNeural",      "gender": "Male",   "language": "Finnish",    "type": "builtin"},
    {"name": "Polina (UA)",      "short_name": "uk-UA-PolinaNeural",     "gender": "Female", "language": "Ukrainian",  "type": "builtin"},
    {"name": "Ostap (UA)",       "short_name": "uk-UA-OstapNeural",      "gender": "Male",   "language": "Ukrainian",  "type": "builtin"},
]


class VoiceManager:
    def __init__(self):
        os.makedirs(PROFILES_DIR, exist_ok=True)
        self._custom: dict = {}
        self._load_custom_profiles()

    # ── Persistence ──────────────────────────────────────────────────────────

    def _load_custom_profiles(self):
        self._custom = {}
        for fname in os.listdir(PROFILES_DIR):
            if fname.endswith(".json"):
                fpath = os.path.join(PROFILES_DIR, fname)
                try:
                    with open(fpath, encoding="utf-8") as f:
                        profile = json.load(f)
                    self._custom[profile["name"]] = profile
                except (json.JSONDecodeError, KeyError, OSError):
                    pass

    def save_custom_voice(self, name: str, gender: str, language: str,
                          reference_audio: str = "", notes: str = "") -> dict:
        """Persist a custom voice profile to disk and return it."""
        safe = re.sub(r"[^\w\s\-]", "", name).strip()
        if not safe:
            raise ValueError("Invalid voice name.")
        profile = {
            "name": safe,
            "short_name": safe.replace(" ", "_").lower(),
            "gender": gender,
            "language": language,
            "type": "custom",
            "reference_audio": reference_audio,
            "notes": notes,
            "created": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        with open(os.path.join(PROFILES_DIR, f"{safe}.json"), "w", encoding="utf-8") as f:
            json.dump(profile, f, indent=2)
        self._custom[safe] = profile
        return profile

    def delete_custom_voice(self, name: str):
        if name in self._custom:
            fpath = os.path.join(PROFILES_DIR, f"{name}.json")
            if os.path.exists(fpath):
                os.remove(fpath)
            del self._custom[name]

    # ── Queries ──────────────────────────────────────────────────────────────

    def get_all_voices(self, gender: str = None, language: str = None) -> list:
        voices = list(BUILTIN_VOICES) + list(self._custom.values())
        if gender and gender != "All":
            voices = [v for v in voices if v.get("gender", "").lower() == gender.lower()]
        if language and language != "All":
            voices = [v for v in voices if v.get("language", "").lower() == language.lower()]
        return voices

    def get_all_genders(self) -> list:
        return ["All"] + sorted({v.get("gender", "") for v in self.get_all_voices() if v.get("gender")})

    def get_all_languages(self) -> list:
        return ["All"] + sorted({v.get("language", "") for v in self.get_all_voices() if v.get("language")})

    # ── Detection ────────────────────────────────────────────────────────────

    def detect_gender_from_audio(self, audio_path: str) -> str:
        """Estimate speaker gender from audio via fundamental-frequency analysis."""
        try:
            y, sr = librosa.load(audio_path, sr=None, mono=True, duration=30)
            f0, voiced_flag, _ = librosa.pyin(
                y,
                fmin=float(librosa.note_to_hz("C2")),
                fmax=float(librosa.note_to_hz("C7")),
                sr=sr,
            )
            if f0 is not None and voiced_flag is not None and voiced_flag.any():
                mean_f0 = float(np.nanmean(f0[voiced_flag]))
                return "Female" if mean_f0 > 165.0 else "Male"
        except Exception:
            pass
        return "Unknown"

    def detect_language_from_text(self, text: str) -> str:
        """Detect natural language from text and return a display name."""
        try:
            code = _langdetect(text.strip())
            return LANGUAGE_MAP.get(code, code.upper())
        except Exception:
            return "English"

    @staticmethod
    def get_locale_for_language(language: str) -> str:
        """Return an edge-tts locale code for a given language display name.

        ``language`` may be either a display name (e.g. ``"French"``) or a
        BCP-47 language code (e.g. ``"fr"``).  Both forms are accepted.
        """
        # If it looks like a code already (e.g. "fr", "zh-cn") normalise first
        lang_lower = language.lower()
        if lang_lower.startswith("zh"):
            return "zh-CN"
        if lang_lower in LOCALE_MAP:
            return LOCALE_MAP[lang_lower]

        # Display-name lookup — resolve collisions by preferring the shortest key
        # (e.g. "Chinese" → "zh" not "zh-tw" which isn't in LOCALE_MAP)
        matching_codes = [k for k, v in LANGUAGE_MAP.items() if v == language]
        if matching_codes:
            code = min(matching_codes, key=len)
            return LOCALE_MAP.get(code, "en-US")

        return "en-US"