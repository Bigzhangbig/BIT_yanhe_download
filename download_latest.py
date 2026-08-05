"""Download the latest episode screen-recording for course 68948."""

import os
import sys

import m3u8dl
import utils


COURSE_ID = "68948"


def main() -> int:
    utils.read_auth()
    video_list, course_name, prof = utils.get_course_info(COURSE_ID)
    print(f"course: {course_name}")
    print(f"teacher: {prof}")
    print(f"episodes: {len(video_list)}")

    latest = video_list[-1]
    print(f"latest episode: {latest['title']} (session_id={latest['id']})")
    v = latest["videos"][0]
    print(f"  vga url: {v['vga']}")
    print(f"  duration: {v['duration']}s")

    work_dir = f"output/{course_name}-screen"
    file_name = f"{course_name}-{prof}-{latest['title']}"
    file_path = os.path.join(work_dir, file_name + ".mp4")

    if os.path.exists(file_path):
        size_mb = os.path.getsize(file_path) / 1024 / 1024
        print(f"already exists: {file_path} ({size_mb:.1f} MB) -- skip")
        return 0

    print(f"work_dir={work_dir}")
    print(f"name={file_name}")

    last_pct = -1

    def progress(cur, tot, merge_status):
        nonlocal last_pct
        if merge_status == 0:
            if tot:
                pct = 100 * cur // tot
                if pct != last_pct and (pct % 5 == 0 or cur == tot):
                    print(f"  [download] {cur}/{tot} ({pct}%)", flush=True)
                    last_pct = pct
        elif merge_status == 1:
            print("  [merge] ffmpeg combining .ts -> .mp4 ...", flush=True)
        elif merge_status == 2:
            print("  [done] OK", flush=True)

    m3u8dl.M3u8Download(
        v["vga"], work_dir, file_name, progress_callback=progress
    )

    if os.path.exists(file_path):
        size_mb = os.path.getsize(file_path) / 1024 / 1024
        print(f"\nfinal file: {file_path} ({size_mb:.1f} MB)")
        return 0
    print("ERROR: output file not found", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
