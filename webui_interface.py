import multiprocessing
import os
import threading
import time
import uuid
import webbrowser
from queue import Empty, Queue

from dotenv import load_dotenv
from flask import (
    Flask,
    jsonify,
    render_template,
    request,
    send_from_directory,
)

import m3u8dl
import utils

load_dotenv()

app = Flask(__name__, static_folder="webui")

"""
    {
        "url":
        "output":
        "name":
        "cur":
        "tot":
        "uuid":
        "canceled":
        "merge_status": 
        "download_type":
        "download_audio": bool
        "audio_url":
    }
"""
all_task_status = []


"""
    {
        "uuid"
    }
"""
task_queue = Queue()


def find_all_task_by_uuid(uuid):
    for id, task in enumerate(all_task_status):
        if task["uuid"] == uuid:
            return task, id
    return None


g_father_queue = None
current_task_uuid = ""


def executor_progress_callback(cur, tot, merge_status):
    global g_father_queue, current_task_uuid
    g_father_queue.put(
        {
            "uuid": current_task_uuid,
            "cur": cur,
            "tot": tot,
            "merge_status": merge_status,
        }
    )
    # print({
    #     "uuid": current_task_uuid,
    #     "cur": cur,
    #     "tot": tot,
    #     "merge_status": merge_status
    # })
    return False


def execute_one_download_task_worker(task_dict, father_queue):
    global current_task_uuid, g_father_queue
    print(f"downloading task {task_dict}")
    current_task_uuid = task_dict["uuid"]
    output = task_dict["output"]
    name = task_dict["name"]
    g_father_queue = father_queue
    if task_dict.get("download_type") == "3":
        # 双轨合并: main + vga + 蓝牙 -> mkv
        os.makedirs(output, exist_ok=True)
        print("Downloading camera (main)...")
        m3u8dl.M3u8Download(task_dict["main_url"], output, name + "-main", progress_callback=executor_progress_callback)
        print("Downloading screen (vga)...")
        m3u8dl.M3u8Download(task_dict["vga_url"], output, name + "-vga", progress_callback=executor_progress_callback)
        audio_aac = None
        audio_url = task_dict.get("audio_url", "")
        if audio_url:
            print("Downloading bluetooth audio...")
            utils.download_audio(audio_url, output, name + "-main")
            audio_aac = os.path.join(output, name + "-main.aac")
        mkv_path = os.path.join(output, name + ".mkv")
        print("Merging to mkv...")
        m3u8dl.merge_to_mkv(
            os.path.join(output, name + "-main.mp4"),
            os.path.join(output, name + "-vga.mp4"),
            audio_aac,
            mkv_path,
            vga_offset=-0.5,
        )
        print(f"Merged: {mkv_path}")
        return
    url = task_dict["url"]
    m3u8dl.M3u8Download(url, output, name, progress_callback=executor_progress_callback)
    if task_dict["download_audio"]:
        audio_url = task_dict["audio_url"]
        if audio_url:
            print("Downloading audio...")
            utils.download_audio(audio_url, output, name)
            print("Download audio successfully.")
    return


def execute_tasks():
    global all_task_status
    queue = multiprocessing.Queue()
    while True:
        try:
            task = task_queue.get(timeout=1)
            task_uuid = task["uuid"]
            task_obj, task_id = find_all_task_by_uuid(task_uuid)
            if task_obj["canceled"] is True:
                all_task_status.pop(task_id)
                continue
            process = multiprocessing.Process(
                target=execute_one_download_task_worker, args=(task_obj, queue)
            )
            process.start()
            while True:
                if all_task_status[task_id]["canceled"]:
                    print("task canceled, terminate subprocess...")
                    process.terminate()
                    all_task_status.pop(task_id)
                    break
                try:
                    msg = queue.get_nowait()
                    update_obj, update_id = find_all_task_by_uuid(msg["uuid"])
                    all_task_status[update_id]["cur"] = msg["cur"]
                    all_task_status[update_id]["tot"] = msg["tot"]
                    all_task_status[update_id]["merge_status"] = msg["merge_status"]
                except Empty:
                    if process.is_alive() is False:
                        break
                    time.sleep(0.1)
                    continue
                except TypeError:
                    continue
        except Empty:
            continue
        except TypeError:
            continue


@app.route("/")
def index():
    auth = utils.read_auth()
    return render_template(
        "index.html",
        auth=auth,
        auth_prompt="" if auth else "。".join(utils.auth_prompt()),
    )


@app.route("/get_course")
def get_course():
    course_id = request.args.get("course_id")
    auth = request.args.get("auth")
    if auth:
        utils.write_auth(auth)
    if not utils.test_auth(courseID=course_id):
        # 尝试 SSO 自动登录
        if utils.ensure_auth(courseID=course_id):
            pass
        else:
            utils.remove_auth()
            return jsonify({"code": 403, "msg": "。".join(utils.auth_prompt(False))})
    try:
        videoList, courseName, professor = utils.get_course_info(courseID=course_id)
    except Exception:
        return jsonify({"videoList": [], "courseName": "", "professor": ""})
    return jsonify(
        {"videoList": videoList, "courseName": courseName, "professor": professor}
    )


@app.route("/new_task", methods=["POST"])
def new_task():
    global task_queue, all_task_status
    data = request.json
    course_id = data["course_id"]
    course_number = data["course_number"]
    download_version = data["download_version"]
    download_audio = data["download_audio"]
    videoList, courseName, professor = utils.get_course_info(courseID=course_id)
    course_number_arr = course_number.split(",")
    ret_id = []
    for courseNum in course_number_arr:
        courseNumT = int(courseNum)
        c = videoList[courseNumT]
        name = courseName + "-" + professor + "-" + c["title"]
        print(name)

        cur_uuid = str(uuid.uuid4())
        ret_id.append(cur_uuid)
        task_status = {
            "url": "",
            "output": "",
            "name": name,
            "cur": 0,
            "tot": 0,
            "uuid": cur_uuid,
            "canceled": False,
            "merge_status": 0,
            "download_type": download_version,
            "download_audio": download_audio == "1",
            "audio_url": "",
        }

        task_status["audio_url"] = utils.get_audio_url(c["video_ids"][0])
        if download_version == "3":
            # 双轨合并: main + vga + 蓝牙 -> mkv
            task_status["main_url"] = c["videos"][0]["main"]
            task_status["vga_url"] = c["videos"][0]["vga"]
            task_status["url"] = c["videos"][0]["main"]
            task_status["output"] = "output/" + courseName + "-merged"
        elif download_version == "2":
            print("Downloading screen...")
            task_status["url"] = c["videos"][0]["vga"]
            task_status["output"] = "output/" + courseName + "-screen"
        else:
            print("Downloading video...")
            task_status["url"] = c["videos"][0]["main"]
            task_status["output"] = "output/" + courseName + "-video"
        all_task_status.append(task_status)
        task_queue.put({"uuid": cur_uuid})

    return jsonify({"status": "success", "task_id": ret_id})


@app.route("/get_status")
def get_status():
    global all_task_status
    return jsonify(all_task_status)


@app.route("/kill_task")
def kill_task():
    global all_task_status
    uuid = request.args.get("uuid")
    task, id = find_all_task_by_uuid(uuid)
    if task["merge_status"] == 2:
        # if already finished
        all_task_status.pop(id)
        return jsonify({"status": "ok"})
    all_task_status[id]["canceled"] = True
    return jsonify({"status": "ok"})


@app.route("/sso_login", methods=["POST"])
def sso_login():
    """通过 BIT SSO 登录 (3 层 fallback: requests -> headless -> 有头自动启动)。
    完整处理所有登录场景, 撞 captcha 时自动启动有头浏览器弹窗,
    用户在弹窗中完成登录, 无需终端跑任何脚本。
    注意: Tier 3 有头浏览器会弹窗, 可能耗时几分钟, threaded 模式下不阻塞其他请求。
    """
    data = request.json or {}
    student_id = data.get("student_id", "") or None
    password = data.get("password", "") or None
    course_id = data.get("course_id", "")
    try:
        from login_sso_unified import run_unified_login, EXIT_OK, EXIT_PASSWORD_WRONG
        rc = run_unified_login(
            username=student_id,
            password=password,
            quiet=False,
            auth_file="auth.txt",
        )
        if rc == EXIT_OK and utils.read_auth():
            if course_id and not utils.test_auth(courseID=course_id):
                return jsonify({"code": 403, "msg": "SSO 登录成功，但课程验证失败"})
            return jsonify({"code": 0, "msg": "登录成功"})
        if rc == EXIT_PASSWORD_WRONG:
            return jsonify({"code": 401, "msg": "账号或密码错误, 请检查 .env 中的 STUDENT_ID/PASSWORD"})
        return jsonify({"code": 401, "msg": f"SSO 登录失败 (exit={rc}), 请重试或检查凭据"})
    except Exception as e:
        return jsonify({"code": 401, "msg": str(e)})


@app.route("/sso_config")
def sso_config():
    """检查 .env 中是否配置了学号和密码"""
    load_dotenv()
    has_student_id = bool(os.getenv("STUDENT_ID"))
    has_password = bool(os.getenv("PASSWORD"))
    return jsonify({
        "has_student_id": has_student_id,
        "has_password": has_password,
        "configured": has_student_id and has_password,
    })


@app.route("/search_courses")
def search_courses():
    """搜索录播课程"""
    keyword = request.args.get("keyword", "")
    page = int(request.args.get("page", 1))
    page_size = int(request.args.get("page_size", 16))
    semesters_str = request.args.get("semesters", "")
    semesters = [int(s) for s in semesters_str.split(",") if s.strip()] if semesters_str else None
    try:
        if not utils.ensure_auth():
            return jsonify({"code": 403, "msg": "请先登录"})
        result = utils.search_courses(keyword=keyword, page=page, page_size=page_size, semesters=semesters)
        return jsonify({"code": 0, "data": result})
    except Exception as e:
        return jsonify({"code": 500, "msg": str(e)})


@app.route("/my_courses")
def my_courses():
    """获取个人录播课程"""
    page = int(request.args.get("page", 1))
    page_size = int(request.args.get("page_size", 16))
    try:
        if not utils.ensure_auth():
            return jsonify({"code": 403, "msg": "请先登录"})
        result = utils.get_my_courses(page=page, page_size=page_size)
        return jsonify({"code": 0, "data": result})
    except Exception as e:
        return jsonify({"code": 500, "msg": str(e)})


@app.route("/semesters")
def semesters():
    """获取学期标签列表"""
    try:
        result = utils.get_semesters()
        return jsonify({"code": 0, "data": result})
    except Exception as e:
        return jsonify({"code": 500, "msg": str(e)})


@app.route("/<path:path>")
def static_files(path):
    return send_from_directory(app.static_folder, path)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    t = threading.Thread(target=execute_tasks)
    t.start()
    webbrowser.open("http://127.0.0.1:5001/")
    app.run(debug=False, host="0.0.0.0", use_reloader=False, port=5001, threaded=True)
