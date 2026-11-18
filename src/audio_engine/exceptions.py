"""Exceptions for Audio Engine and Voice Synthesis."""


class AudioEngineError(Exception):
    """Base exception for all Audio Engine errors."""

    pass


class VoiceSynthesisError(AudioEngineError):
    """Raised when voiceover generation fails or service is unreachable."""

    pass


class AudioMixingError(AudioEngineError):
    """Raised when audio mixing or ducking encounters an error."""

    pass


class AudioLicenseVerificationError(AudioEngineError):
    """Raised when an audio asset lacks verified license documentation."""

    pass


class PaidVoiceServiceBlockedError(AudioEngineError):
    """Raised if an attempt is made to invoke a paid voice API."""

    pass
