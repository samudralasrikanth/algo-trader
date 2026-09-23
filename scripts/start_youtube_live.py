#!/usr/bin/env python3
"""
scripts/start_youtube_live.py — Broadcast NEXUS Live Trading to YouTube Live

Streams the live trading web dashboard (P&L, 5 Multi-Agents, Nifty 50 flow)
directly to YouTube Live via RTMP using FFmpeg or OBS Studio.

Usage:
  python3 scripts/start_youtube_live.py --stream-key "YOUR_KEY_HERE"
  or set YOUTUBE_STREAM_KEY in .env
"""

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

REPO_DIR = Path(__file__).resolve().parents[1]
load_dotenv(REPO_DIR / ".env")

YOUTUBE_RTMP_URL = "rtmp://a.youtube.com/live2"
DASHBOARD_URL = "https://nifty50-event-agent.netlify.app"


def check_ffmpeg() -> bool:
    return bool(shutil.which("ffmpeg"))


def launch_obs_instructions():
    print("""
======================================================================
  ⚡ NEXUS YOUTUBE LIVE STREAMING SETUP (OBS STUDIO - FREE) ⚡
======================================================================

1. Download & open OBS Studio (Free): https://obsproject.com/
2. In OBS, click [+] in 'Sources' -> Select 'Browser'
   - URL: https://nifty50-event-agent.netlify.app (or http://localhost:8080)
   - Width: 1920, Height: 1080
   - FPS: 30
3. (Optional) Add your custom cartoon avatar or webcam as an image/video source!
4. Go to Settings -> Stream:
   - Service: YouTube - RTMPS
   - Server: Primary YouTube ingest server
   - Stream Key: [Paste your YouTube stream key from YouTube Studio]
5. Click 'Start Streaming' during market hours (09:15 to 15:30 IST).
======================================================================
""")


def start_ffmpeg_stream(stream_key: str):
    if not check_ffmpeg():
        print("[!] FFmpeg not found on PATH.")
        print("[*] You can install it via Homebrew: brew install ffmpeg")
        print("[*] Or stream directly with OBS Studio (recommended):")
        launch_obs_instructions()
        return

    rtmp_destination = f"{YOUTUBE_RTMP_URL}/{stream_key}"
    print(f"[*] Connecting live broadcast to: {YOUTUBE_RTMP_URL}...")
    print(f"[*] Streaming dashboard: {DASHBOARD_URL}")
    print("[*] Press Ctrl+C to terminate the live broadcast.")

    # Native macOS AVFoundation screen capture command
    cmd = [
        "ffmpeg",
        "-f", "avfoundation",
        "-framerate", "30",
        "-video_size", "1920x1080",
        "-i", "1:none",  # Capture primary display
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-b:v", "3500k",
        "-maxrate", "4000k",
        "-bufsize", "8000k",
        "-pix_fmt", "yuv420p",
        "-g", "60",
        "-c:a", "aac",
        "-b:a", "128k",
        "-ar", "44100",
        "-f", "flv",
        rtmp_destination,
    ]

    try:
        subprocess.run(cmd, check=True)
    except KeyboardInterrupt:
        print("\n[✓] Live stream ended cleanly.")
    except Exception as e:
        print(f"[!] Stream exited: {e}")


def main():
    parser = argparse.ArgumentParser(description="Broadcast NEXUS Live Trading to YouTube")
    parser.add_argument("--stream-key", default=os.getenv("YOUTUBE_STREAM_KEY"), help="YouTube Live Stream Key")
    parser.add_argument("--obs", action="store_true", help="Print OBS Studio setup guide")
    args = parser.parse_args()

    if args.obs or not args.stream_key:
        launch_obs_instructions()
        if not args.stream_key:
            print("[NOTE] To run automated headless streaming, provide --stream-key or set YOUTUBE_STREAM_KEY in .env")
        return

    start_ffmpeg_stream(args.stream_key)


if __name__ == "__main__":
    main()
