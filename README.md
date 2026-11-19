# YouTube-for-All

A modular Python framework for automated vertical video production (9:16 format). Designed for educational and explainer content, `YouTube-for-All` coordinates topic research, script structuring, voice synthesis, image generation, pan/zoom camera animation, caption synchronization, video assembly, quality validation, and publishing safeguards.

---

## Key Modules & Architecture

The framework is organized into decoupled engine modules within `src/`, with top-level domain facades:

* **Research Engine (`src.research_engine` / `research`)**: Outlines topics, generates factual reference points, and structures pedagogical topic angles using LLM backends.
* **Script Manager (`src.script_manager` / `script_generation`)**: Synthesizes structured scripts with estimated segment pacing, scene markers, and target word counts.
* **Audio Engine (`src.audio_engine` / `voice_and_audio`)**: Multi-provider voice synthesis supporting Edge TTS (local/free) and Sarvam AI (Indic voice synthesis), voice enhancement filters, custom pronunciation lexicons, and background audio ducking via `bgm_library.py`.
* **Image Engine (`src.image_engine` / `image_generation`)**: Multi-backend image generation adapters supporting Cloudflare Flux, Hugging Face Flux, and an offline PIL-based mock generator. Includes prompt adaptation and image validation.
* **Animation & Motion Engine (`src.anime_motion` / `animation`)**: Camera motion trajectory planner (`MotionShotPlan`) generating Ken Burns pans, zooms, dynamic framing, and motion metadata for visual scenes.
* **Video Editor (`src.video_editor` / `video_editing`)**: Automated FFmpeg-based video compositor handling timeline assembly, audio-video synchronization, cross-dissolve transitions, and vertical (1080x1920) rendering.
* **Caption Generator (`src.caption_generator` / `captions`)**: Produces synchronized subtitle tracks (ASS/SRT) with word-level timing and visual formatting for vertical mobile screens.
* **Quality Checker (`src.quality_checker`)**: Multi-gate validation validating resolution, aspect ratio, audio normalization (LUFS), frame rate, duration limits, and visual asset readiness.
* **Storage Manager (`src.storage_manager`)**: Manages production package lifecycles, structured directories (`data/`, `output/`, `logs/`), artifact versioning, and cache retention.
* **Pipeline Orchestrator (`src.pipeline`)**: State-machine-driven execution pipeline providing resumable checkpoints, human approval safeguards, and CLI orchestration.
* **YouTube Uploader (`src.youtube_uploader`)**: Resumable video upload service via YouTube Data API v3, enforcing mandatory human review sign-off (`UploadApprovalGate`), privacy state guards, and automated metadata generation.

---

## Prerequisites

* **Python**: Version 3.10 or higher (compatible with 3.10, 3.11, 3.12, 3.13, and 3.14+).
* **FFmpeg & FFprobe**: Required on the system `PATH` for all audio and video rendering, composition, and format validation tasks.
  * Windows: Install via `winget install Gyan.FFmpeg` or download from official FFmpeg builds and add to PATH.
  * Linux: `sudo apt-get install ffmpeg`
  * macOS: `brew install ffmpeg`

---

## Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/2k25cse2510900-arch/YouTube-for-All.git
   cd YouTube-for-All
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python -m venv .venv

   # On Windows:
   .venv\Scripts\activate

   # On Linux/macOS:
   source .venv/bin/activate
   ```

3. **Install the package:**
   * For core runtime:
     ```bash
     pip install -e .
     ```
   * For development and testing (recommended):
     ```bash
     pip install -e ".[dev]"
     ```

---

## Configuration

1. Copy the example configuration template to create your local `.env`:
   ```bash
   cp configs/default.env.example .env
   # or on Windows:
   copy configs\default.env.example .env
   ```

2. Configure environment variables in `.env` according to your workflow:
   * `GEMINI_API_KEY`: API key for Google Gemini (research and script generation).
   * `GEMINI_MODEL`: Default AI model (defaults to `gemini-3.5-flash-lite`).
   * `AUDIO_VOICE_PROVIDER`: Set to `edge_tts` for default zero-cost local synthesis.
   * `IMAGE_PROVIDER`: Set to `mock_pillow` for offline testing without cloud image generation.
   * `REQUIRE_HUMAN_APPROVAL`: Set to `true` to require human review before publishing stages.
   * `SARVAM_API_KEY`: (Optional) API key for Sarvam AI voice synthesis.
   * `CLOUDFLARE_API_TOKEN` & `CLOUDFLARE_ACCOUNT_ID`: (Optional) Credentials for Cloudflare Workers AI Flux image generation.

> [!IMPORTANT]
> **API Credentials, Quotas, and Potential Costs**:
> External service providers (such as Google Gemini, Cloudflare Workers AI, Sarvam AI, and YouTube Data API) require user-provisioned API credentials. Using these third-party cloud services may incur usage fees, consume account quotas, or be subject to rate limits depending on your account tier with each provider. Never commit your `.env` file or API secrets to version control. The repository defaults to offline/mock providers (`mock_pillow`, `edge_tts`) to facilitate zero-cost local testing.

---

## Command-Line Usage

The pipeline can be managed using `main.py` or the `src.pipeline.cli` module.

### Check System Status
View the production dashboard, active gates, and queued productions:
```bash
python main.py --status
```

### List Pipeline Productions
View existing production packages and their stage statuses:
```bash
python -m src.pipeline.cli list
```

### Prepare a Production Package
Initialize a production package from an approved script ID:
```bash
python -m src.pipeline.cli prepare --script-id <SCRIPT_ID>
```

### Validate Production Assets
Inspect image assets, durations, and quality gates for a production:
```bash
python -m src.pipeline.cli validate --production-id <PRODUCTION_ID>
```

### Render Video
Trigger FFmpeg composition and assembly for a validated production:
```bash
python -m src.pipeline.cli render --production-id <PRODUCTION_ID>
```

### Generate Production Report
Output detailed quality metrics and execution logs:
```bash
python -m src.pipeline.cli report --production-id <PRODUCTION_ID>
```

### Approve Production Sign-Off
Record human reviewer approval required by quality gates:
```bash
python -m src.pipeline.cli approve --production-id <PRODUCTION_ID> --notes "Review complete and approved."
```

### Resume Interrupted Production
Resume execution from the last valid checkpoint:
```bash
python -m src.pipeline.cli resume --production-id <PRODUCTION_ID>
```

---

## Running Tests

Execute the automated test suite with `pytest`:

```bash
pytest tests --tb=short
```

To run a specific test file:
```bash
pytest tests/test_video_editor.py -v
```
