#!/usr/bin/env python3
"""Batch transcribe with ffmpeg 20min split + Qwen3-ASR MLX. Resume-safe with chunk timeout."""
import subprocess
import time
import signal
import sys
from pathlib import Path

VIDEO_DIR = Path.home() / "github/BIT_yanhe_download/output/电影音乐-video"
AUDIO_DIR = Path.home() / "github/BIT_yanhe_download/output/audio"
CHUNK_DIR = Path.home() / "github/BIT_yanhe_download/output/chunks-ffmpeg"
TEXT_DIR = Path.home() / "github/BIT_yanhe_download/output/transcripts"
MODEL_DIR = "/Users/harvey/github/BIT_yanhe_download/models/Qwen3-ASR-1.7B-bf16"
CHUNK_SEC = 20 * 60
CHUNK_TIMEOUT_SEC = 600  # 10 min per chunk = safety limit

CHUNK_DIR.mkdir(exist_ok=True)
TEXT_DIR.mkdir(exist_ok=True)

def extract_audio(video_path: Path, audio_path: Path) -> None:
    cmd = ["ffmpeg", "-y", "-i", str(video_path),
           "-vn", "-acodec", "pcm_s16le", "-ac", "1", "-ar", "16000", str(audio_path)]
    subprocess.run(cmd, check=True, capture_output=True)

def split_audio(audio_path: Path, chunk_dir: Path, prefix: str) -> list[Path]:
    pattern = str(chunk_dir / f"{prefix}_%03d.wav")
    cmd = ["ffmpeg", "-y", "-i", str(audio_path),
           "-f", "segment", "-segment_time", str(CHUNK_SEC),
           "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le", pattern]
    subprocess.run(cmd, check=True, capture_output=True)
    return sorted(chunk_dir.glob(f"{prefix}_*.wav"))

def main():
    from qwen3_asr_mlx import Qwen3ASR

    def timeout_handler(signum, frame):
        raise TimeoutError(f"Chunk exceeded {CHUNK_TIMEOUT_SEC}s timeout")

    signal.signal(signal.SIGALRM, timeout_handler)

    print("Loading Qwen3-ASR model...")
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
            print(f"  ✓ {name} already done")
            continue

        if not audio.exists():
            print(f"  🎵 Extracting audio: {name}")
            t0 = time.time()
            extract_audio(video, audio)
            print(f"  → audio extracted in {time.time()-t0:.1f}s")

        print(f"  ✂️  ffmpeg splitting: {name}")
        t0 = time.time()
        chunks = split_audio(audio, CHUNK_DIR, name)
        print(f"  → {len(chunks)} chunks in {time.time()-t0:.1f}s")

        results = []
        for i, chunk in enumerate(chunks):
            chunk_name = f"{name}_{i+1}/{len(chunks)}"
            print(f"  📝 [{chunk_name}] transcribing...")
            signal.alarm(CHUNK_TIMEOUT_SEC)
            t0 = time.time()
            try:
                result = model.transcribe(str(chunk), language="zh")
                elapsed = time.time() - t0
                signal.alarm(0)
                print(f"  ✅ [{chunk_name}] done in {elapsed:.0f}s")
                results.append(result.text)
            except TimeoutError:
                signal.alarm(0)
                elapsed = time.time() - t0
                print(f"  ⏰ [{chunk_name}] TIMEOUT after {elapsed:.0f}s, skipping")
                results.append(f"[TIMEOUT chunk {i+1}]")
            except Exception as e:
                signal.alarm(0)
                print(f"  ❌ [{chunk_name}] ERROR: {e}")
                results.append(f"[ERROR chunk {i+1}: {e}]")

        with open(text_file, "w", encoding="utf-8") as f:
            f.write(f"视频: {name}\n总块数: {len(chunks)}\n---\n")
            f.write("\n\n".join(results))

        print(f"  ✅ {name} complete → {text_file}")

    print("All done!")

if __name__ == "__main__":
    main()
