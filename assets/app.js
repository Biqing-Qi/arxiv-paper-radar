const AUTH_HASH = "c295e0f7ac253cd568a92ea64490b139e70110f1d5864fc12782f1214a92675c";
const AUTH_STORAGE_KEY = "paper-radar-auth-v1";
const TAG_EDITS_STORAGE_KEY = "paper-radar-tag-edits-v1";
const COLUMN_ORDER_STORAGE_KEY = "paper-radar-column-order-v1";

const state = {
  site: null,
  social: null,
  paperDate: null,
  paperDirection: "all",
  peopleOrg: "all",
  peopleQuery: "",
  globalQuery: "",
  tagEdits: {},
  columnOrder: {},
};

const els = {
  authGate: document.querySelector("#auth-gate"),
  authForm: document.querySelector("#auth-form"),
  authPassword: document.querySelector("#auth-password"),
  authMessage: document.querySelector("#auth-message"),
  dateSelect: document.querySelector("#date-select"),
  searchInput: document.querySelector("#search-input"),
  metricCount: document.querySelector("#metric-count"),
  metricScore: document.querySelector("#metric-score"),
  metricUpdated: document.querySelector("#metric-updated"),
  paperDateFilter: document.querySelector("#paper-date-filter"),
  paperDirectionFilter: document.querySelector("#paper-direction-filter"),
  paperDirectionChips: document.querySelector("#paper-direction-chips"),
  paperHead: document.querySelector("#paper-database-head"),
  paperBody: document.querySelector("#paper-database-body"),
  peopleOrgFilter: document.querySelector("#people-org-filter"),
  peopleSearch: document.querySelector("#people-search"),
  peopleOrgChips: document.querySelector("#people-org-chips"),
  peopleHead: document.querySelector("#people-database-head"),
  peopleBody: document.querySelector("#people-database-body"),
};

async function sha256Hex(value) {
  const bytes = new TextEncoder().encode(value);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest)).map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function unlockApp() {
  document.body.classList.remove("auth-locked");
  document.body.classList.add("auth-unlocked");
  els.authGate.hidden = true;
}

function setAuthMessage(message) {
  els.authMessage.textContent = message;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function unique(values) {
  return Array.from(new Set(values.filter(Boolean)));
}

function fmtDate(value) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function slug(value) {
  return String(value || "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

function loadLocalState() {
  try {
    state.tagEdits = JSON.parse(localStorage.getItem(TAG_EDITS_STORAGE_KEY) || "{}");
  } catch {
    state.tagEdits = {};
  }
  try {
    state.columnOrder = JSON.parse(localStorage.getItem(COLUMN_ORDER_STORAGE_KEY) || "{}");
  } catch {
    state.columnOrder = {};
  }
}

function saveColumnOrder() {
  localStorage.setItem(COLUMN_ORDER_STORAGE_KEY, JSON.stringify(state.columnOrder));
}

function saveTagEdits() {
  localStorage.setItem(TAG_EDITS_STORAGE_KEY, JSON.stringify(state.tagEdits));
}

function dateBucket(paper) {
  return paper.digest_date || (paper.published || "").slice(0, 10);
}

function authorsText(paper) {
  const authors = paper.authors || [];
  if (authors.length <= 3) return authors.join(", ") || "Unknown authors";
  return `${authors.slice(0, 3).join(", ")}, et al.`;
}

function personKey(account) {
  return slug(`${account.name}-${account.org}-${account.handle || ""}`);
}

function editedTags(account) {
  return state.tagEdits[personKey(account)] || account.tags || [];
}

function canonicalOrg(org) {
  const raw = String(org || "").trim();
  const text = raw.toLowerCase();
  if (!raw) return "Unknown";
  if (text.includes("tsinghua")) return "Tsinghua University";
  if (text.includes("peking university") || text.includes("pku")) return "Peking University";
  if (text.includes("stanford")) return "Stanford";
  if (text.includes("mit")) return "MIT";
  if (text.includes("openai")) return "OpenAI";
  if (text.includes("anthropic")) return "Anthropic";
  if (text.includes("deepmind") || text.includes("google")) return "Google DeepMind / Google";
  if (text.includes("baai") || text.includes("智源")) return "BAAI";
  if (text.includes("shanghai ai")) return "Shanghai AI Lab";
  if (text.includes("deepseek")) return "DeepSeek";
  if (text.includes("moonshot")) return "Moonshot AI";
  if (text.includes("alibaba") || text.includes("qwen")) return "Alibaba / Qwen";
  if (text.includes("tencent")) return "Tencent";
  if (text.includes("baidu")) return "Baidu";
  if (text.includes("huawei")) return "Huawei";
  if (text.includes("bytedance")) return "ByteDance";
  if (text.includes("arxiv")) return raw;
  return raw.split("/")[0].trim();
}

function orgDistinction(org) {
  const raw = String(org || "").trim();
  const canonical = canonicalOrg(raw);
  return raw && raw !== canonical ? raw : "";
}

function initials(name) {
  const parts = String(name || "?").trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  if (/[\u4e00-\u9fa5]/.test(parts[0])) return parts[0].slice(0, 2);
  return parts.slice(0, 2).map((part) => part[0]).join("").toUpperCase();
}

function avatarHtml(account) {
  if (account.photo_url) {
    return `<img class="person-photo" src="${escapeHtml(account.photo_url)}" alt="${escapeHtml(account.name)}">`;
  }
  return `<span class="person-photo person-photo-fallback">${escapeHtml(initials(account.name))}</span>`;
}

function scholarUrl(name) {
  return `https://scholar.google.com/scholar?q=${encodeURIComponent(name)}`;
}

function linkCell(url, label) {
  return url ? `<a href="${escapeHtml(url)}">${escapeHtml(label)}</a>` : "";
}

function chipHtml(values) {
  return unique(values)
    .slice(0, 10)
    .map((item) => `<span class="db-chip">${escapeHtml(item)}</span>`)
    .join("");
}

function textOfPaper(paper) {
  return [
    paper.title,
    paper.summary,
    paper.abstract,
    ...(paper.authors || []),
    ...(paper.categories || []),
    ...(paper.boost_hits || []),
    ...paperResearchDirections(paper),
  ].join(" ").toLowerCase();
}

function paperResearchDirections(paper) {
  const text = `${paper.title || ""} ${paper.abstract || ""} ${paper.summary || ""} ${(paper.boost_hits || []).join(" ")} ${(paper.categories || []).join(" ")}`.toLowerCase();
  const topicLabels = (paper.topics || []).map((topic) => topic.label);
  const tags = [];
  if (topicLabels.includes("Model Architecture") || /architecture|mamba|linear attention|state space|moe|mixture of experts|sparse attention/.test(text)) tags.push("模型架构");
  if (topicLabels.includes("Diffusion Language Models") || /diffusion|denoising|score-based|masked diffusion/.test(text)) tags.push("扩散语言模型");
  if (/agent|multi-agent|tool use|workflow|planning/.test(text)) tags.push("智能体");
  if (/reinforcement learning|\brl\b|reward|policy optimization|rlhf/.test(text)) tags.push("强化学习");
  if (/reasoning|chain-of-thought|search|verif|planning/.test(text)) tags.push("推理与搜索");
  if (/multimodal|vision|image|video|audio|speech/.test(text)) tags.push("多模态");
  if (/efficient|compression|distillation|inference|serving|memory|long context/.test(text)) tags.push("高效模型与系统");
  if (/evaluation|benchmark|eval|leaderboard/.test(text)) tags.push("评测与基准");
  if (/biology|biomedical|medical|protein|science|chemistry/.test(text)) tags.push("AI for Science");
  if (/pretrain|training|data|synthetic|dataset/.test(text)) tags.push("训练与数据");
  return unique(tags.length ? tags : ["其他"]);
}

function papersForSelectedDate() {
  return (state.site?.papers || []).filter((paper) => dateBucket(paper) === state.paperDate);
}

function filteredPapers() {
  const query = state.globalQuery.trim().toLowerCase();
  return papersForSelectedDate()
    .filter((paper) => state.paperDirection === "all" || paperResearchDirections(paper).includes(state.paperDirection))
    .filter((paper) => !query || textOfPaper(paper).includes(query))
    .sort((a, b) => (b.score || 0) - (a.score || 0));
}

function filteredPeople() {
  const globalQuery = state.globalQuery.trim().toLowerCase();
  const peopleQuery = state.peopleQuery.trim().toLowerCase();
  return (state.social?.accounts || [])
    .filter((account) => state.peopleOrg === "all" || canonicalOrg(account.org) === state.peopleOrg)
    .filter((account) => {
      const text = [
        account.name,
        account.handle,
        account.org,
        canonicalOrg(account.org),
        account.region,
        account.focus,
        account.why_watch,
        ...editedTags(account),
      ].join(" ").toLowerCase();
      return (!globalQuery || text.includes(globalQuery)) && (!peopleQuery || text.includes(peopleQuery));
    });
}

function optionList(values, allLabel) {
  return [`<option value="all">${allLabel}</option>`]
    .concat(values.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`))
    .join("");
}

function renderMetrics() {
  const papers = papersForSelectedDate();
  const topScore = papers.reduce((max, paper) => Math.max(max, paper.score || 0), 0);
  els.metricCount.textContent = String(papers.length);
  els.metricScore.textContent = String(topScore);
  els.metricUpdated.textContent = fmtDate(state.site?.generated_at);
}

function renderPaperFilters() {
  const dates = state.site?.dates || [];
  els.dateSelect.innerHTML = dates.map((date) => `<option value="${date}">${date}</option>`).join("");
  els.paperDateFilter.innerHTML = dates.map((date) => `<option value="${date}">${date}</option>`).join("");
  els.dateSelect.value = state.paperDate;
  els.paperDateFilter.value = state.paperDate;

  const directions = unique(papersForSelectedDate().flatMap(paperResearchDirections)).sort((a, b) => a.localeCompare(b));
  if (state.paperDirection !== "all" && !directions.includes(state.paperDirection)) state.paperDirection = "all";
  els.paperDirectionFilter.innerHTML = optionList(directions, "全部研究方向");
  els.paperDirectionFilter.value = state.paperDirection;
  els.paperDirectionChips.innerHTML = directions
    .map((direction) => {
      const active = direction === state.paperDirection ? " is-active" : "";
      return `<button class="keyword-chip${active}" type="button" data-direction="${escapeHtml(direction)}">${escapeHtml(direction)}</button>`;
    })
    .join("");
  els.paperDirectionChips.querySelectorAll(".keyword-chip").forEach((button) => {
    button.addEventListener("click", () => {
      state.paperDirection = button.dataset.direction;
      renderPapers();
    });
  });
}

function renderPeopleFilters() {
  const orgs = unique((state.social?.accounts || []).map((account) => canonicalOrg(account.org))).sort((a, b) => a.localeCompare(b));
  if (state.peopleOrg !== "all" && !orgs.includes(state.peopleOrg)) state.peopleOrg = "all";
  els.peopleOrgFilter.innerHTML = optionList(orgs, "全部高校 / 机构");
  els.peopleOrgFilter.value = state.peopleOrg;
  els.peopleOrgChips.innerHTML = orgs
    .slice(0, 28)
    .map((org) => {
      const active = org === state.peopleOrg ? " is-active" : "";
      return `<button class="keyword-chip${active}" type="button" data-org="${escapeHtml(org)}">${escapeHtml(org)}</button>`;
    })
    .join("");
  els.peopleOrgChips.querySelectorAll(".keyword-chip").forEach((button) => {
    button.addEventListener("click", () => {
      state.peopleOrg = button.dataset.org;
      renderPeople();
    });
  });
}

function orderedColumns(key, columns) {
  const saved = state.columnOrder[key] || columns.map((column) => column.id);
  const byId = Object.fromEntries(columns.map((column) => [column.id, column]));
  return saved.filter((id) => byId[id]).map((id) => byId[id]).concat(columns.filter((column) => !saved.includes(column.id)));
}

function renderHeader(key, columns, headEl, renderFn) {
  const ordered = orderedColumns(key, columns);
  headEl.innerHTML = `<tr>${ordered.map((column) => `<th draggable="true" data-col="${column.id}">${escapeHtml(column.label)}</th>`).join("")}</tr>`;
  headEl.querySelectorAll("th").forEach((th) => {
    th.addEventListener("dragstart", (event) => {
      event.dataTransfer.setData("text/plain", th.dataset.col);
    });
    th.addEventListener("dragover", (event) => event.preventDefault());
    th.addEventListener("drop", (event) => {
      event.preventDefault();
      const from = event.dataTransfer.getData("text/plain");
      const to = th.dataset.col;
      const ids = orderedColumns(key, columns).map((column) => column.id);
      const fromIndex = ids.indexOf(from);
      const toIndex = ids.indexOf(to);
      if (fromIndex < 0 || toIndex < 0 || fromIndex === toIndex) return;
      ids.splice(toIndex, 0, ids.splice(fromIndex, 1)[0]);
      state.columnOrder[key] = ids;
      saveColumnOrder();
      renderFn();
    });
  });
  return ordered;
}

function paperColumns() {
  return [
    { id: "title", label: "Aa 标题", get: (paper) => paper.title },
    { id: "directions", label: "研究方向", html: true, get: (paper) => chipHtml(paperResearchDirections(paper)) },
    { id: "score", label: "分数", get: (paper) => paper.score || 0 },
    { id: "recommendation", label: "推荐", get: (paper) => paper.recommendation || "" },
    { id: "authors", label: "作者", get: authorsText },
    { id: "date", label: "时间", get: (paper) => dateBucket(paper) },
    { id: "categories", label: "来源分类", get: (paper) => (paper.categories || []).join(", ") },
    { id: "summary", label: "总结", get: (paper) => paper.summary || paper.abstract },
    { id: "url", label: "链接", html: true, get: (paper) => linkCell(paper.url, "arXiv") },
    { id: "pdf", label: "PDF", html: true, get: (paper) => linkCell(paper.pdf_url, "PDF") },
  ];
}

function personNameHtml(account) {
  const detail = orgDistinction(account.org);
  return `<div class="person-name-cell"><strong>${escapeHtml(account.name)}</strong>${detail ? `<span>${escapeHtml(detail)}</span>` : ""}</div>`;
}

function editableTagsHtml(account) {
  return `<div class="editable-tags" contenteditable="true" data-person-key="${escapeHtml(personKey(account))}" spellcheck="false">${escapeHtml(editedTags(account).join(", "))}</div>`;
}

function peopleColumns() {
  return [
    { id: "name", label: "Aa 姓名", html: true, get: personNameHtml },
    { id: "photo", label: "照片", html: true, get: avatarHtml },
    { id: "org", label: "高校 / 机构", get: (account) => canonicalOrg(account.org) },
    { id: "region", label: "地区", get: (account) => account.region },
    { id: "focus", label: "方向", get: (account) => account.focus },
    { id: "tags", label: "多 Tags", html: true, get: editableTagsHtml },
    { id: "scholar", label: "Google Scholar", html: true, get: (account) => linkCell(scholarUrl(account.name), "Scholar") },
    { id: "x", label: "X", html: true, get: (account) => linkCell(account.profile_url, account.handle ? `@${account.handle}` : "") },
    { id: "summary", label: "最新动态总结", get: (account) => account.why_watch || account.status || "" },
    { id: "home", label: "主页", html: true, get: (account) => linkCell(account.blog_url || account.search_url, "打开") },
  ];
}

function renderRows(rows, columns, bodyEl) {
  bodyEl.innerHTML = rows
    .map((row) => {
      const cells = columns.map((column) => {
        const value = column.get(row) || "";
        return `<td>${column.html ? value : escapeHtml(value)}</td>`;
      });
      return `<tr>${cells.join("")}</tr>`;
    })
    .join("");
}

function bindEditableTags() {
  els.peopleBody.querySelectorAll(".editable-tags").forEach((node) => {
    node.addEventListener("blur", () => {
      const key = node.dataset.personKey;
      state.tagEdits[key] = unique(node.textContent.split(/[,，]/).map((item) => item.trim()));
      saveTagEdits();
    });
    node.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        node.blur();
      }
    });
  });
}

function renderPapers() {
  renderPaperFilters();
  renderMetrics();
  const columns = renderHeader("papers", paperColumns(), els.paperHead, renderPapers);
  renderRows(filteredPapers(), columns, els.paperBody);
}

function renderPeople() {
  renderPeopleFilters();
  const columns = renderHeader("people", peopleColumns(), els.peopleHead, renderPeople);
  renderRows(filteredPeople(), columns, els.peopleBody);
  bindEditableTags();
}

function renderAll() {
  renderPapers();
  renderPeople();
}

async function loadApp() {
  loadLocalState();
  try {
    const response = await fetch("data/site.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.site = await response.json();
  } catch (error) {
    state.site = { generated_at: null, dates: [], papers: [] };
    console.error(error);
  }
  try {
    const response = await fetch("data/social.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.social = await response.json();
  } catch (error) {
    state.social = { generated_at: null, accounts: [], posts: [] };
    console.error(error);
  }

  const dates = state.site.dates || [];
  state.paperDate = dates.includes(state.site.latest_date) ? state.site.latest_date : dates[0] || null;

  els.dateSelect.addEventListener("change", (event) => {
    state.paperDate = event.target.value;
    renderPapers();
  });
  els.paperDateFilter.addEventListener("change", (event) => {
    state.paperDate = event.target.value;
    renderPapers();
  });
  els.paperDirectionFilter.addEventListener("change", (event) => {
    state.paperDirection = event.target.value;
    renderPapers();
  });
  els.searchInput.addEventListener("input", (event) => {
    state.globalQuery = event.target.value;
    renderAll();
  });
  els.peopleOrgFilter.addEventListener("change", (event) => {
    state.peopleOrg = event.target.value;
    renderPeople();
  });
  els.peopleSearch.addEventListener("input", (event) => {
    state.peopleQuery = event.target.value;
    renderPeople();
  });

  renderAll();
}

function initAuth() {
  if (localStorage.getItem(AUTH_STORAGE_KEY) === AUTH_HASH) {
    unlockApp();
    loadApp();
    return;
  }
  els.authForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const password = els.authPassword.value;
    if (!password) {
      setAuthMessage("请输入访问密码。");
      return;
    }
    try {
      const hash = await sha256Hex(password);
      if (hash !== AUTH_HASH) {
        els.authPassword.value = "";
        els.authPassword.focus();
        setAuthMessage("密码不正确。");
        return;
      }
      localStorage.setItem(AUTH_STORAGE_KEY, AUTH_HASH);
      unlockApp();
      await loadApp();
    } catch (error) {
      console.error(error);
      setAuthMessage("当前浏览器不支持本地密码校验。");
    }
  });
}

initAuth();
