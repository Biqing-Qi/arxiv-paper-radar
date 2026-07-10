const AUTH_HASH = "c295e0f7ac253cd568a92ea64490b139e70110f1d5864fc12782f1214a92675c";
const AUTH_STORAGE_KEY = "paper-radar-auth-v1";

const state = {
  site: null,
  social: null,
  selectedDate: null,
  selectedTopic: "all",
  selectedOrg: "all",
  selectedRegion: "all",
  selectedPeopleTag: "all",
  peopleQuery: "",
  query: "",
  selectedId: null,
};

const els = {
  authGate: document.querySelector("#auth-gate"),
  authForm: document.querySelector("#auth-form"),
  authPassword: document.querySelector("#auth-password"),
  authMessage: document.querySelector("#auth-message"),
  dateSelect: document.querySelector("#date-select"),
  searchInput: document.querySelector("#search-input"),
  topicButtons: Array.from(document.querySelectorAll(".topic-button")),
  paperList: document.querySelector("#paper-list"),
  visibleCount: document.querySelector("#visible-count"),
  metricCount: document.querySelector("#metric-count"),
  metricScore: document.querySelector("#metric-score"),
  metricUpdated: document.querySelector("#metric-updated"),
  socialStatus: document.querySelector("#social-status"),
  socialAccounts: document.querySelector("#social-accounts"),
  orgFilter: document.querySelector("#org-filter"),
  regionFilter: document.querySelector("#region-filter"),
  tagFilter: document.querySelector("#tag-filter"),
  peopleSearch: document.querySelector("#people-search"),
  emptyState: document.querySelector("#empty-state"),
  detail: document.querySelector("#paper-detail"),
  template: document.querySelector("#paper-card-template"),
};

async function sha256Hex(value) {
  const bytes = new TextEncoder().encode(value);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
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

function unique(values) {
  return Array.from(new Set(values.filter(Boolean)));
}

function authorsText(paper) {
  const authors = paper.authors || [];
  if (authors.length <= 3) return authors.join(", ") || "Unknown authors";
  return `${authors.slice(0, 3).join(", ")}, et al.`;
}

function dateBucket(paper) {
  return paper.digest_date || (paper.published || "").slice(0, 10);
}

function papersForDate() {
  const papers = state.site?.papers || [];
  return papers.filter((paper) => dateBucket(paper) === state.selectedDate);
}

function filteredPapers() {
  const query = state.query.trim().toLowerCase();
  return papersForDate()
    .filter((paper) => {
      if (state.selectedTopic === "all") return true;
      return (paper.topics || []).some((topic) => topic.label === state.selectedTopic);
    })
    .filter((paper) => {
      if (!query) return true;
      const haystack = [
        paper.title,
        paper.summary,
        paper.abstract,
        ...(paper.authors || []),
        ...(paper.categories || []),
        ...(paper.boost_hits || []),
        ...(paper.topics || []).flatMap((topic) => [topic.label, ...(topic.keywords || [])]),
      ].join(" ").toLowerCase();
      return haystack.includes(query);
    })
    .sort((a, b) => (b.score || 0) - (a.score || 0));
}

function renderDateOptions() {
  const dates = state.site?.dates || [];
  els.dateSelect.innerHTML = dates
    .map((date) => `<option value="${date}">${date}</option>`)
    .join("");
  els.dateSelect.value = state.selectedDate;
}

function renderMetrics(papers) {
  const allForDay = papersForDate();
  const topScore = allForDay.reduce((max, paper) => Math.max(max, paper.score || 0), 0);
  els.metricCount.textContent = String(allForDay.length);
  els.metricScore.textContent = String(topScore);
  els.metricUpdated.textContent = fmtDate(state.site?.generated_at);
  els.visibleCount.textContent = String(papers.length);
}

function tag(label, className = "tag") {
  const span = document.createElement("span");
  span.className = className;
  span.textContent = label;
  return span;
}

function renderList(papers) {
  els.paperList.innerHTML = "";
  if (!papers.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.innerHTML = "<p class=\"eyebrow\">No results</p><h2>没有符合当前筛选的论文</h2>";
    els.paperList.append(empty);
    renderDetail(null);
    return;
  }

  if (!papers.some((paper) => paper.arxiv_id === state.selectedId)) {
    state.selectedId = papers[0].arxiv_id;
  }

  for (const paper of papers) {
    const node = els.template.content.firstElementChild.cloneNode(true);
    node.dataset.id = paper.arxiv_id;
    node.classList.toggle("is-active", paper.arxiv_id === state.selectedId);
    node.querySelector(".score-badge").textContent = `${paper.recommendation || "Paper"} · ${paper.score || 0}`;
    node.querySelector(".paper-title").textContent = paper.title;
    node.querySelector(".paper-meta").textContent = `${authorsText(paper)} · ${fmtDate(paper.published)}`;
    const row = node.querySelector(".tag-row");
    unique((paper.topics || []).map((topic) => topic.label)).forEach((label) => row.append(tag(label)));
    node.addEventListener("click", () => {
      state.selectedId = paper.arxiv_id;
      render();
    });
    els.paperList.append(node);
  }
}

function renderDetail(paper) {
  if (!paper) {
    els.detail.hidden = true;
    els.emptyState.hidden = false;
    return;
  }

  els.emptyState.hidden = true;
  els.detail.hidden = false;

  const keywords = unique((paper.topics || []).flatMap((topic) => topic.keywords || []));
  const topics = unique((paper.topics || []).map((topic) => topic.label));
  const pdfLink = paper.pdf_url ? `<a href="${escapeHtml(paper.pdf_url)}">PDF</a>` : "";

  els.detail.innerHTML = `
    <div class="detail-top">
      <p class="eyebrow">${escapeHtml(paper.recommendation || "Recommendation")}</p>
      <h2 class="detail-title">${escapeHtml(paper.title)}</h2>
      <p class="detail-summary">${escapeHtml(paper.summary || "")}</p>
      <div class="detail-tags">
        ${topics.map((item) => `<span class="tag">${escapeHtml(item)}</span>`).join("")}
        ${keywords.slice(0, 10).map((item) => `<span class="keyword">${escapeHtml(item)}</span>`).join("")}
      </div>
    </div>

    <div class="detail-meta-grid">
      <div class="detail-meta"><span>Score</span><strong>${paper.score || 0}</strong></div>
      <div class="detail-meta"><span>Published</span><strong>${fmtDate(paper.published)}</strong></div>
      <div class="detail-meta"><span>Authors</span><strong>${escapeHtml(authorsText(paper))}</strong></div>
      <div class="detail-meta"><span>Categories</span><strong>${escapeHtml((paper.categories || []).join(", ") || "--")}</strong></div>
    </div>

    <div class="detail-links">
      <a href="${escapeHtml(paper.url)}">arXiv</a>
      ${pdfLink}
    </div>

    <div class="abstract-box">${escapeHtml(paper.abstract || "No abstract available.")}</div>
  `;
}

function optionList(values, allLabel) {
  return [`<option value="all">${allLabel}</option>`]
    .concat(values.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`))
    .join("");
}

function renderPeopleFilters(accounts) {
  const orgs = unique(accounts.map((account) => account.org)).sort();
  const regions = unique(accounts.map((account) => account.region)).sort();
  const tags = unique(accounts.flatMap((account) => account.tags || [])).sort();
  els.orgFilter.innerHTML = optionList(orgs, "全部机构");
  els.regionFilter.innerHTML = optionList(regions, "全部地区");
  els.tagFilter.innerHTML = optionList(tags, "全部标签");
  els.orgFilter.value = state.selectedOrg;
  els.regionFilter.value = state.selectedRegion;
  els.tagFilter.value = state.selectedPeopleTag;
}

function filteredAccounts(accounts) {
  const query = state.peopleQuery.trim().toLowerCase();
  return accounts.filter((account) => {
    if (state.selectedOrg !== "all" && account.org !== state.selectedOrg) return false;
    if (state.selectedRegion !== "all" && account.region !== state.selectedRegion) return false;
    if (state.selectedPeopleTag !== "all" && !(account.tags || []).includes(state.selectedPeopleTag)) return false;
    if (!query) return true;
    const text = [
      account.name,
      account.handle,
      account.org,
      account.region,
      account.focus,
      account.why_watch,
      ...(account.tags || []),
    ].join(" ").toLowerCase();
    return text.includes(query);
  });
}

function renderSocial() {
  const social = state.social || { accounts: [], posts: [] };
  const accounts = social.accounts || [];
  const visibleAccounts = filteredAccounts(accounts);
  const posts = social.posts || [];

  els.socialStatus.textContent = posts.length
    ? `已汇总 ${posts.length} 条最新动态，当前显示 ${visibleAccounts.length}/${accounts.length} 位 AI 研究者/机构观察卡。`
    : `当前显示 ${visibleAccounts.length}/${accounts.length} 位 AI 研究者/机构观察卡。`;

  els.socialAccounts.innerHTML = "";
  visibleAccounts.forEach((account) => {
    const card = document.createElement("article");
    card.className = "person-card";
    const handleLine = account.handle ? `@${escapeHtml(account.handle)} · ` : "";
    const tags = (account.tags || []).slice(0, 5).map((item) => `<span>${escapeHtml(item)}</span>`).join("");
    card.innerHTML = `
      <div class="person-card-head">
        <div>
          <h3>${escapeHtml(account.name)}</h3>
          <p>${handleLine}${escapeHtml(account.org || "Unknown")} · ${escapeHtml(account.focus || "AI")}</p>
        </div>
        <span>${account.post_count || 0}</span>
      </div>
      <p class="person-note">${escapeHtml(account.why_watch || "适合持续观察 AI 研究、产品和产业信号。")}</p>
      <div class="person-tags">${tags}</div>
      <div class="person-links">
        ${account.profile_url ? `<a href="${escapeHtml(account.profile_url)}">X 主页</a>` : ""}
        ${account.search_url ? `<a href="${escapeHtml(account.search_url)}">最新搜索</a>` : ""}
        ${account.blog_url ? `<a href="${escapeHtml(account.blog_url)}">博客/主页</a>` : ""}
      </div>
    `;
    els.socialAccounts.append(card);
  });
}

function render() {
  const papers = filteredPapers();
  renderMetrics(papers);
  renderList(papers);
  renderDetail(papers.find((paper) => paper.arxiv_id === state.selectedId));
}

async function loadApp() {
  try {
    const response = await fetch("data/site.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.site = await response.json();
  } catch (error) {
    state.site = {
      generated_at: null,
      dates: [],
      papers: [],
    };
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
  state.selectedDate = dates.includes(state.site.latest_date) ? state.site.latest_date : dates[0] || null;
  renderDateOptions();

  els.dateSelect.addEventListener("change", (event) => {
    state.selectedDate = event.target.value;
    state.selectedId = null;
    render();
  });

  els.searchInput.addEventListener("input", (event) => {
    state.query = event.target.value;
    state.selectedId = null;
    render();
  });

  els.topicButtons.forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedTopic = button.dataset.topic;
      state.selectedId = null;
      els.topicButtons.forEach((item) => item.classList.toggle("is-active", item === button));
      render();
    });
  });

  renderPeopleFilters(state.social.accounts || []);
  els.orgFilter.addEventListener("change", (event) => {
    state.selectedOrg = event.target.value;
    renderSocial();
  });
  els.regionFilter.addEventListener("change", (event) => {
    state.selectedRegion = event.target.value;
    renderSocial();
  });
  els.tagFilter.addEventListener("change", (event) => {
    state.selectedPeopleTag = event.target.value;
    renderSocial();
  });
  els.peopleSearch.addEventListener("input", (event) => {
    state.peopleQuery = event.target.value;
    renderSocial();
  });

  renderSocial();
  render();
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
