const state = {
  site: null,
  social: null,
  selectedDate: null,
  selectedTopic: "all",
  query: "",
  selectedId: null,
};

const els = {
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
  socialFeed: document.querySelector("#social-feed"),
  emptyState: document.querySelector("#empty-state"),
  detail: document.querySelector("#paper-detail"),
  template: document.querySelector("#paper-card-template"),
};

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

function renderSocial() {
  const social = state.social || { accounts: [], posts: [] };
  const accounts = social.accounts || [];
  const posts = social.posts || [];
  const okAccounts = accounts.filter((account) => account.status === "ok").length;

  els.socialStatus.textContent = posts.length
    ? `已汇总 ${posts.length} 条最新动态，覆盖 ${okAccounts}/${accounts.length} 个账号。`
    : `暂时没有抓到动态。仍可直接打开 ${accounts.length} 个账号主页查看。`;

  els.socialAccounts.innerHTML = "";
  accounts.forEach((account) => {
    const card = document.createElement("a");
    card.className = "account-chip";
    card.href = account.profile_url;
    card.innerHTML = `
      <span>${escapeHtml(account.name)}</span>
      <small>@${escapeHtml(account.handle)} · ${escapeHtml(account.focus || "AI")}</small>
    `;
    els.socialAccounts.append(card);
  });

  els.socialFeed.innerHTML = "";
  const feedItems = posts.length ? posts.slice(0, 12) : accounts.map((account) => ({
    account: account.name,
    handle: account.handle,
    title: "打开 X 主页查看最新动态",
    summary: account.status === "ok" ? "这个账号暂时没有返回新内容。" : account.status,
    url: account.search_url,
    published: social.generated_at,
  }));

  feedItems.forEach((post) => {
    const item = document.createElement("article");
    item.className = "social-post";
    item.innerHTML = `
      <div>
        <p class="social-author">${escapeHtml(post.account)} <span>@${escapeHtml(post.handle)}</span></p>
        <h3>${escapeHtml(post.title)}</h3>
        <p>${escapeHtml(post.summary || "")}</p>
      </div>
      <div class="social-post-foot">
        <span>${fmtDate(post.published)}</span>
        <a href="${escapeHtml(post.url)}">查看原文</a>
      </div>
    `;
    els.socialFeed.append(item);
  });
}

function render() {
  const papers = filteredPapers();
  renderMetrics(papers);
  renderList(papers);
  renderDetail(papers.find((paper) => paper.arxiv_id === state.selectedId));
}

async function init() {
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

  renderSocial();
  render();
}

init();
