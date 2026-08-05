#!/usr/bin/env python3
"""Batch transcribe with whisper.cpp using Metal GPU."""
import subprocess
import time
from pathlib import Path

AUDIO_DIR = Path.home() / "github/BIT_yanhe_download/output/audio"
TRANSCRIPT_DIR = Path.home() / "github/BIT_yanhe_download/output/transcripts-whisper"
MODEL = Path.home() / "github/whisper.cpp/models/ggml-medium.bin"
WHISPER_CLI = Path.home() / "github/whisper.cpp/build/bin/whisper-cli"

TRANSCRIPT_DIR.mkdir(exist_ok=True)

wavs = sorted(AUDIO_DIR.glob("*.wav"))
print(f"Found {len(wavs)} audio files")

for wav in wavs:
    name = wav.stem
    txt = TRANSCRIPT_DIR / f"{name}.txt"

    if txt.exists():
        print(f"  ✓ {name} already done")
        continue

    print(f"  📝 {name}")
    t0 = time.time()

    cmd = [
        str(WHISPER_CLI),
        "-m", str(MODEL),
        "-f", str(wav),
        "--language", "zh",
        "--max-context", "-1",
        "--log-score", "yes",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    elapsed = time.time() - t0
    print(f"  ✅ {name} done in {elapsed:.0f}s")

    # Extract transcription from output
    lines = result.stdout.strip().split("\n")
    transcription_lines = [l for l in lines if l.startswith("[00:")]
    text = "\n".join(transcription_lines)

    with open(txt, "w", encoding="utf-8") as f:
        f.write(f"whisper.cpp medium\n")
        f.write(f"时长: {elapsed:.0f}s\n")
        f.write(f"---\n")
        f.write(text)

    print(f"  📄 saved: {txt}")

print("All done!")
