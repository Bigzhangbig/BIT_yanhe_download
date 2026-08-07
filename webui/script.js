document.getElementById("newTaskButton").onclick = function () {
  document.getElementById("taskPopup").style.display = "block";
  loadSemesters();
};

document.getElementsByClassName("close")[0].onclick = function () {
  document.getElementById("taskPopup").style.display = "none";
};

// ====== 课程搜索功能 ======
let currentSearchPage = 1;
let searchDebounceTimer = null;

function switchTab(tab) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
  document.querySelector(`.tab[data-tab="${tab}"]`).classList.add("active");
  document.getElementById("searchPanel").style.display = tab === "search" ? "block" : "none";
  document.getElementById("myPanel").style.display = tab === "my" ? "block" : "none";
  document.getElementById("searchResults").innerHTML = "";
  document.getElementById("pagination").innerHTML = "";
}

function loadSemesters() {
  fetch("/semesters")
    .then((r) => r.json())
    .then((data) => {
      if (data.code !== 0) return;
      const select = document.getElementById("semesterFilter");
      select.innerHTML = '<option value="">\u5168\u90e8\u5b66\u671f</option>';
      data.data.forEach((s) => {
        select.innerHTML += `<option value="${s.id}">${s.name}</option>`;
      });
    });
}

function doSearch(page) {
  const keyword = document.getElementById("searchKeyword").value.trim();
  const semester = document.getElementById("semesterFilter").value;
  const p = page || 1;
  currentSearchPage = p;

  let url = `/search_courses?keyword=${encodeURIComponent(keyword)}&page=${p}&page_size=16`;
  if (semester) url += `&semesters=${semester}`;

  document.getElementById("searchResults").innerHTML = '<p class="search-hint">\u641c\u7d22\u4e2d...</p>';
  fetch(url)
    .then((r) => r.json())
    .then((data) => {
      if (data.code !== 0) {
        document.getElementById("searchResults").innerHTML = `<p class="search-hint">${data.msg || "\u641c\u7d22\u5931\u8d25"}</p>`;
        return;
      }
      renderCourseResults(data.data);
    })
    .catch((err) => {
      document.getElementById("searchResults").innerHTML = `<p class="search-hint">\u8bf7\u6c42\u5931\u8d25: ${err}</p>`;
    });
}

function loadMyCourses(page) {
  const p = page || 1;
  currentSearchPage = p;
  document.getElementById("searchResults").innerHTML = '<p class="search-hint">\u52a0\u8f7d\u4e2d...</p>';
  fetch(`/my_courses?page=${p}&page_size=16`)
    .then((r) => r.json())
    .then((data) => {
      if (data.code !== 0) {
        document.getElementById("searchResults").innerHTML = `<p class="search-hint">${data.msg || "\u52a0\u8f7d\u5931\u8d25"}</p>`;
        return;
      }
      renderCourseResults(data.data);
    })
    .catch((err) => {
      document.getElementById("searchResults").innerHTML = `<p class="search-hint">\u8bf7\u6c42\u5931\u8d25: ${err}</p>`;
    });
}

function renderCourseResults(resultData) {
  const courses = resultData.data || [];
  const container = document.getElementById("searchResults");
  const pagination = document.getElementById("pagination");

  if (!courses.length) {
    container.innerHTML = '<p class="search-hint">\u672a\u627e\u5230\u76f8\u5173\u8bfe\u7a0b</p>';
    pagination.innerHTML = "";
    return;
  }

  let html = "";
  courses.forEach((c) => {
    const profs = (c.professors || []).map((p) => (typeof p === "string" ? p : p.name || "")).join(", ");
    const college = c.college_name || "";
    const year = c.school_year || "";
    const semester = c.semester === "1" ? "\u7b2c\u4e00\u5b66\u671f" : c.semester === "2" ? "\u7b2c\u4e8c\u5b66\u671f" : c.semester || "";
    html += `
      <div class="course-item" onclick="selectCourse(${c.id})">
        <div class="course-name">${c.name_zh || c.name || "\u672a\u77e5"}</div>
        <div class="course-meta">${profs}${college ? " | " + college : ""}${year ? " | " + year + " " + semester : ""}</div>
      </div>`;
  });
  container.innerHTML = html;

  // 分页
  const currentPage = resultData.current_page || 1;
  const lastPage = resultData.last_page || 1;
  let pageHtml = "";
  if (lastPage > 1) {
    if (currentPage > 1) {
      pageHtml += `<button class="page-btn" onclick="navigatePage(${currentPage - 1})">\u4e0a\u4e00\u9875</button>`;
    }
    pageHtml += `<span class="page-info">\u7b2c ${currentPage} / ${lastPage} \u9875\uff0c\u5171 ${resultData.total || 0} \u95e8\u8bfe</span>`;
    if (currentPage < lastPage) {
      pageHtml += `<button class="page-btn" onclick="navigatePage(${currentPage + 1})">\u4e0b\u4e00\u9875</button>`;
    }
  } else {
    pageHtml = `<span class="page-info">\u5171 ${resultData.total || courses.length} \u95e8\u8bfe</span>`;
  }
  pagination.innerHTML = pageHtml;
}

function navigatePage(page) {
  const activeTab = document.querySelector(".tab.active").getAttribute("data-tab");
  if (activeTab === "my") {
    loadMyCourses(page);
  } else {
    doSearch(page);
  }
}

function selectCourse(courseId) {
  document.getElementById("courseId").value = courseId;
  document.getElementById("searchResults").innerHTML = `<p class="search-hint">\u5df2\u9009\u62e9\u8bfe\u7a0b ID: ${courseId}</p>`;
  document.getElementById("pagination").innerHTML = "";
  // 自动触发获取课程信息
  fetchCourseNumber();
}

// 回车键搜索
document.addEventListener("DOMContentLoaded", () => {
  const searchInput = document.getElementById("searchKeyword");
  if (searchInput) {
    searchInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        doSearch();
      }
    });
  }
});

// Implement the logic to fetch course number and handle form submission
function fetchCourseNumber() {
  document.getElementById("courseList").innerHTML = '<li>\u52a0\u8f7d\u4e2d...</li>';
  fetch(`/get_course?course_id=${document.getElementById("courseId").value}&auth=${document.getElementById("auth").value}`)
    .then((response) => response.json())
    .then((data) => {
      console.log(data);
      if (data.code && data.code == 403) {
        document.getElementById("auth_prompt").innerHTML = data.msg;
        alert(data.msg);
      }
      document.getElementById("courseList").innerHTML = ``;
      document.getElementById("courseName11").innerHTML = `\u8bfe\u7a0b\u540d: <b>${data.courseName == "" ? "\u672a\u77e5" : data.courseName
        }</b>`;
      document.getElementById("professor11").innerHTML = `\u8001\u5e08: <b>${data.professor == "" ? "\u672a\u77e5" : data.professor
        }</b>`;
      let courseListHTML = "";
      for (let i = 0; i < data.videoList.length; i++) {
        courseListHTML += `<li data-value="${i}">${data.videoList[i].title}</li>`;
      }
      document.getElementById("courseList").innerHTML = courseListHTML;
      document.querySelectorAll("#courseList li").forEach((item) => {
        item.addEventListener("click", () => {
          item.classList.toggle("selected");
        });
      });
    })
    .catch((error) => console.error("Error:", error));
}

document.getElementById("taskForm").onsubmit = function (event) {
  event.preventDefault();
  let courseId = document.getElementById("courseId").value;
  if (courseId.trim() == "") {
    alert("课程名不能为空");
    return;
  }
  let downloadType = document.getElementById("downloadType").value;
  let downloadAudio = document.getElementById("downloadAudio").value;
  let selected_index = [];
  let courseList = document.getElementById("courseList");
  for (let i = 0; i < courseList.childNodes.length; i++) {
    let child = courseList.childNodes[i];
    if (child.className == "selected") {
      selected_index.push(child.getAttribute("data-value"));
    }
  }
  let course_number = selected_index.join(",");
  fetch("/new_task", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      course_id: courseId.trim(),
      course_number: course_number,
      download_version: downloadType,
      download_audio: downloadAudio
    }),
  })
    .then((response) => response.json())
    .then((data) => {
      console.log(data);
      document.getElementById("taskPopup").style.display = "none";
    })
    .catch((error) => console.error("Error:", error));
};

function getDownloadStatusText(task_obj) {
  const merge_status = task_obj["merge_status"];
  const cur = task_obj["cur"];
  const tot = task_obj["tot"];
  const cancel = task_obj["canceled"];
  if (cancel) {
    return "已取消";
  }
  if (merge_status == 0) {
    if (cur == 0) {
      return "等待中...";
    } else {
      return `下载中...(${((cur / tot) * 100).toFixed(2)} %)`;
    }
  } else if (merge_status == 1) {
    return "合并视频中...";
  } else if (merge_status == 2) {
    return "已完成";
  } else {
    return "未知状态";
  }
}

function cancelTask(btn) {
  let uuid = btn.getAttribute("data-task-uuid");
  console.log(uuid);
  fetch(`/kill_task?uuid=${uuid}`)
    .then((response) => response.json())
    .then((data) => {
      console.log(data);
      let remove_node = document.getElementById(`${uuid}-task`);
      if (remove_node != null) {
        remove_node.parentNode.removeChild(remove_node);
      }
    })
    .catch((error) => console.error("Error:", error));
}

setInterval(() => {
  const addElement = (task_obj) => {
    if (task_obj["canceled"]) {
      return;
    }
    const download_version =
      task_obj["download_type"] == 2 ? "电脑屏幕" : "摄像头";
    const html = `
      <div class="task" id="${task_obj["uuid"]}-task">
        <div class="task-info">
          <span>${task_obj["name"]}(${download_version})</span>
          <div class="status-container">
            <span class="status" id="${task_obj["uuid"]
      }-status">${getDownloadStatusText(task_obj)}</span>
            <button class="cancel-btn" data-task-uuid="${task_obj["uuid"]
      }" onclick="cancelTask(this);">×</button>
          </div>
        </div>
        <div class="progress-bar">
          <div class="progress" id="${task_obj["uuid"]}-progress"></div>
        </div>
      </div>
    `;
    let taskList = document.getElementById("taskList");
    taskList.innerHTML = html + taskList.innerHTML;
  };
  const updateElement = (task_obj) => {
    const uuid = task_obj["uuid"];
    const status_ele = document.getElementById(`${task_obj["uuid"]}-status`);
    const progress_ele = document.getElementById(
      `${task_obj["uuid"]}-progress`
    );
    status_ele.innerText = getDownloadStatusText(task_obj);
    const progress = (100 * task_obj["cur"]) / task_obj["tot"];
    progress_ele.style.width = `${progress.toFixed(2)}%`;
  };
  const removeCanceledElement = (uuid_arr) => {
    let all_task_elem = document.getElementsByClassName("task");
    for (let i = 0; i < all_task_elem.length; i++) {
      const uuid = all_task_elem[i].getAttribute("id").replace("-task", "");
      if (!uuid_arr.includes(uuid)) {
        all_task_elem[i].parentNode.removeChild(all_task_elem[i]);
      }
    }
  }
  fetch("/get_status")
    .then((response) => response.json())
    .then((data) => {
      // console.log(data);
      let uuid_arr = [];
      for (let i = 0; i < data.length; i++) {
        const uuid = data[i]["uuid"];
        if (!data[i]["canceled"]) {
          uuid_arr.push(uuid);
        }
        let exist_ele = document.getElementById(`${uuid}-task`);
        if (exist_ele == null) {
          addElement(data[i]);
        } else {
          updateElement(data[i]);
        }
      }
      removeCanceledElement(uuid_arr);
    })
    .catch((error) => console.error("Error:", error));
}, 1000);

const listItems = document.querySelectorAll("#courseList li");
listItems.forEach((item) => {
  item.addEventListener("click", () => {
    item.classList.toggle("selected");
  });
});

function selectAll(select) {
  let list = document.getElementById("courseList");
  for (let i = 0; i < list.childNodes.length; i++) {
    list.childNodes[i].className = select ? "selected" : "";
  }
}

async function ssoLogin() {
  const btn = event.target;
  btn.disabled = true;
  btn.textContent = "登录中(可能弹浏览器)...";
  let timer = setTimeout(() => {
    btn.textContent = "请在弹出的浏览器中完成登录...";
  }, 10000);
  try {
    const res = await fetch("/sso_login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ course_id: document.getElementById("courseId").value }),
    }).then((r) => r.json());
    clearTimeout(timer);
    if (res.code === 0) {
      alert("SSO 登录成功 (auth.txt 已更新)");
      document.getElementById("auth").value = "";
      document.getElementById("auth").placeholder = "已通过 SSO 登录";
    } else {
      alert("SSO 登录结果: " + res.msg);
    }
  } catch (e) {
    clearTimeout(timer);
    alert("SSO 登录请求失败(可能超时): " + e);
  } finally {
    btn.disabled = false;
    btn.textContent = "SSO 登录";
  }
}
