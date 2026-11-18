"""Video Editor and FFmpeg Assembly Module for YouTube Shorts."""

from src.video_editor.exceptions import (
    FFmpegExecutionError,
    FFmpegNotFoundError,
    VideoAssetMissingError,
    VideoCompositionError,
    VideoEditorError,
)
from src.video_editor.ffmpeg_runner import FFmpegRunner
from src.video_editor.filtergraph import FiltergraphBuilder, escape_ffmpeg_filter_path
from src.video_editor.models import SceneClipSpec, VideoRenderResult, VideoRenderSettings
from src.video_editor.service import VideoAssemblyEngine

__all__ = [
    "VideoAssemblyEngine",
    "VideoRenderSettings",
    "SceneClipSpec",
    "VideoRenderResult",
    "FFmpegRunner",
    "FiltergraphBuilder",
    "escape_ffmpeg_filter_path",
    "VideoEditorError",
    "FFmpegNotFoundError",
    "FFmpegExecutionError",
    "VideoAssetMissingError",
    "VideoCompositionError",
]
