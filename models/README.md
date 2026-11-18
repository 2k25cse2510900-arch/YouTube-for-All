# AI Model Integrations & Providers

YouTube-for-All integrates multiple AI models and neural processing APIs across text, audio, image, and video domains.

> [!NOTE]
> **Zero Model Weights Policy**: This repository provides reusable Python wrappers, API adapters, prompt schemas, and configuration templates. It does not bundle or redistribute model weights.

## Supported Model Categories

| Domain | Provider / Engine | Primary Model | Alternative / Fallback |
| :--- | :--- | :--- | :--- |
| **Research & Claims** | Google Gemini | `gemini-3.5-flash-lite` | `gemini-3.1-flash-lite` |
| **Image Generation** | Cloudflare Workers AI | `@cf/black-forest-labs/flux-1-schnell` | Hugging Face Serverless FLUX.1 |
| **Image Generation** | Google Gemini | `gemini-2.5-flash-image` | Mock Pillow Procedural Generator |
| **Voiceover & TTS** | Microsoft Edge TTS | `hi-IN-MadhurNeural` | `hi-IN-SwaraNeural`, `en-IN-NeerjaNeural` |
| **Indian Voiceover** | Sarvam AI | Bulbul v1 (`shubh`) | Mock offline sine synthesizer |
| **Animation / Video** | Hybrid Optical / FFmpeg | 2.5D Parallax & Ken Burns | Runway Gen-2/3 API adapter stub |

## Setup & Credential Resolution

All integrations resolve authentication keys via environment variables configured in `.env`:
- `GEMINI_API_KEY`: Google AI Studio access
- `CLOUDFLARE_ACCOUNT_ID` & `CLOUDFLARE_API_TOKEN`: Cloudflare Workers AI
- `HF_TOKEN`: Hugging Face Inference API
- `SARVAM_API_KEY`: Sarvam AI Bulbul TTS
