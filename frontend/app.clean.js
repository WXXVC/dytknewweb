const API_BASE = "http://127.0.0.1:8000";

const state = {
  creators: [],
  profiles: [],
  tasks: [],
  currentScan: null,
  showDownloaded: false,
  selectedWorkIds: new Set(),
};

function setStaticText() {
  const sidebar = document.querySelector(".sidebar p");
  if (sidebar) sidebar.textContent = "自用控制面板";

  document.querySelector('[data-view="dashboard"]').textContent = "概览";
  document.querySelector('[data-view="creators"]').textContent = "账号管理";
  document.querySelector('[data-view="profiles"]').textContent = "下载配置";
  document.querySelector('[data-view="scan"]').textContent = "扫描结果";
  document.querySelector('[data-view="tasks"]').textContent = "任务中心";

  document.querySelector("#dashboard h2").textContent = "系统状态";
  document.querySelector("#creators h2").textContent = "账号管理";
  document.querySelector("#profiles h2").textContent = "下载配置";
  document.querySelector("#scan h2").textContent = "扫描结果";
  document.querySelector("#tasks h2").textContent = "任务中心";

  document.getElementById("refresh-creators").textContent = "刷新";
  document.getElementById("refresh-profiles").textContent = "刷新";
  document.getElementById("refresh-tasks").textContent = "刷新";
  document.getElementById("run-scan").textContent = "扫描未下载作品";
  document.getElementById("download-scanned").textContent = "下载当前扫描结果";
  document.getElementById("sync-engine").textContent = "同步到引擎 settings.json";
  document.getElementById("select-all-visible").textContent = "全选当前展示";
  document.getElementById("clear-selection").textContent = "清空选择";
  document.getElementById("download-selected").textContent = "下载已选作品";

  const showDownloadedLabel = document.getElementById("show-downloaded")?.parentElement;
  if (showDownloadedLabel) showDownloadedLabel.lastChild.textContent = "显示已下载作品";

  document.querySelector('#creator-form [name="name"]').placeholder = "显示名称";
  document.querySelector('#creator-form [name="mark"]').placeholder = "标记名";
  document.querySelector('#creator-form [name="url"]').placeholder = "主页链接";
  document.querySelector('#creator-form [name="sec_user_id"]').placeholder = "sec_user_id，可留空";
  document.querySelector('#creator-form [name="tab"]').placeholder = "tab，默认 post";
  document.querySelector('#profile-form [name="name"]').placeholder = "配置名称";
  document.querySelector('#profile-form [name="root_path"]').placeholder = "下载根目录";
  document.querySelector('#profile-form [name="folder_name"]').placeholder = "文件夹名";
  document.querySelector('#profile-form [name="name_format"]').placeholder = "命名格式";

  document.querySelector('#creator-form button[type="submit"]').textContent = "新增账号";
  document.querySelector('#profile-form button[type="submit"]').textContent = "新增配置";
  document.querySelector('#creator-form [name="platform"] option[value="douyin"]').textContent = "抖音";
  document.querySelector('#creator-form [name="enabled"]').parentElement.lastChild.textContent = "启用";
  document.querySelector('#profile-form [name="folder_mode"]').parentElement.lastChild.textContent = "按作品建文件夹";
  document.querySelector('#profile-form [name="music"]').parentElement.lastChild.textContent = "下载音乐";
  document.querySelector('#profile-form [name="dynamic_cover"]').parentElement.lastChild.textContent = "动态封面";
  document.querySelector('#profile-form [name="static_cover"]').parentElement.lastChild.textContent = "静态封面";
  document.querySelector('#profile-form [name="enabled"]').parentElement.lastChild.textContent = "启用";
}

document.querySelectorAll(".nav-link").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".nav-link").forEach((item) => item.classList.remove("active"));
    document.querySelectorAll(".view").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    document.getElementById(button.dataset.view).classList.add("active");
  });
});

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || "Request failed");
  }
  if (response.status === 204) {
    return null;
  }
  return response.json();
}

function boolValue(form, name) {
  return form.querySelector(`[name="${name}"]`).checked;
}

function visibleScanItems() {
  if (!state.currentScan) return [];
  return state.showDownloaded
    ? [...state.currentScan.items, ...(state.currentScan.hidden_items || [])]
    : state.currentScan.items;
}

function renderHealth(data) {
  document.getElementById("health-grid").innerHTML = `
    <div class="stat-card"><strong>${data.status}</strong><small>接口状态</small></div>
    <div class="stat-card"><strong>${data.app_db_ready ? "已就绪" : "缺失"}</strong><small>面板数据库</small></div>
    <div class="stat-card"><strong>${data.engine_db_found ? "已发现" : "缺失"}</strong><small>引擎下载历史库</small></div>
    <div class="stat-card"><strong>${data.engine_settings_found ? "已发现" : "缺失"}</strong><small>引擎 settings.json</small></div>
  `;
}

function renderProfiles() {
  document.getElementById("creator-profile-select").innerHTML = state.profiles
    .map((item) => `<option value="${item.id}">${item.name}</option>`)
    .join("");
  document.getElementById("scan-creator-select").innerHTML = state.creators
    .map((item) => `<option value="${item.id}">${item.name}</option>`)
    .join("");

  document.getElementById("profiles-table").innerHTML = state.profiles
    .map((item) => `
      <article class="list-card">
        <header>
          <strong>${item.name}</strong>
          <span class="pill">${item.enabled ? "启用" : "停用"}</span>
        </header>
        <small>目录：${item.root_path || "(跟随引擎默认目录)"}</small>
        <small>文件夹：${item.folder_name}</small>
        <small>命名：${item.name_format}</small>
      </article>
    `)
    .join("");
}

function renderCreators() {
  const table = document.getElementById("creators-table");
  table.innerHTML = state.creators
    .map((item) => `
      <article class="list-card">
        <header>
          <strong>${item.name}</strong>
          <span class="pill">${item.platform}</span>
        </header>
        <small>${item.url}</small>
        <small>标记：${item.mark || "(无)"}</small>
        <small>配置 ID：${item.profile_id ?? 1}</small>
        <div class="actions" style="margin-top:12px">
          <button data-download-creator="${item.id}">开始下载</button>
          <button data-delete-creator="${item.id}">删除</button>
        </div>
      </article>
    `)
    .join("");

  table.querySelectorAll("[data-download-creator]").forEach((button) => {
    button.addEventListener("click", async () => {
      await request("/tasks", {
        method: "POST",
        body: JSON.stringify({
          creator_id: Number(button.dataset.downloadCreator),
        }),
      });
      await loadTasks();
      alert("下载任务已启动，原项目会按预设菜单流执行。");
    });
  });

  table.querySelectorAll("[data-delete-creator]").forEach((button) => {
    button.addEventListener("click", async () => {
      await request(`/creators/${button.dataset.deleteCreator}`, { method: "DELETE" });
      await loadCreators();
    });
  });
}

function renderScan(data) {
  state.currentScan = data;
  const items = visibleScanItems();
  document.getElementById("scan-summary").innerHTML = `
    <strong>${data.creator_name}</strong> 扫描完成：
    来源 ${data.source}，共 ${data.all_count} 条，已下载 ${data.downloaded_count} 条，待下载 ${data.undownloaded_count} 条，
    当前展示 ${items.length} 条，已选 ${state.selectedWorkIds.size} 条。
  `;

  document.getElementById("scan-results").innerHTML = items
    .map((item) => `
      <article class="work-card ${state.selectedWorkIds.has(item.id) ? "selected" : ""}">
        ${item.cover ? `<img src="${item.cover}" alt="${item.title}" />` : ""}
        <header>
          <strong>${item.title}</strong>
          <span class="pill">${item.type}</span>
        </header>
        <label class="checkbox" style="margin:10px 0 0">
          <input type="checkbox" data-toggle-work="${item.id}" ${state.selectedWorkIds.has(item.id) ? "checked" : ""} ${item.is_downloaded ? "disabled" : ""} />
          选择这个作品
        </label>
        <small>ID：${item.id}</small>
        <small>发布时间：${item.published_at || "未知"}</small>
        <small>状态：${item.is_downloaded ? "已下载" : "未下载"}</small>
        ${item.share_url ? `<small><a href="${item.share_url}" target="_blank" rel="noreferrer">打开原链接</a></small>` : ""}
        <div class="actions" style="margin-top:12px">
          ${item.is_downloaded ? "" : `<button data-download-work="${item.id}">下载这个作品</button>`}
        </div>
      </article>
    `)
    .join("");

  document.querySelectorAll("[data-toggle-work]").forEach((element) => {
    element.addEventListener("change", (event) => {
      const workId = event.currentTarget.dataset.toggleWork;
      if (event.currentTarget.checked) {
        state.selectedWorkIds.add(workId);
      } else {
        state.selectedWorkIds.delete(workId);
      }
      renderScan(state.currentScan);
    });
  });

  document.querySelectorAll("[data-download-work]").forEach((button) => {
    button.addEventListener("click", async () => {
      if (!state.currentScan) return;
      await request("/tasks/works", {
        method: "POST",
        body: JSON.stringify({
          creator_id: state.currentScan.creator_id,
          work_ids: [button.dataset.downloadWork],
        }),
      });
      await loadTasks();
      alert("作品下载任务已启动。");
    });
  });
}

function renderTasks() {
  document.getElementById("tasks-table").innerHTML = state.tasks
    .map((item) => `
      <article class="list-card">
        <header>
          <strong>${item.creator_name}</strong>
          <span class="pill">${item.status}</span>
        </header>
        <small>平台：${item.platform}</small>
        <small>任务模式：${item.mode}</small>
        <small>作品数量：${item.item_count}</small>
        <small>PID：${item.pid ?? "(无)"}</small>
        <small>运行命令：${item.run_command}</small>
        <small>退出码：${item.exit_code ?? "(运行中)"}</small>
        <small>标准输出：${item.stdout_log || "(无)"}</small>
        <small>错误输出：${item.stderr_log || "(无)"}</small>
        <small>${item.message}</small>
        <div class="actions" style="margin-top:12px">
          ${item.status === "running" ? `<button data-stop-task="${item.id}">停止任务</button>` : ""}
        </div>
      </article>
    `)
    .join("");

  document.querySelectorAll("[data-stop-task]").forEach((button) => {
    button.addEventListener("click", async () => {
      await request(`/tasks/${button.dataset.stopTask}/stop`, { method: "POST" });
      await loadTasks();
    });
  });
}

async function loadHealth() {
  renderHealth(await request("/health"));
}

async function loadProfiles() {
  state.profiles = await request("/profiles");
  renderProfiles();
  setStaticText();
}

async function loadCreators() {
  state.creators = await request("/creators");
  renderCreators();
  renderProfiles();
  setStaticText();
}

async function loadTasks() {
  state.tasks = await request("/tasks");
  renderTasks();
}

document.getElementById("profile-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  await request("/profiles", {
    method: "POST",
    body: JSON.stringify({
      name: form.name.value,
      root_path: form.root_path.value,
      folder_name: form.folder_name.value,
      name_format: form.name_format.value,
      folder_mode: boolValue(form, "folder_mode"),
      music: boolValue(form, "music"),
      dynamic_cover: boolValue(form, "dynamic_cover"),
      static_cover: boolValue(form, "static_cover"),
      enabled: boolValue(form, "enabled"),
    }),
  });
  form.reset();
  form.folder_name.value = "Download";
  form.name_format.value = "create_time type nickname desc";
  form.enabled.checked = true;
  await loadProfiles();
});

document.getElementById("creator-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  await request("/creators", {
    method: "POST",
    body: JSON.stringify({
      platform: form.platform.value,
      name: form.name.value,
      mark: form.mark.value,
      url: form.url.value,
      sec_user_id: form.sec_user_id.value,
      tab: form.tab.value,
      profile_id: Number(form.profile_id.value || 1),
      enabled: boolValue(form, "enabled"),
    }),
  });
  form.reset();
  form.tab.value = "post";
  form.enabled.checked = true;
  await loadCreators();
});

document.getElementById("run-scan").addEventListener("click", async () => {
  const creatorId = document.getElementById("scan-creator-select").value;
  if (!creatorId) return;
  state.selectedWorkIds.clear();
  renderScan(await request(`/scans/creator/${creatorId}`, { method: "POST" }));
});

document.getElementById("show-downloaded").addEventListener("change", (event) => {
  state.showDownloaded = event.currentTarget.checked;
  if (state.currentScan) {
    renderScan(state.currentScan);
  }
});

document.getElementById("select-all-visible").addEventListener("click", () => {
  visibleScanItems().forEach((item) => {
    if (!item.is_downloaded) {
      state.selectedWorkIds.add(item.id);
    }
  });
  if (state.currentScan) {
    renderScan(state.currentScan);
  }
});

document.getElementById("clear-selection").addEventListener("click", () => {
  state.selectedWorkIds.clear();
  if (state.currentScan) {
    renderScan(state.currentScan);
  }
});

document.getElementById("download-selected").addEventListener("click", async () => {
  if (!state.currentScan || !state.selectedWorkIds.size) return;
  await request("/tasks/works", {
    method: "POST",
    body: JSON.stringify({
      creator_id: state.currentScan.creator_id,
      work_ids: [...state.selectedWorkIds],
    }),
  });
  state.selectedWorkIds.clear();
  await loadTasks();
  alert("已选作品下载任务已启动。");
});

document.getElementById("download-scanned").addEventListener("click", async () => {
  if (!state.currentScan || !state.currentScan.items.length) return;
  await request("/tasks/works", {
    method: "POST",
    body: JSON.stringify({
      creator_id: state.currentScan.creator_id,
      work_ids: state.currentScan.items.map((item) => item.id),
    }),
  });
  await loadTasks();
  alert("当前扫描结果的作品下载任务已启动。");
});

document.getElementById("sync-engine").addEventListener("click", async () => {
  await request("/engine/settings-sync", { method: "POST" });
  alert("已同步到引擎 settings.json");
  await loadHealth();
});

document.getElementById("refresh-creators").addEventListener("click", loadCreators);
document.getElementById("refresh-profiles").addEventListener("click", loadProfiles);
document.getElementById("refresh-tasks").addEventListener("click", loadTasks);

await loadHealth();
await loadProfiles();
await loadCreators();
await loadTasks();
setStaticText();

setInterval(() => {
  loadTasks().catch(() => {});
}, 5000);
