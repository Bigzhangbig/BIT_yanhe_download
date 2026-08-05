"""Download audio (aac) for two specific sessions of 中国近现代史纲要 course."""
import os
import sys

import utils

COURSE_ID = "68768"

# 倒数第二和倒数第三 (按时间排序的话 index 14 和 13, 也就是第 15 周和第 14 周)
TARGET_INDICES = [13, 14]  # 0-based index, 第 14 周 和 第 15 周


def main() -> int:
    utils.read_auth()
    video_list, course_name, prof = utils.get_course_info(COURSE_ID)
    print(f"course: {course_name}")
    print(f"teacher: {prof}")
    print(f"total episodes: {len(video_list)}")

    out_dir = f"output/{course_name}-audio"
    os.makedirs(out_dir, exist_ok=True)

    for idx in TARGET_INDICES:
        c = video_list[idx]
        title = c["title"]
        video_ids = c.get("video_ids", [])
        if not video_ids:
            print(f"[skip] {title}: no video_ids")
            continue
        first_vid = video_ids[0]
        name = f"{course_name}-{prof}-{title}"
        target = os.path.join(out_dir, name + ".aac")
        if os.path.exists(target) and os.path.getsize(target) > 1024:
            size_kb = os.path.getsize(target) / 1024
            print(f"[exists] {target} ({size_kb:.1f} KB) -- skip")
            continue

        print(f"\n[{idx}] {title} (video_id={first_vid})")
        audio_url = utils.get_audio_url(first_vid)
        if not audio_url:
            print(f"  no audio url for video_id={first_vid}, skip")
            continue
        print(f"  audio url: {audio_url[:100]}...")
        utils.download_audio(audio_url, out_dir, name)
        size_kb = os.path.getsize(target) / 1024
        print(f"  [done] {target} ({size_kb:.1f} KB)")

    return 0


if __name__ == "__main__":
    sys.exit(main())