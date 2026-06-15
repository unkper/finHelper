(function () {
  const cfg = window.STOCK_NEWS_PAGE || {};
  const LIMIT = 20;
  let currentOffset = 0;
  let hasMore = false;
  let loading = false;

  function $(id) {
    return document.getElementById(id);
  }

  function setStatus(text, isError) {
    const el = $("newsStatus");
    if (!el) return;
    if (!text) {
      el.hidden = true;
      el.textContent = "";
      el.classList.remove("is-error");
      return;
    }
    el.hidden = false;
    el.textContent = text;
    el.classList.toggle("is-error", !!isError);
  }

  function formatDate(value) {
    if (!value) return "";
    return String(value).replace("T", " ").slice(0, 16);
  }

  function sentimentClass(label) {
    if (label === "偏正面") return "news-sentiment--pos";
    if (label === "偏负面") return "news-sentiment--neg";
    return "news-sentiment--neu";
  }

  function escapeHtml(text) {
    return String(text || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function renderNewsCard(item) {
    const title = escapeHtml(item.title);
    const link = item.link ? escapeHtml(item.link) : "";
    const titleHtml = link
      ? `<a href="${link}" target="_blank" rel="noopener noreferrer">${title}</a>`
      : title;
    const tags = (item.tags || [])
      .slice(0, 5)
      .map((tag) => `<span class="news-tag">${escapeHtml(tag)}</span>`)
      .join("");
    return `
      <article class="news-card">
        <div class="news-card-head">
          <h3 class="news-card-title">${titleHtml}</h3>
          <span class="news-sentiment ${sentimentClass(item.sentiment_label)}">${escapeHtml(item.sentiment_label || "中性")}</span>
        </div>
        <p class="news-card-meta">${formatDate(item.date)}</p>
        <p class="news-card-summary">${escapeHtml(item.summary || "")}</p>
        ${tags ? `<div class="news-card-tags">${tags}</div>` : ""}
      </article>
    `;
  }

  function setLoading(active) {
    loading = active;
    const el = $("newsLoading");
    if (el) el.hidden = !active;
    const refreshBtn = $("refreshNewsBtn");
    const loadMoreBtn = $("loadMoreNewsBtn");
    if (refreshBtn) refreshBtn.disabled = active || !cfg.selectedTicker;
    if (loadMoreBtn) loadMoreBtn.disabled = active;
  }

  function buildFeedUrl(offset, refresh) {
    const params = new URLSearchParams({
      ticker: cfg.selectedTicker,
      offset: String(offset),
      limit: String(LIMIT),
      range: cfg.newsRange || "30",
    });
    if (refresh) params.set("refresh", "1");
    return `${cfg.feedUrl}?${params.toString()}`;
  }

  async function loadNews({ append = false, refresh = false } = {}) {
    if (!cfg.feedUrl || !cfg.selectedTicker || loading) return;

    const offset = append ? currentOffset : 0;
    setLoading(true);
    setStatus("", false);
    if (!append) {
      $("newsList")?.replaceChildren();
      $("newsListPanel")?.setAttribute("hidden", "");
      $("newsEmpty")?.setAttribute("hidden", "");
    }

    try {
      const res = await fetch(buildFeedUrl(offset, refresh));
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "加载失败");

      const items = data.items || [];
      hasMore = !!data.has_more;
      currentOffset = offset + items.length;

      const list = $("newsList");
      if (list) {
        items.forEach((item) => {
          list.insertAdjacentHTML("beforeend", renderNewsCard(item));
        });
      }

      const hasItems = (list?.children.length || 0) > 0;
      $("newsListPanel")?.toggleAttribute("hidden", !hasItems);
      $("newsEmpty")?.toggleAttribute("hidden", hasItems);
      $("loadMoreNewsBtn")?.toggleAttribute("hidden", !hasMore || !hasItems);
    } catch (error) {
      setStatus(error.message || "加载失败", true);
      if (!append) {
        $("newsListPanel")?.setAttribute("hidden", "");
        $("newsEmpty")?.removeAttribute("hidden");
      }
    } finally {
      setLoading(false);
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    if (!cfg.hasTickers || !cfg.selectedTicker) return;
    loadNews();

    $("refreshNewsBtn")?.addEventListener("click", () => {
      currentOffset = 0;
      loadNews({ refresh: true });
    });

    $("loadMoreNewsBtn")?.addEventListener("click", () => {
      if (hasMore) loadNews({ append: true });
    });
  });
})();
