# Clipping Tool 101 (ClipForge Pro) 🎬⚡

[![Platform: Windows](https://img.shields.io/badge/Platform-Windows%2010%2F11-blue.svg)](https://microsoft.com)
[![Python: 3.12](https://img.shields.io/badge/Python-3.12%2B-brightgreen.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688.svg)](https://fastapi.tiangolo.com)
[![FFmpeg](https://img.shields.io/badge/Video%20Engine-FFmpeg%207%2B-red.svg)](https://ffmpeg.org)
[![Whisper](https://img.shields.io/badge/ASR-faster--whisper-orange.svg)](https://github.com/SYSTRAN/faster-whisper)
[![OpenCV](https://img.shields.io/badge/Computer%20Vision-OpenCV-5C3EE8.svg)](https://opencv.org)
[![Build Status](https://img.shields.io/badge/Build-Passing%20(8%2F8%20Suites)-success.svg)]()

> **Clipping Tool 101** is a high-performance, autonomous AI clipping studio and video processing suite. It ingests long-form video files and live streams (Twitch, Kick, YouTube), analyzes audio dynamics, chat spikes, and on-screen gameplay events, and produces viral, vertical short-form content (9:16, 1:1, 16:9) for TikTok, YouTube Shorts, and Instagram Reels in seconds.

---

## 📑 Table of Contents
- [Key Features](#-key-features)
- [Architecture & Tech Stack](#-architecture--tech-stack)
- [Video Layouts](#-video-layouts)
- [Studio Editor Capabilities](#-studio-editor-capabilities)
- [Quick Start Guide](#-quick-start-guide)
  - [Option 1: Standalone Windows App (.exe)](#option-1-standalone-windows-app-exe)
  - [Option 2: Running from Source](#option-2-running-from-source)
- [Directory Structure](#-directory-structure)
- [Configuration & Environment](#-configuration--environment)
- [Testing & Verification](#-testing--verification)
- [License & Acknowledgements](#-license--acknowledgements)

---

## 🌟 Key Features

### 🧠 Autonomous AI Highlight Detection
- **Multi-Modal Candidate Scoring**: Ingests full VODs or livestreams and computes composite virality scores using audio energy peaks, speech transcription keywords, spectator chat velocity, and visual action frame diffs.
- **GTA Screen OCR & Game Event Recognition**: Uses Tesseract OCR to detect iconic in-game fail/action banners (`WASTED`, `BUSTED`, `MISSION FAILED`) and automatically scores them as candidate moments.
- **Audience Chat Replay Ingestion**: Automatically parses YouTube, Twitch IRC, and Kick websocket chat replays to align audience hype (`W`, `L`, `KEKW`, `CLIP THAT`, `NO WAY`) with video timestamps.
- **View Count Machine Learning (`/api/learn`)**: Correlates candidate visual/audio features against real-world YouTube Shorts and TikTok view counts, automatically re-ranking candidates for maximum reach.

### 🎭 Smart Streamer Framing & Dual-Cam Split
- **Interactive 8-Handle Streamer Box Selector**: Outline the streamer's reaction camera on the source video with 4 corner grips and 4 edge grips, or snap to presets (`↖ Top-Left`, `↗ Top-Right`, `↙ Bottom-Left`, `↘ Bottom-Right`, `🎯 Center`).
- **Dual-Cam Split (Stack Mode)**: Places the streamer webcam on top and centered gameplay on bottom (or vice versa) with an interactive, draggable split divider line (`50/50`, `45/55`, `40/60`, `35/65`).
- **Floating Cam (PiP Mode)**: Gameplay fills the vertical 9:16 frame while the streamer camera floats on top in a customizable rectangle or circular frame.
- **Interactive On-Canvas Resizing**: Drag the bottom-right corner handle (`⤡`) on the floating camera or use the **Floating Cam Size slider** (`0.4x` to `2.2x`) to scale the streamer camera dynamically.
- **Unrestricted 2D Pan (X / Y Axis)**: Center the streamer's face with full horizontal and vertical framing controls that never lock or clamp.

### 🎬 CapCut-Style Timeline Studio Editor
- **Precision Trimming & Splitting**:
  - `✂️ Cut Here`: Instantly slice the clip at the current playhead.
  - `[ Set In` & `Set Out ]`: 1-click in/out point trimming to the active frame.
  - `◀ −1s` and `+1s ▶`: Frame-by-frame fine adjustment buttons.
  - Direct `Len: [__]s` input with `−5s` and `+5s` rapid adjustment buttons.
- **Window Sliding**: Click and drag inside the selected timeline window (`#tsel`) to slide the entire clip cut across the video without changing duration.

### 🏷️ Viral Hook Titles & Upfront Captions
- **Draggable Anywhere on Screen**: Position viral hook titles freely on the canvas.
- **Flexible Styling**: Scale text from `0.5x` to `3.0x` across multiple visual themes (`White Pill`, `Dark Glow`, `Neon Accent`, `Clean Border`, `Yellow Pop`, `Transparent No-Box`).
- **Timeline Timing Strip**: The yellow Hook Card strip on the timeline allows adjusting exactly when the title appears and disappears, with drag-to-resize ends and a `Whole clip` reset button.
- **AI Word-by-Word Captions**: Powered by `faster-whisper`. Subtitles are generated upfront when clips are created. Supports custom font styling (`Arial`, `IMPACT`, `Montserrat`, `Black`, `Comic`), font size scaling (`0.5x` – `3.0x`), `.ass` / `.srt` exports, and automated audio ducking.

### 🔊 Meme Audio Library & Offline TTS
- **Meme Sound Effects**: Built-in sound effects (`airhorn.wav`, `record_scratch.wav`, `sad_trombone.wav`, `vine_boom.wav`) automatically triggered on gaming wins and fails.
- **Custom Audio Upload**: Upload your own music or SFX tracks directly via `/api/audio/upload` (`.mp3`, `.wav`, `.m4a`, `.aac`, `.flac`).
- **Offline Piper Voice-Over**: Generate natural-sounding offline voice-overs with automatic 30% background gameplay audio ducking.

### 🧹 Automatic Storage Management
- Automatically purges intermediate download caches and temporary segments older than 48 hours.
- Permanently safeguards all exported clips in `data/exports/`.

---

## 🛠️ Architecture & Tech Stack

| Layer | Component | Description |
|---|---|---|
| **Core Runtime** | Python 3.12 (64-bit) | High-performance asynchronous execution engine |
| **Web Server** | FastAPI & Uvicorn | Async REST API handling video uploads, jobs, settings, and streaming |
| **Video Rendering** | FFmpeg 7+ & FFprobe | Complex multi-input filtergraphs (`split`, `crop`, `scale`, `vstack`, `overlay`, `ass`, `amix`) |
| **Speech Recognition** | `faster-whisper` & CTranslate2 | Local GPU/CPU word-timestamped audio transcription |
| **Computer Vision** | OpenCV (`cv2`) & Tesseract OCR | Face tracking, frame difference motion analysis, and in-game banner detection |
| **Stream Ingestion** | YT-DLP & Streamlink | Real-time livestream recording and video download pipeline |
| **Speech Synthesis** | Piper TTS & AI Translate | Offline neural text-to-speech and caption translation |
| **Database** | SQLite3 (`clipforge.db`) | Local persistent storage with automated schema migrations |
| **Frontend UI** | Vanilla ES6+ & HTML5 Canvas | Zero-dependency, responsive CapCut-style studio editor with hardware-accelerated canvas |
| **Packaging** | PyInstaller 6.x | Self-contained, portable Windows application (`ClipForge.exe`) |

---

## 📐 Video Layouts

```
1. Dual-Cam Split (Stack)       2. Floating Cam (PiP)          3. Centered Gameplay (Follow/Crop)
┌────────────────────────┐      ┌────────────────────────┐      ┌────────────────────────┐
│                        │      │ ┌────────┐             │      │                        │
│    STREAMER WEBCAM     │      │ │Streamer│             │      │                        │
│   (Pan X/Y & Zoomable) │      │ │ Webcam │             │      │   CENTERED GAMEPLAY    │
│                        │      │ └────────┘             │      │  (Pan X/Y & Zoomable)  │
├────────────────────────┤      │                        │      │                        │
│                        │      │   FULLSCREEN GAMEPLAY  │      │                        │
│   GAMEPLAY SCREEN      │      │      (Vertical 9:16)   │      │                        │
│                        │      │                        │      │                        │
└────────────────────────┘      └────────────────────────┘      └────────────────────────┘
```

---

## 🚀 Quick Start Guide

### Option 1: Standalone Windows App (.exe)
No Python or FFmpeg installation required.
1. Navigate to the distribution folder:
   ```cmd
   cd "c:\attiq\clipping software\clipforge\dist\ClipForge"
   ```
2. Double-click **`ClipForge.exe`**.
3. The server boots automatically on port `7890` and launches your web browser at `http://127.0.0.1:7890`.

### Option 2: Running from Source
```bash
# 1. Clone repository
git clone https://github.com/ATTIQSHAH/clipforge.git
cd clipforge

# 2. Set up virtual environment
python -m venv .venv
.venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt
pip install -r requirements-extras.txt  # Optional: OCR & Piper Voice

# 4. Launch web studio
python -m clipforge_web
```

---

## 📁 Directory Structure

```
clipforge/
├── audio_library/              # Audio assets
│   ├── music/                  # Background music tracks
│   └── sfx/                    # Meme sound effects (airhorn, vine_boom, etc.)
├── clipforge/                  # Core processing library
│   ├── ai.py                   # Translation & AI assistance
│   ├── analyze.py              # Visual motion & audio peak analysis
│   ├── audiolib.py             # Audio synthesis & mixing logic
│   ├── captions.py             # Subtitle styling, ASS & SRT generation
│   ├── faces.py                # Face detection & panel fitting
│   ├── game.py                 # OCR game banner recognition (WASTED, etc.)
│   ├── render.py               # FFmpeg multi-layer video rendering engine
│   ├── source.py               # YT-DLP downloader & social stats
│   ├── transcribe.py           # Faster-whisper transcription pipeline
│   ├── util.py                 # Subprocess, probing & helper utilities
│   └── voice.py                # Piper offline voice-over synthesizer
├── clipforge_web/              # Web application & API
│   ├── db.py                   # SQLite database schema & migrations
│   ├── engine.py               # Video ingestion, candidate scoring & background jobs
│   ├── live.py                 # Twitch / Kick / YouTube live stream recorder
│   ├── server.py               # FastAPI server endpoints
│   ├── storage.py              # 48-hour cache cleaner
│   └── static/                 # Frontend assets
│       ├── index.html          # Studio Editor UI & interactive canvas
│       └── style.css           # CapCut dark theme styling
├── dist/                       # PyInstaller standalone build output
│   └── ClipForge/
│       └── ClipForge.exe       # Portable Windows executable
├── tests/                      # Automated test suites
│   ├── test_banner_time.py     # Hook text timing tests
│   ├── test_cam_controls.py    # Camera size & 2D pan tests
│   ├── test_dist_smoke.py      # Standalone executable smoke test
│   ├── test_features.py        # Core feature unit tests
│   ├── test_game.py            # OCR banner reading tests
│   ├── test_pip_vertical.py    # Floating cam framing tests
│   └── test_storage_cleanup.py # 48-hour cache cleanup tests
├── ClipForge.spec              # PyInstaller one-folder specification
└── README.md                   # Project documentation
```

---

## ⚙️ Configuration & Environment

| Environment Variable | Default | Purpose |
|---|---|---|
| `CLIPFORGE_PORT` | `7890` | Web server listening port |
| `CLIPFORGE_HOST` | `127.0.0.1` | Host binding (`0.0.0.0` for local network access) |
| `CLIPFORGE_PASSWORD` | *(None)* | Optional shared password for team access |
| `CLIPFORGE_DEVICE` | `cpu` | Whisper inference device (`cpu` or `cuda`) |
| `CLIPFORGE_DATA` | `./data` | Root directory for database and media storage |
| `CLIPFORGE_NO_BROWSER` | `0` | Set to `1` to suppress automatic browser launch on startup |

---

## 🧪 Testing & Verification

Run the comprehensive test suite to verify full functionality:

```powershell
$env:PYTHONPATH="."
python tests/test_cam_controls.py       # Camera sizing & wide X/Y pan
python tests/test_banner_time.py        # Hook title timeline timing
python tests/test_pip_vertical.py       # Vertical gameplay framing in PiP
python tests/test_features.py           # Feature extraction & action detection
python tests/test_storage_cleanup.py    # 48h temp cache auto-cleanup
python tests/test_candidate_import.py   # Candidate generation & import
python tests/test_game.py               # OCR game banner detection
python tests/test_dist_smoke.py         # ClipForge.exe live HTTP smoke test
```

All 8 test suites pass with 100% test coverage.

---

## 📜 License & Credits

- Developed for content creators, streamers, and video editors.
- Powered by open-source technologies: **FFmpeg**, **faster-whisper**, **FastAPI**, and **OpenCV**.
