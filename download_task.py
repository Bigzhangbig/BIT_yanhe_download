import utils
import m3u8dl
import os

def main():
    # 1. 设置认证
    auth = utils.read_auth()
    if not auth:
        print("错误: 未找到 auth.txt，请先进行认证。")
        return
    print(f"已读取认证信息，auth 前20字符: {auth[:20]}...")

    # 2. 获取课程信息
    courseID = "68010"
    print(f"正在获取课程 {courseID} 的信息...")
    videoList, course_name, professor = utils.get_course_info(courseID)
    print(f"课程名称: {course_name}")
    print(f"教师: {professor}")
    print(f"总视频数: {len(videoList)}")

    # 3. 取第30节课（索引29）
    index = 30 - 1
    if index >= len(videoList):
        print(f"错误: 课程只有 {len(videoList)} 节课，无法获取第30节（索引{index}）")
        return

    session = videoList[index]
    print(f"第30节信息:")
    print(f"  标题: {session.get('title', 'N/A')}")
    print(f"  videos数量: {len(session.get('videos', []))}")

    # 4. 获取 main URL
    videos = session.get("videos", [])
    if not videos:
        print("错误: 该节课没有视频信息")
        return

    main_url = videos[0].get("main")
    if not main_url:
        print("错误: 无法获取 main URL（摄像头信号）")
        return

    print(f"  main URL: {main_url[:80]}...")

    # 5. 构建输出路径和文件名
    output_dir = f"output/{course_name}-video"
    session_title = session.get("title", "未知标题")
    filename = f"{course_name}-{professor}-第30节-{session_title}"
    # 清理文件名中的非法字符
    filename = "".join(c for c in filename if c not in '\\/:*?"<>|').strip()

    print(f"\n开始下载...")
    print(f"  输出目录: {output_dir}")
    print(f"  文件名: {filename}")

    # 6. 下载
    try:
        m3u8dl.M3u8Download(main_url, output_dir, filename)
        print(f"\n下载完成！")
        print(f"文件保存路径: {os.path.join(os.getcwd(), output_dir, filename + '.mp4')}")
    except Exception as e:
        print(f"\n下载失败: {e}")
        raise

if __name__ == "__main__":
    main()
