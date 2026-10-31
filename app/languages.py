"""Supported languages with speech settings.

whisper: language hint for speech recognition; edge: Microsoft neural voices
(free, via edge-tts); gtts: Google Translate TTS fallback code.
"""
from __future__ import annotations

LANGS: dict[str, dict] = {
    "hi": {"name": "Hindi", "native": "हिन्दी", "whisper": "hi", "edge": ["hi-IN-SwaraNeural", "hi-IN-MadhurNeural"], "gtts": "hi"},
    "en": {"name": "English", "native": "English", "whisper": "en", "edge": ["en-IN-NeerjaNeural", "en-IN-PrabhatNeural"], "gtts": "en"},
    "bn": {"name": "Bengali", "native": "বাংলা", "whisper": "bn", "edge": ["bn-IN-TanishaaNeural", "bn-IN-BashkarNeural"], "gtts": "bn"},
    "mr": {"name": "Marathi", "native": "मराठी", "whisper": "mr", "edge": ["mr-IN-AarohiNeural", "mr-IN-ManoharNeural"], "gtts": "mr"},
    "te": {"name": "Telugu", "native": "తెలుగు", "whisper": "te", "edge": ["te-IN-ShrutiNeural", "te-IN-MohanNeural"], "gtts": "te"},
    "ta": {"name": "Tamil", "native": "தமிழ்", "whisper": "ta", "edge": ["ta-IN-PallaviNeural", "ta-IN-ValluvarNeural"], "gtts": "ta"},
    "gu": {"name": "Gujarati", "native": "ગુજરાતી", "whisper": "gu", "edge": ["gu-IN-DhwaniNeural", "gu-IN-NiranjanNeural"], "gtts": "gu"},
    "kn": {"name": "Kannada", "native": "ಕನ್ನಡ", "whisper": "kn", "edge": ["kn-IN-SapnaNeural", "kn-IN-GaganNeural"], "gtts": "kn"},
    "ml": {"name": "Malayalam", "native": "മലയാളം", "whisper": "ml", "edge": ["ml-IN-SobhanaNeural", "ml-IN-MidhunNeural"], "gtts": "ml"},
    "pa": {"name": "Punjabi", "native": "ਪੰਜਾਬੀ", "whisper": "pa", "edge": ["pa-IN-VaaniNeural", "pa-IN-OjasNeural"], "gtts": "pa"},
    "ur": {"name": "Urdu", "native": "اردو", "whisper": "ur", "edge": ["ur-IN-GulNeural", "ur-IN-SalmanNeural"], "gtts": "ur"},
}


def lang_or_default(code: str | None, default: str = "hi") -> str:
    c = (code or "").lower().strip()
    return c if c in LANGS else default


def describe(code: str) -> str:
    l = LANGS[code]
    return f"{l['name']} ({l['native']})"
