# Runway & Motion Video Providers

## Overview
- **Provider**: Runway Gen-2 / Gen-3 Alpha (Cloud API) & Local Hybrid Motion
- **Execution**: Remote REST API or Local OpenCV/FFmpeg 2.5D optical flow
- **Purpose**: Image-to-video animation and cinematic shot transitions.

## Motion Modes
1. **Hybrid Sequential Motion (Local)**:
   - High-speed 60fps pan/tilt/zoom Ken Burns interpolation.
   - Parallax foreground/background layer shifting via FFmpeg filtergraphs.
   - Zero-cost, 100% offline.
2. **Cloud Runway Adapter (Remote API)**:
   - REST client adapter for remote motion synthesis.
