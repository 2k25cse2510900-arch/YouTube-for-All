"""BGM and SFX Library Manager with verified YouTube Audio Library licensing."""

import hashlib
from pathlib import Path
import shutil
from typing import Dict, List, Optional

from config.settings import get_settings
from src.audio_engine.exceptions import AudioLicenseVerificationError
from src.audio_engine.models import BGMTrackMetadata, SFXTrackMetadata
from src.common.logger import setup_logger

logger = setup_logger("bgm_library")


class BGMLibraryManager:
    """Manages verified background music and sound effects with strict license enforcement.

    CRITICAL RULES:
    1. FreePD.com is closed and must NOT be used.
    2. YouTube Audio Library tracks with attribution-not-required status are the primary source.
    3. Every track records title, artist, source, license, and attribution requirements.
    4. Tracks without verified licenses cannot enter the production pipeline.
    """

    def __init__(self, bgm_dir: Optional[Path] = None, sfx_dir: Optional[Path] = None):
        settings = get_settings()
        self.bgm_dir = Path(bgm_dir or settings.paths.bgm_assets_dir)
        self.sfx_dir = Path(sfx_dir or settings.paths.sfx_assets_dir)

        self.bgm_dir.mkdir(parents=True, exist_ok=True)
        self.sfx_dir.mkdir(parents=True, exist_ok=True)

        self._catalog: Dict[str, BGMTrackMetadata] = {}
        self._sfx_catalog: Dict[str, SFXTrackMetadata] = {}
        self._init_curated_catalog()

    def _init_curated_catalog(self) -> None:
        """Initialize curated list of verified YouTube Audio Library tracks."""
        # 1. YouTube Audio Library - Track 1 (DISABLED: Misleading metadata; audio is Airplane Mode copy)
        t1 = BGMTrackMetadata(
            track_id="yt_bgm_suspense_revelation_01",
            title="Space Station",
            artist="Jeremy Blake",
            source="YouTube Audio Library",
            license="YouTube Audio Library License - Attribution Not Required",
            license_url="https://support.google.com/youtube/answer/3376882",
            attribution_required=False,
            attribution_text=None,
            file_path=str(self.bgm_dir / "space_station_jeremy_blake.mp3"),
            duration_seconds=124.0,
            mood="Suspense",
            tempo="Medium",
            status="DISABLED",
            is_verified=False,
        )
        self.register_bgm_track(t1)

        # 2. YouTube Audio Library - Track 2 (DISABLED: Misleading metadata; audio is Airplane Mode copy)
        t2 = BGMTrackMetadata(
            track_id="yt_bgm_inspirational_science_02",
            title="Book The Rental Car",
            artist="Josh Woodward",
            source="YouTube Audio Library",
            license="YouTube Audio Library License - Attribution Not Required",
            license_url="https://support.google.com/youtube/answer/3376882",
            attribution_required=False,
            attribution_text=None,
            file_path=str(self.bgm_dir / "book_the_rental_car_josh_woodward.mp3"),
            duration_seconds=98.0,
            mood="Inspirational",
            tempo="Medium",
            status="DISABLED",
            is_verified=False,
        )
        self.register_bgm_track(t2)

        # 3. YouTube Audio Library - Track 3 (DISABLED: Misleading metadata; audio is Airplane Mode copy)
        t3 = BGMTrackMetadata(
            track_id="yt_bgm_clockwork_drama_03",
            title="Dramatic Clockwork Pulse",
            artist="YouTube Creator Studio",
            source="YouTube Audio Library",
            license="YouTube Audio Library License - Attribution Not Required",
            license_url="https://support.google.com/youtube/answer/3376882",
            attribution_required=False,
            attribution_text=None,
            file_path=str(self.bgm_dir / "dramatic_clockwork_pulse.mp3"),
            duration_seconds=60.0,
            mood="Dark",
            tempo="Fast",
            status="DISABLED",
            is_verified=False,
        )
        self.register_bgm_track(t3)

        # 4. Creative Commons Track (Josh Woodward - UNVERIFIED: Pending independent local license proof)
        t4 = BGMTrackMetadata(
            track_id="cc_bgm_airplane_mode_josh_woodward",
            title="Airplane Mode (Instrumental Version)",
            artist="Josh Woodward",
            source="Free Music Archive",
            license="Creative Commons Attribution 4.0 International (CC BY 4.0)",
            license_url="http://creativecommons.org/licenses/by/4.0/",
            attribution_required=True,
            attribution_text='Music: "Airplane Mode (Instrumental Version)" by Josh Woodward (https://www.joshwoodward.com/) licensed under CC BY 4.0',
            file_path=str(self.bgm_dir / "space_station_jeremy_blake.mp3"),
            duration_seconds=216.85,
            mood="Dramatic Revelation",
            tempo="Medium",
            status="UNVERIFIED",
            is_verified=False,
        )
        self.register_bgm_track(t4)


        # Standard Curated Sound Effects (Public Domain / CC0)
        sfx_items = [
            ("sfx_stone_crack", "Stone Crack", "CC0 Public Domain"),
            ("sfx_clock_tick", "Rhythmic Clock Tick", "CC0 Public Domain"),
            ("sfx_electric_hum", "Synapse Electrical Pulse", "CC0 Public Domain"),
            ("sfx_bass_drop", "Cinematic Sub Bass Drop", "CC0 Public Domain"),
            ("sfx_synth_chime", "Upbeat Scientific Chime", "CC0 Public Domain"),
        ]
        for sfx_id, name, lic in sfx_items:
            self._sfx_catalog[sfx_id] = SFXTrackMetadata(
                sfx_id=sfx_id,
                name=name,
                source="CC0 / Public Domain",
                license=lic,
                file_path=str(self.sfx_dir / f"{sfx_id}.wav"),
                duration_seconds=2.0,
            )

    def register_bgm_track(self, track: BGMTrackMetadata) -> None:
        """Register a verified track into the catalog with license verification."""
        # Enforce blacklist against closed or unverified sources
        source_lower = track.source.lower()
        if "freepd" in source_lower:
            msg = f"LICENSE VIOLATION: Source '{track.source}' is barred (FreePD is closed). Use YouTube Audio Library."
            logger.critical(msg)
            raise AudioLicenseVerificationError(msg)

        if not track.license or "attribution not required" not in track.license.lower():
            if track.attribution_required and not track.attribution_text:
                raise AudioLicenseVerificationError(
                    f"Track '{track.title}' requires attribution, but no attribution text was provided."
                )

        self._catalog[track.track_id] = track
        logger.debug("Registered verified BGM track: '%s' by %s (%s)", track.title, track.artist, track.source)

    def get_track(self, track_id: str) -> Optional[BGMTrackMetadata]:
        """Retrieve a verified BGM track by ID."""
        return self._catalog.get(track_id)

    def get_track_for_mood(self, mood: str) -> Optional[BGMTrackMetadata]:
        """Retrieve the best matching verified active BGM track for a requested mood.

        Returns None if no active verified track is available (permitting voiceover-only production).
        """
        clean_mood = mood.strip().lower()
        active_tracks = [t for t in self._catalog.values() if t.status == "ACTIVE" and t.is_verified]
        for track in active_tracks:
            if track.mood.lower() in clean_mood:
                return track
        if active_tracks:
            return active_tracks[0]
        return None

    def get_sfx(self, sfx_id: str) -> Optional[SFXTrackMetadata]:
        """Retrieve a verified sound effect by ID."""
        return self._sfx_catalog.get(sfx_id)

    def list_catalog(self, active_only: bool = False) -> List[BGMTrackMetadata]:
        """Return BGM tracks (all tracks by default, or only active verified tracks)."""
        if active_only:
            return [t for t in self._catalog.values() if t.status == "ACTIVE" and t.is_verified]
        return list(self._catalog.values())

    @classmethod
    def format_attribution(cls, track: Optional[BGMTrackMetadata]) -> Optional[str]:
        """Construct deterministic attribution credit text based on verified metadata and license.

        - If attribution is NOT required (e.g. YouTube Audio Library attribution-not-required), returns None.
        - If attribution IS required:
          - Validates presence of title and artist.
          - Validates source or license URL.
          - Formats transparent credit string.
        """
        if not track:
            return None
        if not track.attribution_required:
            lic_lower = (track.license or "").lower()
            if "attribution not required" in lic_lower or "cc0" in lic_lower or "public domain" in lic_lower:
                return None

        # Attribution is required
        if not track.title or not track.artist:
            raise ValueError(f"Incomplete BGM metadata for track '{track.track_id}': title and artist are required for attribution.")

        if track.attribution_text:
            return track.attribution_text

        # Construct attribution text adhering to CC BY guidelines
        url_part = f" ({track.license_url})" if track.license_url else ""
        source_part = f" - Source: {track.source}" if track.source else ""
        lic_part = f" under {track.license}" if track.license else ""
        return f'Music: "{track.title}" by {track.artist}{lic_part}{url_part}{source_part}'.strip()


    def import_bgm_track(
        self,
        source_audio_path: Path,
        track_id: str,
        title: str,
        artist: str,
        source: str = "YouTube Audio Library",
        license_name: str = "YouTube Audio Library License - Attribution Not Required",
        attribution_required: bool = False,
        attribution_text: Optional[str] = None,
        mood: str = "Cinematic",
        tempo: str = "Medium",
    ) -> BGMTrackMetadata:
        """Import a real downloaded audio file into the local BGM assets directory with checksum verification."""
        src = Path(source_audio_path).resolve()
        if not src.exists():
            raise FileNotFoundError(f"Audio file to import does not exist: {src}")

        ext = src.suffix or ".mp3"
        dest = self.bgm_dir / f"{track_id}{ext}"
        shutil.copy2(src, dest)

        with open(dest, "rb") as f:
            checksum = hashlib.sha256(f.read()).hexdigest()

        track = BGMTrackMetadata(
            track_id=track_id,
            title=title,
            artist=artist,
            source=source,
            license=license_name,
            attribution_required=attribution_required,
            attribution_text=attribution_text,
            file_path=str(dest),
            file_checksum=checksum,
            mood=mood,
            tempo=tempo,
        )
        self.register_bgm_track(track)
        logger.info("Imported BGM track '%s' (%s, SHA256: %s)", title, track_id, checksum[:12])
        return track

    def import_sfx_track(
        self,
        source_audio_path: Path,
        sfx_id: str,
        name: str,
        license_name: str = "CC0 / Public Domain",
        source: str = "CC0 / Public Domain",
    ) -> SFXTrackMetadata:
        """Import a real sound effect into the local SFX assets directory with checksum verification."""
        src = Path(source_audio_path).resolve()
        if not src.exists():
            raise FileNotFoundError(f"SFX file to import does not exist: {src}")

        ext = src.suffix or ".wav"
        dest = self.sfx_dir / f"{sfx_id}{ext}"
        shutil.copy2(src, dest)

        with open(dest, "rb") as f:
            checksum = hashlib.sha256(f.read()).hexdigest()

        sfx = SFXTrackMetadata(
            sfx_id=sfx_id,
            name=name,
            source=source,
            license=license_name,
            file_path=str(dest),
            file_checksum=checksum,
        )
        self._sfx_catalog[sfx_id] = sfx
        logger.info("Imported SFX '%s' (%s, SHA256: %s)", name, sfx_id, checksum[:12])
        return sfx
