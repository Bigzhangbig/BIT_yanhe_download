"""Transcribe aac files to plain .txt using MLX Qwen3-ASR (no timestamps)."""
import os
import subprocess
import sys
import tempfile
import time

from gen_caption import (
    DEFAULT_MODEL,
    QWEN3_ASR_MODELS,
    convert_to_simplified_chinese,
    get_result_segments,
    load_asr_model,
    seconds_to_hmsm,
)

AUDIO_DIR = "output/中国近现代史纲要-audio"
OUTPUT_DIR = "output/transcripts"


def prepare_wav(aac_path: str) -> tuple[str, bool]:
    """Convert aac to 16kHz mono wav in same dir (temp file)."""
    name = os.path.splitext(os.path.basename(aac_path))[0]
    out_path = os.path.join(
        os.path.dirname(os.path.abspath(aac_path)),
        f"{name}-asr-tmp.wav",
    )
    if os.path.exists(out_path):
        return out_path, False
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        aac_path,
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        out_path,
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out_path, True


def write_txt(result, txt_path: str) -> None:
    """Write transcription as plain text with optional timestamped segments."""
    segments = get_result_segments(result)
    with open(txt_path, "w", encoding="utf-8") as f:
        for seg in segments:
            if isinstance(seg, dict):
                start = seg.get("start", seg.get("start_time", 0))
                end = seg.get("end", seg.get("end_time", 0))
                text = seg.get("text", "")
            else:
                start = getattr(seg, "start", getattr(seg, "start_time", 0))
                end = getattr(seg, "end", getattr(seg, "end_time", 0))
                text = getattr(seg, "text", "")
            text = convert_to_simplified_chinese(text).strip()
            if not text:
                continue
            f.write(f"[{seconds_to_hmsm(start)} --> {seconds_to_hmsm(end)}]  {text}\n")


def main() -> int:
    model_name = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_MODEL
    if model_name.isdigit():
        model_name = QWEN3_ASR_MODELS[int(model_name)]
    print(f"using model: {model_name}")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    aac_files = sorted(
        os.path.join(AUDIO_DIR, f) for f in os.listdir(AUDIO_DIR) if f.endswith(".aac")
    )
    if not aac_files:
        print(f"no aac files in {AUDIO_DIR}")
        return 1
    print(f"found {len(aac_files)} aac files")

    print("loading model...")
    t0 = time.time()
    model = load_asr_model(model_name)
    print(f"model loaded in {time.time() - t0:.1f}s")

    for aac_path in aac_files:
        base = os.path.splitext(os.path.basename(aac_path))[0]
        txt_path = os.path.join(OUTPUT_DIR, base + ".txt")
        if os.path.exists(txt_path) and os.path.getsize(txt_path) > 200:
            print(f"[exists] {txt_path} -- skip")
            continue
        print(f"\n[transcribe] {aac_path}")
        wav_path, is_tmp = prepare_wav(aac_path)
        try:
            t0 = time.time()
            result = model.generate(
                wav_path,
                language="Chinese",
                chunk_duration=30.0,
                max_tokens=65536,
                verbose=True,
            )
            dt = time.time() - t0
            write_txt(result, txt_path)
            size_kb = os.path.getsize(txt_path) / 1024
            print(f"[done] {txt_path} ({size_kb:.1f} KB, {dt:.1f}s)")
        finally:
            if is_tmp and os.path.exists(wav_path):
                os.remove(wav_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())