"""Error classification and user-friendly CLARA-voice error messages.

No LLM call in the except path -- templates are deterministic and fast.
"""
from __future__ import annotations

import logging
from typing import Literal

logger = logging.getLogger(__name__)

ErrorCategory = Literal["transient", "unsupported", "no_data", "provider_block", "generic"]


def classify_error(exc: BaseException) -> tuple[ErrorCategory, bool]:
    """Classify an exception into a category and whether it's retryable."""
    name = type(exc).__name__.lower()
    msg = str(exc).lower()

    # Transient / connectivity
    if any(tok in name for tok in ("timeout", "connection", "refused", "reset", "unavailable")):
        return "transient", True
    if any(tok in msg for tok in (
        "timed out", "connection refused", "connection reset", "unreachable",
        "429", "too many requests", "rate limit", "503", "502", "500",
        "temporarily unavailable", "service unavailable",
    )):
        return "transient", True

    # Provider content block
    if any(tok in msg for tok in ("content filter", "blocked", "safety", "guardrail")):
        return "provider_block", False

    # Unsupported / bad query
    if any(tok in msg for tok in (
        "syntax error", "invalid", "recursion limit", "no route", "unsupported",
        "undefined column", "relation does not exist",
    )):
        return "unsupported", False

    # Empty result surfaced as error
    if any(tok in msg for tok in ("no data", "no results", "not found", "empty")):
        return "no_data", False

    return "generic", True


_TEMPLATES: dict[ErrorCategory, dict[str, str]] = {
    "transient": {
        "en": "I could not reach the records system just now. Please try again in a moment.",
        "hi": "अभी रिकॉर्ड सिस्टम तक पहुँचने में समस्या हुई। कृपया कुछ देर बाद पुनः प्रयास करें।",
        "kn": "ದಾಖಲೆ ವ್ಯವಸ್ಥೆಯನ್ನು ಈಗ ತಲುಪಲು ಸಾಧ್ಯವಾಗಲಿಲ್ಲ. ದಯವಿಟ್ಟು ಸ್ವಲ್ಪ ಸಮಯದ ನಂತರ ಮತ್ತೆ ಪ್ರಯತ್ನಿಸಿ.",
    },
    "unsupported": {
        "en": "I could not work out how to answer that. Try rephrasing, or name the case by its CrimeNo.",
        "hi": "मैं इस प्रश्न का उत्तर नहीं दे पाया। कृपया अलग तरीके से पूछें, या CrimeNo से केस बताएं।",
        "kn": "ಅದಕ್ಕೆ ಉತ್ತರ ಕಂಡುಹಿಡಿಯಲು ಸಾಧ್ಯವಾಗಲಿಲ್ಲ. ಬೇರೆ ರೀತಿಯಲ್ಲಿ ಕೇಳಿ, ಅಥವಾ CrimeNo ಮೂಲಕ ಪ್ರಕರಣವನ್ನು ಹೆಸರಿಸಿ.",
    },
    "no_data": {
        "en": "I found no matching records for that query. Try broadening the search -- for example, use a shorter date range or a less specific identifier.",
        "hi": "उस प्रश्न के लिए कोई मेल खाते रिकॉर्ड नहीं मिले। खोज को व्यापक करें -- उदाहरण के लिए, छोटी तारीख सीमा या कम विशिष्ट पहचानकर्ता का उपयोग करें।",
        "kn": "ಆ ಪ್ರಶ್ನೆಗೆ ಹೊಂದಿಕೆಯಾಗುವ ದಾಖಲೆಗಳು ಸಿಗಲಿಲ್ಲ. ಹುಡುಕಾಟವನ್ನು ವಿಸ್ತಾರಗೊಳಿಸಿ -- ಚಿಕ್ಕ ದಿನಾಂಕ ವ್ಯಾಪ್ತಿ ಅಥವಾ ಕಡಿಮೆ ನಿರ್ದಿಷ್ಟ ಗುರುತಿಸುವಿಕೆ ಬಳಸಿ.",
    },
    "provider_block": {
        "en": "The query was blocked by a content safety filter. Try rephrasing your question with more specific case details.",
        "hi": "प्रश्न सुरक्षा फ़िल्टर द्वारा अवरुद्ध किया गया था। अधिक विशिष्ट केस विवरण के साथ अपना प्रश्न पुनः लिखें।",
        "kn": "ಪ್ರಶ್ನೆಯನ್ನು ಸುರಕ್ಷತಾ ಫಿಲ್ಟರ್ ನಿರ್ಬಂಧಿಸಿದೆ. ಹೆಚ್ಚಿನ ನಿರ್ದಿಷ್ಟ ಪ್ರಕರಣ ವಿವರಗಳೊಂದಿಗೆ ನಿಮ್ಮ ಪ್ರಶ್ನೆಯನ್ನು ಪುನಃ ಬರೆಯಿರಿ.",
    },
    "generic": {
        "en": "Something went wrong while processing your question. Please try again.",
        "hi": "आपके प्रश्न को संसाधित करते समय कुछ गड़बड़ हुई। कृपया पुनः प्रयास करें।",
        "kn": "ನಿಮ್ಮ ಪ್ರಶ್ನೆಯನ್ನು ಪ್ರಕ್ರಿಯೆಗೊಳಿಸುವಾಗ ಏನೋ ತಪ್ಪಾಗಿದೆ. ದಯವಿಟ್ಟು ಮತ್ತೆ ಪ್ರಯತ್ನಿಸಿ.",
    },
}


def error_message(category: ErrorCategory, language: str = "en") -> str:
    """Get the user-facing error message for a category in the officer's language."""
    templates = _TEMPLATES.get(category, _TEMPLATES["generic"])
    return templates.get(language, templates["en"])
