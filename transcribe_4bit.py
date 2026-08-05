#!/usr/bin/env python3
"""Batch transcribe videos in 20-minute chunks with Qwen3-ASR via MLX."""
import os
import subprocess
import time
from pathlib import Path

VIDEO_DIR = Path.home() / "github/BIT_yanhe_download/output/电影音乐-video"
AUDIO_DIR = Path.home() / "github/BIT_yanhe_download/output/audio"
CHUNK_DIR = Path.home() / "github/BIT_yanhe_download/output/chunks"
TEXT_DIR = Path.home() / "github/BIT_yanhe_download/output/transcripts"
MODEL_DIR = "/Users/harvey/github/BIT_yanhe_download/models/Qwen3-ASR-1.7B-4bit"

AUDIO_DIR.mkdir(exist_ok=True)
CHUNK_DIR.mkdir(exist_ok=True)
TEXT_DIR.mkdir(exist_ok=True)

CHUNK_SEC = 20 * 60  # 20 minutes

def extract_audio(video_path: Path, audio_path: Path) -> None:
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vn", "-acodec", "pcm_s16le",
        "-ac", "1", "-ar", "16000",
        str(audio_path)
    ]
    subprocess.run(cmd, check=True, capture_output=True)

def split_audio(audio_path: Path, chunk_dir: Path, prefix: str) -> list[Path]:
    """Split audio into 20-minute chunks."""
    pattern = str(chunk_dir / f"{prefix}_%03d.wav")
    cmd = [
        "ffmpeg", "-y", "-i", str(audio_path),
        "-f", "segment", "-segment_time", str(CHUNK_SEC),
        "-ac", "1", "-ar", "16000",
        "-acodec", "pcm_s16le",
        pattern
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return sorted(chunk_dir.glob(f"{prefix}_*.wav"))

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
        text_file = TEXT_DIR / f"{name}.txt"

        if text_file.exists():
            print(f"  ✓ {name} already transcribed")
            continue

        if not audio.exists():
            print(f"  🎵 Extracting audio: {name}")
            extract_audio(video, audio)

        print(f"  ✂️  Splitting into 20min chunks: {name}")
        chunks = split_audio(audio, CHUNK_DIR, name)
        print(f"  → {len(chunks)} chunks")

        results = []
        for i, chunk in enumerate(chunks):
            print(f"  📝 Transcribing chunk {i+1}/{len(chunks)}: {chunk.name}")
            t0 = time.time()
            result = model.transcribe(str(chunk), language="zh")
            elapsed = time.time() - t0
            print(f"  ✅ Chunk {i+1} done in {elapsed:.1f}s")
            results.append(result.text)

        with open(text_file, "w", encoding="utf-8") as f:
            f.write(f"视频: {name}\n")
            f.write(f"总块数: {len(chunks)}\n")
            f.write(f"---\n")
            f.write("\n\n".join(results))

        print(f"  🎉 {name} complete: {text_file}")

    print("All done!")

if __name__ == "__main__":
    main()
