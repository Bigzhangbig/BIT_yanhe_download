#!/usr/bin/env python3
"""Batch transcribe videos with Qwen3-ASR via MLX."""
import os
import sys
import subprocess
import time
from pathlib import Path

VIDEO_DIR = Path.home() / "github/BIT_yanhe_download/output/电影音乐-video"
AUDIO_DIR = Path.home() / "github/BIT_yanhe_download/output/audio"
TEXT_DIR = Path.home() / "github/BIT_yanhe_download/output/transcripts"
MODEL_DIR = "/Users/harvey/github/BIT_yanhe_download/models/Qwen3-ASR-1.7B-bf16"

AUDIO_DIR.mkdir(exist_ok=True)
TEXT_DIR.mkdir(exist_ok=True)

def extract_audio(video_path: Path, audio_path: Path) -> None:
    """Extract 16kHz mono WAV from MP4."""
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vn", "-acodec", "pcm_s16le",
        "-ac", "1", "-ar", "16000",
        str(audio_path)
    ]
    subprocess.run(cmd, check=True, capture_output=True)

def main():
    from qwen3_asr_mlx import Qwen3ASR

    print("Loading model...")
    t0 = time.time()
    model = Qwen3ASR.from_pretrained(MODEL_DIR)
    print(f"Model loaded in {time.time()-t0:.1f}s")

    print("Warming up...")
    t0 = time.time()
    model.warm_up()
    print(f"Warm up done in {time.time()-t0:.1f}s")

    videos = sorted(VIDEO_DIR.glob("*.mp4"))
    print(f"Found {len(videos)} videos")

    for video in videos:
        name = video.stem
        audio = AUDIO_DIR / f"{name}.wav"
        text = TEXT_DIR / f"{name}.txt"

        if text.exists():
            print(f"  ✓ {name} already transcribed")
            continue

        if not audio.exists():
            print(f"  🎵 Extracting audio: {name}")
            extract_audio(video, audio)

        print(f"  📝 Transcribing: {name}")
        t0 = time.time()
        result = model.transcribe(str(audio), language="zh")
        elapsed = time.time() - t0
        print(f"  ✅ Done in {elapsed:.1f}s: {text}")

        with open(text, "w", encoding="utf-8") as f:
            f.write(f"语言: {result.language}\n")
            f.write(f"时长: {result.duration:.1f}s\n")
            f.write(f"转录耗时: {elapsed:.1f}s\n")
            f.write(f"---\n")
            f.write(result.text)

    print("All done!")

if __name__ == "__main__":
    main()
