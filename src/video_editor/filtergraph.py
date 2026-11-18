"""FFmpeg Filtergraph Builder for Vertical 9:16 YouTube Shorts."""

from pathlib import Path
from typing import List, Optional, Tuple

from src.video_editor.models import SceneClipSpec, VideoRenderSettings


def escape_ffmpeg_filter_path(path: Path) -> str:
    """Escape file path for FFmpeg filter arguments (subtitles / ass).

    On Windows, backslashes must be converted to forward slashes and the drive colon
    must be escaped (e.g. 'C\\:/path/to/subtitles.ass').
    """
    resolved = Path(path).resolve()
    # Normalize to forward slashes
    posix_path = resolved.as_posix()
    # Escape colon following drive letter on Windows (e.g. C: -> C\:)
    if len(posix_path) >= 2 and posix_path[1] == ":":
        posix_path = posix_path[0] + "\\:" + posix_path[2:]
    # Escape single quotes and brackets
    posix_path = posix_path.replace("'", "'\\''").replace("[", "\\[").replace("]", "\\]")
    return posix_path


class FiltergraphBuilder:
    """Builds native FFmpeg complex filtergraphs for multi-scene 9:16 Shorts assembly."""

    def __init__(self, render_settings: Optional[VideoRenderSettings] = None):
        self.settings = render_settings or VideoRenderSettings()

    def build_scene_filter(
        self,
        input_index: int,
        spec: SceneClipSpec,
    ) -> str:
        """Construct the filter chain for an individual scene clip including motion.

        Supports camera movements:
        - slow-zoom-in: gentle 1.0 -> 1.12 scale push toward center
        - dynamic-push: dramatic 1.0 -> 1.20 push
        - pan-left-to-right: 1.08 zoom with smooth horizontal pan
        - static: centered scale and pad to 1080x1920 with 1:1 pixel aspect ratio
        """
        w = self.settings.width
        h = self.settings.height
        fps = self.settings.fps
        duration = spec.duration_seconds
        frames = max(1, int(round(duration * fps)))

        movement = (spec.camera_movement or "static").lower().strip()

        if movement in ("slow-zoom-in", "zoom-in", "slow_zoom_in"):
            # Subtle smooth zoom from 1.0 to 1.12
            motion_filter = (
                f"zoompan=z='min(zoom+0.001,1.12)':d={frames}:"
                f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps={fps}"
            )
        elif movement in ("slow-zoom-out", "zoom-out", "slow_zoom_out"):
            # Subtle smooth zoom out from 1.12 toward 1.0
            motion_filter = (
                f"zoompan=z='if(lte(zoom,1.0),1.12,max(1.001,zoom-0.0008))':d={frames}:"
                f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps={fps}"
            )
        elif movement in ("dynamic-push", "push", "dynamic_push"):
            # More intense dramatic push
            motion_filter = (
                f"zoompan=z='min(zoom+0.002,1.20)':d={frames}:"
                f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps={fps}"
            )
        elif movement in ("pan-left-to-right", "pan_left_to_right", "pan-right"):
            # Subtle zoom with horizontal pan
            motion_filter = (
                f"zoompan=z=1.08:x='if(lte(on,-1),0,on/{frames}*(iw-iw/zoom))':"
                f"y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={fps}"
            )
        elif movement in ("pan-up", "pan_up"):
            # Subtle zoom with vertical pan upwards
            motion_filter = (
                f"zoompan=z=1.08:x='iw/2-(iw/zoom/2)':"
                f"y='if(lte(on,-1),ih-ih/zoom,(1-on/{frames})*(ih-ih/zoom))':d={frames}:s={w}x{h}:fps={fps}"
            )
        elif movement in ("static-drift", "static_drift", "drift"):
            # Subtle continuous drift
            motion_filter = (
                f"zoompan=z='min(zoom+0.0004,1.06)':d={frames}:"
                f"x='if(lte(on,-1),0,on/{frames}*(iw-iw/zoom)*0.5)':"
                f"y='ih/2-(ih/zoom/2)':s={w}x{h}:fps={fps}"
            )
        else:
            # Static: standard high-quality aspect-ratio preserving fit with center padding
            motion_filter = (
                f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1"
            )

        # Ensure exact frame duration and PTS reset
        return (
            f"[{input_index}:v]{motion_filter},"
            f"trim=duration={duration:.3f},setpts=PTS-STARTPTS[v{input_index}]"
        )

    def build_full_command(
        self,
        scene_specs: List[SceneClipSpec],
        audio_path: Path,
        output_path: Path,
        ass_caption_path: Optional[Path] = None,
    ) -> List[str]:
        """Synthesize the complete FFmpeg CLI arguments.

        Args:
            scene_specs: List of scene clips with paths, durations, and camera movements.
            audio_path: Path to synchronized voiceover or mixed audio WAV.
            output_path: Path to target MP4 output file.
            ass_caption_path: Optional path to stylized ASS subtitles.

        Returns:
            List[str]: Complete argument list for subprocess invocation.
        """
        args: List[str] = ["-y"]  # Overwrite output without prompting

        # 1. Inputs for each scene image (looping for exact duration)
        for spec in scene_specs:
            args.extend([
                "-loop", "1",
                "-t", f"{spec.duration_seconds:.3f}",
                "-i", str(Path(spec.image_path).resolve()),
            ])

        # 2. Audio input
        audio_idx = len(scene_specs)
        args.extend(["-i", str(Path(audio_path).resolve())])

        # 3. Filtergraph construction
        filter_parts: List[str] = []

        # Build each scene's individual motion stream
        for idx, spec in enumerate(scene_specs):
            filter_parts.append(self.build_scene_filter(idx, spec))

        # Concat all scene visual streams
        concat_inputs = "".join(f"[v{i}]" for i in range(len(scene_specs)))
        filter_parts.append(f"{concat_inputs}concat=n={len(scene_specs)}:v=1:a=0[vbase]")

        # Burn in ASS captions if provided
        if ass_caption_path and Path(ass_caption_path).exists():
            escaped_ass = escape_ffmpeg_filter_path(ass_caption_path)
            filter_parts.append(f"[vbase]ass='{escaped_ass}'[vout]")
        else:
            filter_parts.append("[vbase]null[vout]")

        full_filtergraph = ";".join(filter_parts)

        args.extend(["-filter_complex", full_filtergraph])

        # 4. Stream mapping
        args.extend(["-map", "[vout]", "-map", f"{audio_idx}:a"])

        # 5. Encoding specifications (optimized for 8GB RAM laptop & YouTube Shorts compatibility)
        preset_val = getattr(self.settings, "preset", getattr(self.settings, "encoding_preset", "veryfast"))
        args.extend([
            "-c:v", self.settings.video_codec,
            "-preset", preset_val,
            "-crf", str(self.settings.crf),
            "-pix_fmt", self.settings.pixel_format,
            "-c:a", self.settings.audio_codec,
            "-b:a", self.settings.audio_bitrate,
            "-ar", "48000",
            "-ac", "2",
            "-shortest",  # Ensure video terminates when audio ends
            str(Path(output_path).resolve()),
        ])

        return args
