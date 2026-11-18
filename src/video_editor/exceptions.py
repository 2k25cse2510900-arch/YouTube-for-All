"""Exceptions for Video Editor and FFmpeg Assembly Engine."""


class VideoEditorError(Exception):
    """Base exception for all video editor errors."""

    pass


class FFmpegNotFoundError(VideoEditorError):
    """Raised when FFmpeg or FFprobe executables cannot be located."""

    pass


class FFmpegExecutionError(VideoEditorError):
    """Raised when an FFmpeg process exits with non-zero status or encounters an error."""

    pass


class VideoAssetMissingError(VideoEditorError):
    """Raised when a required media asset (image, audio, caption) is missing from disk."""

    pass


class VideoCompositionError(VideoEditorError):
    """Raised when filtergraph synthesis or scene duration calculations fail."""

    pass
