import argparse
import os
import subprocess
import tempfile
import time


QWEN3_ASR_MODELS = [
    "mlx-community/Qwen3-ASR-1.7B-bf16",
    "mlx-community/Qwen3-ASR-1.7B-8bit",
    "mlx-community/Qwen3-ASR-1.7B-6bit",
    "mlx-community/Qwen3-ASR-1.7B-4bit",
]
DEFAULT_MODEL = QWEN3_ASR_MODELS[0]
MEDIA_EXTENSIONS = (".mp4", ".aac", ".m4a", ".wav", ".mp3", ".flac")
DEFAULT_CHUNK_DURATION = 30.0
DEFAULT_MAX_TOKENS = 65536


def seconds_to_hmsm(seconds):
    """
    输入一个秒数，输出为H:M:S,M时间格式
    @params:
        seconds   - Required  : 秒 (float)
    """
    total_milliseconds = max(0, int(round(float(seconds) * 1000)))
    total_seconds, milliseconds = divmod(total_milliseconds, 1000)
    minutes_total, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes_total, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def parse_index_list(raw_input, max_count):
    indexes = []
    for item in raw_input.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            index = int(item)
        except ValueError:
            print(f"ignore invalid input: {item}")
            continue
        if 0 <= index < max_count:
            indexes.append(index)
        else:
            print(f"ignore out-of-range input: {index}")
    return indexes


def find_media_files():
    files = []
    for dirpath, _, filenames in os.walk("."):
        for filename in filenames:
            if filename.lower().endswith(MEDIA_EXTENSIONS):
                files.append(os.path.join(dirpath, filename).replace("\\", "/"))
    return sorted(files)


def prompt_media_files():
    files = find_media_files()
    if not files:
        raise FileNotFoundError("current directory has no supported media files")

    for i, file_path in enumerate(files):
        print(f"[{i}]: {file_path}")

    raw_input = input("select media files by input nums(split with ','): ")
    indexes = parse_index_list(raw_input, len(files))
    if not indexes:
        raise ValueError("no valid media file selected")

    video_paths = [files[index] for index in indexes]
    print("selected media files:", video_paths)
    return video_paths


def prompt_model():
    for i, model in enumerate(QWEN3_ASR_MODELS):
        print(f"[{i}]: {model}")

    raw_input = input(
        f"select a model by input a num(default '{DEFAULT_MODEL}'): "
    ).strip()
    if not raw_input:
        return DEFAULT_MODEL

    try:
        return QWEN3_ASR_MODELS[int(raw_input)]
    except (ValueError, IndexError):
        print("selected custom model:", raw_input)
        return raw_input


def prepare_audio(media_path):
    _, ext = os.path.splitext(media_path)
    if ext.lower() == ".wav":
        return media_path, False

    media_dir = os.path.dirname(os.path.abspath(media_path)) or "."
    media_name = os.path.splitext(os.path.basename(media_path))[0]
    with tempfile.NamedTemporaryFile(
        prefix=f"{media_name}-caption-",
        suffix=".wav",
        dir=media_dir,
        delete=False,
    ) as temp_file:
        audio_path = temp_file.name

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        media_path,
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        audio_path,
    ]
    try:
        subprocess.run(cmd, check=True)
    except Exception:
        os.remove(audio_path)
        raise
    return audio_path, True


def get_segment_value(segment, key):
    if isinstance(segment, dict):
        if key in segment:
            return segment[key]
        if key == "start":
            return segment["start_time"]
        if key == "end":
            return segment["end_time"]
        raise KeyError(key)
    return getattr(segment, key)


def get_result_segments(result):
    segments = getattr(result, "segments", None)
    if segments:
        return segments
    text = getattr(result, "text", "").strip()
    if not text:
        return []
    return [{"start": 0, "end": 0, "text": text}]


def load_asr_model(model_name):
    try:
        from mlx_audio.stt import load_model
    except ImportError as error:
        raise RuntimeError(
            "MLX ASR dependencies are not installed. "
            "Run `uv sync --extra asr` before generating captions."
        ) from error

    return load_model(model_name)


def convert_to_simplified_chinese(text):
    try:
        from zhconv import convert
    except ImportError as error:
        raise RuntimeError(
            "Chinese conversion dependency is not installed. "
            "Run `uv sync --extra asr` before generating captions."
        ) from error

    return convert(text, "zh-cn")


def write_srt(result, srt_path):
    with open(srt_path, "w", encoding="utf-8") as file:
        for i, segment in enumerate(get_result_segments(result), start=1):
            start = get_segment_value(segment, "start")
            end = get_segment_value(segment, "end")
            text = get_segment_value(segment, "text")

            file.write(str(i) + "\n")
            file.write(f"{seconds_to_hmsm(start)} --> {seconds_to_hmsm(end)}\n")
            file.write(convert_to_simplified_chinese(text) + "\n")
            file.write("\n")


def transcribe_media(model, media_path, language, chunk_duration, max_tokens, verbose):
    base_path, _ = os.path.splitext(media_path)
    audio_path, should_delete_audio = prepare_audio(media_path)
    try:
        start = time.time()
        result = model.generate(
            audio_path,
            language=language,
            chunk_duration=chunk_duration,
            max_tokens=max_tokens,
            verbose=verbose,
        )
        print("Time cost: ", time.time() - start)
        write_srt(result, base_path + ".srt")
    finally:
        if should_delete_audio:
            os.remove(audio_path)


def main():
    parser = argparse.ArgumentParser(
        description="Generate SRT captions with MLX Qwen3-ASR."
    )
    parser.add_argument(
        "media_paths",
        nargs="*",
        help="media file paths. Leave empty to select files interactively.",
    )
    parser.add_argument(
        "-m",
        "--model",
        default=None,
        help=f"MLX Qwen3-ASR model name. Default: {DEFAULT_MODEL}",
    )
    parser.add_argument(
        "-l",
        "--language",
        default="Chinese",
        help="recognition language passed to Qwen3-ASR. Default: Chinese",
    )
    parser.add_argument(
        "--chunk-duration",
        type=float,
        default=DEFAULT_CHUNK_DURATION,
        help=f"audio chunk duration in seconds. Default: {DEFAULT_CHUNK_DURATION}",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=DEFAULT_MAX_TOKENS,
        help=f"maximum generated tokens for each media file. Default: {DEFAULT_MAX_TOKENS}",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="show MLX Audio generation progress.",
    )
    args = parser.parse_args()

    media_paths = args.media_paths or prompt_media_files()
    model_name = args.model or (DEFAULT_MODEL if args.media_paths else prompt_model())
    print("selected model:", model_name)

    model = load_asr_model(model_name)
    for media_path in media_paths:
        transcribe_media(
            model,
            media_path,
            args.language,
            args.chunk_duration,
            args.max_tokens,
            args.verbose,
        )


if __name__ == "__main__":
    main()
