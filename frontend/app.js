const API_BASE = "http://127.0.0.1:8000";

const state = {
  creators: [],
  profiles: [],
  tasks: [],
  currentScan: null,
  showDownloaded: false,
};

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
  const visibleItems = state.showDownloaded
    ? [...data.items, ...(data.hidden_items || [])]
    : data.items;
  document.getElementById("scan-summary").innerHTML = `
    <strong>${data.creator_name}</strong> 扫描完成：
    来源 ${data.source}，共 ${data.all_count} 条，已下载 ${data.downloaded_count} 条，待下载 ${data.undownloaded_count} 条，
    当前展示 ${visibleItems.length} 条。
  `;
  document.getElementById("scan-results").innerHTML = visibleItems
    .map((item) => `
      <article class="work-card">
        ${item.cover ? `<img src="${item.cover}" alt="${item.title}" />` : ""}
        <header>
          <strong>${item.title}</strong>
          <span class="pill">${item.type}</span>
        </header>
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
}

async function loadCreators() {
  state.creators = await request("/creators");
  renderCreators();
  renderProfiles();
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
  renderScan(await request(`/scans/creator/${creatorId}`, { method: "POST" }));
});

document.getElementById("show-downloaded").addEventListener("change", (event) => {
  state.showDownloaded = event.currentTarget.checked;
  if (state.currentScan) {
    renderScan(state.currentScan);
  }
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

setInterval(() => {
  loadTasks().catch(() => {});
}, 5000);
