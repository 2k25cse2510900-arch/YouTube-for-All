"""FFmpeg and FFprobe Subprocess Execution Guard."""

import json
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

from config.settings import get_settings
from src.common.logger import setup_logger
from src.video_editor.exceptions import FFmpegExecutionError, FFmpegNotFoundError

logger = setup_logger("ffmpeg_runner")


class FFmpegRunner:
    """Manages secure, memory-conscious FFmpeg and FFprobe subprocess execution."""

    def __init__(
        self,
        ffmpeg_path: Optional[str] = None,
        ffprobe_path: Optional[str] = None,
        default_timeout: int = 300,
    ):
        settings = get_settings().video
        self.ffmpeg_path = ffmpeg_path or settings.ffmpeg_path
        self.ffprobe_path = ffprobe_path or settings.ffprobe_path
        self.default_timeout = default_timeout or settings.render_timeout_seconds

    def is_ffmpeg_available(self) -> bool:
        """Check whether FFmpeg executable is accessible on the host machine."""
        available, _ = self.check_ffmpeg_availability()
        return available

    def check_ffmpeg_availability(self) -> Tuple[bool, str]:
        """Verify that FFmpeg executable responds to version query.

        Returns:
            Tuple[bool, str]: (is_available, version_or_error_message)
        """
        # First check PATH resolution via shutil.which
        resolved = shutil.which(self.ffmpeg_path)
        if not resolved and not Path(self.ffmpeg_path).is_file():
            return False, f"FFmpeg executable '{self.ffmpeg_path}' not found on PATH or disk."

        cmd = [self.ffmpeg_path, "-version"]
        try:
            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5,
            )
            if res.returncode == 0:
                first_line = res.stdout.splitlines()[0] if res.stdout else "FFmpeg present"
                return True, first_line
            return False, f"FFmpeg exited with code {res.returncode}: {res.stderr[:200]}"
        except FileNotFoundError:
            return False, f"FFmpeg binary not found at '{self.ffmpeg_path}'."
        except subprocess.TimeoutExpired:
            return False, "FFmpeg version check timed out after 5s."
        except Exception as err:
            return False, f"FFmpeg check failed: {err}"

    def check_ffprobe_availability(self) -> Tuple[bool, str]:
        """Verify that FFprobe executable responds to version query."""
        resolved = shutil.which(self.ffprobe_path)
        if not resolved and not Path(self.ffprobe_path).is_file():
            return False, f"FFprobe executable '{self.ffprobe_path}' not found on PATH or disk."

        cmd = [self.ffprobe_path, "-version"]
        try:
            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5,
            )
            if res.returncode == 0:
                first_line = res.stdout.splitlines()[0] if res.stdout else "FFprobe present"
                return True, first_line
            return False, f"FFprobe exited with code {res.returncode}: {res.stderr[:200]}"
        except FileNotFoundError:
            return False, f"FFprobe binary not found at '{self.ffprobe_path}'."
        except Exception as err:
            return False, f"FFprobe check failed: {err}"

    def run_ffmpeg(
        self,
        args: List[str],
        timeout: Optional[int] = None,
    ) -> Tuple[subprocess.CompletedProcess, float]:
        """Execute an FFmpeg command via a streaming subprocess.

        Args:
            args: Argument list to pass to ffmpeg (excluding the ffmpeg executable itself).
            timeout: Maximum seconds to allow the process to run.

        Returns:
            Tuple[subprocess.CompletedProcess, float]: (CompletedProcess, elapsed_seconds)

        Raises:
            FFmpegNotFoundError: If FFmpeg binary is not found.
            FFmpegExecutionError: If FFmpeg command returns non-zero status or times out.
        """
        full_cmd = [self.ffmpeg_path] + args
        timeout_sec = timeout or self.default_timeout

        logger.info("Executing FFmpeg command: %s (Timeout: %ds)", " ".join(full_cmd[:8]) + " ...", timeout_sec)
        start_time = time.perf_counter()

        try:
            proc = subprocess.run(
                full_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout_sec,
            )
            elapsed = round(time.perf_counter() - start_time, 3)

            if proc.returncode != 0:
                err_preview = proc.stderr[-1000:] if proc.stderr else "Unknown error"
                msg = f"FFmpeg process failed with exit code {proc.returncode} in {elapsed}s:\n{err_preview}"
                logger.error(msg)
                raise FFmpegExecutionError(msg)

            logger.info("FFmpeg execution completed successfully in %.3fs", elapsed)
            return proc, elapsed

        except FileNotFoundError as fnf:
            msg = (
                f"FFmpeg binary not found at '{self.ffmpeg_path}'. "
                f"Please ensure FFmpeg is installed and accessible on PATH."
            )
            logger.critical(msg)
            raise FFmpegNotFoundError(msg) from fnf
        except subprocess.TimeoutExpired as te:
            msg = f"FFmpeg execution timed out after {timeout_sec} seconds. Process aborted."
            logger.error(msg)
            raise FFmpegExecutionError(msg) from te

    def probe_video(self, file_path: Path) -> Dict[str, Any]:
        """Query container and stream metadata of a rendered video file using ffprobe."""
        target = Path(file_path).resolve()
        if not target.exists():
            raise FileNotFoundError(f"Video file to probe does not exist: {target}")

        cmd = [
            self.ffprobe_path,
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(target),
        ]

        try:
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)
            if proc.returncode != 0:
                raise FFmpegExecutionError(f"FFprobe failed for '{target.name}': {proc.stderr}")
            return json.loads(proc.stdout)
        except FileNotFoundError as fnf:
            raise FFmpegNotFoundError(f"FFprobe binary not found at '{self.ffprobe_path}'.") from fnf
        except Exception as err:
            raise FFmpegExecutionError(f"Failed to probe video '{target.name}': {err}") from err
