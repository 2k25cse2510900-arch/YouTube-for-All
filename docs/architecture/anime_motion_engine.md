# Anime Motion Engine Architecture Specification

**Project:** A Lesson With AI  
**Component:** Anime Motion Engine (AME)  
**Version:** 1.0.0  
**Target Environment:** Windows 10, Python 3.15, 8 GB System RAM, FFmpeg 9.0.2  
**Date:** 2026-11-17  

---

## 1. Architectural Overview & System Goals

The **Anime Motion Engine (AME)** is a modular subsystem designed to elevate the production quality of *A Lesson With AI* from static-image pan/zoom slideshows to cinematic anime storytelling with genuine character motion, sequential action choreography, and persistent visual identity.

```
+---------------------------------------------------------------------------------------------------+
|                                   ANIME MOTION ENGINE PIPELINE                                    |
+---------------------------------------------------------------------------------------------------+
|                                                                                                   |
|  [Character Bible] ----+                                                                          |
|                        |                                                                          |
|                        v                                                                          |
|  [Script Manager] ---> [Motion Planner] ---> [Keyframe Generator] ---> [I2V Provider Adapter]     |
|   (Lang-Aware)           (15+ Shots)           (Pose Sequencing)          (Runway / Luma / Mock)  |
|                                                                                   |               |
|                                                                                   v               |
|  [Audio Engine] <------------------------------------------------------ [Animation Sequence]      |
|   (Sarvam/Edge + SFX/BGM)                                                         |               |
|                                                                                   v               |
|                                                                       [Motion Quality Checker]    |
|                                                                                   |               |
|                                                                                   v               |
|                                                                         [VideoFolderManager]      |
|                                                                          (Manifest & Review)      |
+---------------------------------------------------------------------------------------------------+
```

### Core Design Principles
1. **Four-Tier Motion Taxonomy:** Strict programmatic distinction between:
   - *Tier 1 — Static Image:* A single still frame with no pixel motion.
   - *Tier 2 — Procedural Camera Motion:* 2D affine transformation (pan, zoom, tilt) applied to a static canvas.
   - *Tier 3 — Frame Interpolation:* Motion-compensated optical flow synthesis between two static states.
   - *Tier 4 — Genuine AI Character Animation:* Semantic generative transformation where limbs, facial features, clothing, hair, and environmental elements deform, articulate, and interact across time.
2. **Persistent Visual Consistency:** Character visual identity is defined in a centralized `CharacterBible` schema and passed to every visual generation prompt and keyframe conditioning pass.
3. **Hardware-Conscious Memory Footprint:** Built to operate reliably on standard developer hardware (8 GB total RAM, CPU-bound execution) by streaming video operations in chunked FFmpeg pipes, strictly avoiding in-memory buffering of large video frames.
4. **Provider Neutrality & Strict Cost Guards:** Unified provider interface (`BaseImageToVideoProvider`) allowing plug-and-play switching between cloud generative APIs (Runway, Luma, Kling, Replicate) and local/mock fallback adapters without modifying downstream composition logic.

---

## 2. Component Hierarchy & Module Breakdown

### 2.1 Character Bible (`character_bible.py`)
Maintains a persistent, single-source-of-truth visual identity for original anime characters:
- **Core Attributes:** Name, role, age, archetype, silhouette, color palette.
- **Facial Specifications:** Eye shape, iris color, pupil design, eyebrow style, jawline, expression baselines.
- **Hair Specifications:** Style, length, bangs, color, highlights, dynamic response to wind/gravity.
- **Wardrobe & Gear:** Multi-layer clothing (inner, outerwear, footwear, accessories, weapons).
- **Distinguishing Motifs:** Runes, scars, tech implants, magical auras.
- **Prompt Conditioning:** Translates structured attributes into high-adherence positive and negative diffusion prompts.

### 2.2 Motion Planner (`motion_planner.py`)
Translates narrative beats from the language-aware script into a granular, shot-by-shot cinematic storyboard (minimum 15 distinct shots):
- **Shot Metadata:** Shot ID, start/end time, duration, shot size (wide, medium, close-up, macro), camera angle (low, high, eye-level, Dutch).
- **Choreography:** Starting pose, kinetic trajectory, acceleration/deceleration, ending pose.
- **Cinematic Atmosphere:** Lighting direction, color temperature, particle dynamics (sparks, rain, embers).
- **Audio Cueing:** Dedicated timestamps for footsteps, clothing rustle, blade impacts, magic ignition, and BGM ducking.

### 2.3 Keyframe Generator (`keyframe_generator.py`)
Generates structured visual anchors:
- Synthesizes initial frame (start pose) and optional final frame (settle pose) for each shot.
- Injects character reference tokens from the Character Bible to enforce visual continuity.
- Validates aspect ratio (9:16 vertical, 1080×1920) and resolution.

### 2.4 Image-to-Video Provider Adapter (`image_to_video_provider.py`)
Abstract interface defining video clip synthesis:
```python
class BaseImageToVideoProvider(ABC):
    @abstractmethod
    def generate_motion_clip(
        self,
        shot_id: str,
        start_image_path: Path,
        motion_prompt: str,
        duration_seconds: float,
        end_image_path: Optional[Path] = None,
        motion_strength: float = 0.5,
    ) -> MotionClipMetadata:
        pass
```
- **Supported Backends:**
  - `CloudRunwayProvider`: Direct integration with Runway Gen-3 Alpha Turbo API.
  - `CloudLumaProvider`: Direct integration with Luma Dream Machine API.
  - `CloudReplicateProvider`: Serverless execution of CogVideoX or Stable Video Diffusion.
  - `OpticalFlowHybridProvider`: Multi-keyframe character sequencing with bidirectional motion-compensated interpolation (`minterpolate`).
  - `MockMotionProvider`: Deterministic, zero-cost procedural animation for unit testing.

### 2.5 Animation Sequence Synthesizer (`animation_sequence.py`)
Assembles and coordinates the multi-shot motion timeline:
- Concatenates rendered video clips, hybrid motion sequences, and cinematic transitions (match cuts, light leaks, whip pans, dissolves).
- Aligns video sequence duration with audio narration and sound effects down to the individual frame (30.0 fps).

### 2.6 Motion Quality Checker (`motion_quality_checker.py`)
Automated forensic inspection of rendered animation:
- **Structural Defects:** Extra limbs, floating artifacts, facial disfigurement.
- **Temporal Defects:** High-frequency flicker, unnatural warp, freeze frames, sudden position jumps.
- **Format Integrity:** Full FFmpeg stream decode to null, 9:16 vertical check, audio-video synchronization margin ($\le 50$ ms).

### 2.7 Anime Motion Pipeline (`anime_motion_pipeline.py`)
The top-level orchestrator executing the end-to-end lifecycle:
1. Initialize Character Bible.
2. Plan 15+ cinematic shots from script.
3. Generate keyframe visual assets.
4. Synthesize genuine motion clips.
5. Generate synchronized voiceover and sound effects.
6. Assemble final master video and lightweight preview.
7. Perform automated quality audit and register in `manifest.json`.

---

## 3. Storage and Isolation Architecture

All outputs from the Anime Motion Engine are stored in dedicated per-video directories managed by `VideoFolderManager`:

```
output/videos/anime_motion_test_01/
├── manifest.json                  # Canonical asset registry & publication status
├── source/                        # Concept briefs & references
├── script/                        # Language-aware script (JSON)
├── storyboard/                    # 15-shot motion storyboard (JSON)
├── characters/                    # Character Bible specs & reference art
├── images/                        # Base keyframe images (1080x1920)
├── animation_clips/               # Rendered motion clips (MP4)
├── audio/                         # Voiceover narration, SFX, BGM
├── captions/                      # Subtitle timing & transcript
├── frames/                        # Extracted transition audit frames
├── preview/                       # Lightweight preview (<19 MB)
├── final/                         # Full-quality master MP4
└── reports/                       # Forensic QA report & structured JSON
```

---

## 4. Cost and Safety Enforcements

1. **Zero Unexpected Billing:** The engine defaults to offline mock or local hybrid optical flow mode. External cloud APIs cannot be invoked without explicit provider enablement and valid API tokens.
2. **Strict Privacy Gating:** All test outputs are flagged `PRIVATE_TEST_ONLY`. Automated publication, YouTube upload, and channel interactions are permanently barred.
