# Google Gemini Integration

## Overview
- **Provider**: Google DeepMind / Google Cloud AI Studio
- **SDK**: `google-genai` (v3.2.0+)
- **Models**: `gemini-3.5-flash-lite`, `gemini-3.1-flash-lite`, `gemini-2.5-flash-image`
- **License**: Google APIs Terms of Service / Gemini API Additional Terms

## Capabilities
1. **Research & Fact Verification**: Structured JSON schema output extracting claims, verification status, and citation sources with Google Search grounding.
2. **Storyboard Generation**: Translates raw scripts into scene-by-scene visual descriptions, camera framing, subject placement, and pacing durations.
3. **Image Synthesis**: Generates vertical 9:16 keyframes via `gemini-2.5-flash-image`.

## Configuration
```env
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-3.5-flash-lite
GEMINI_FALLBACK_MODEL=gemini-3.1-flash-lite
GEMINI_TIMEOUT_SECONDS=30
```
