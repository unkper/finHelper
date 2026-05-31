(function () {
  const cfg = window.RESEARCH_PAGE || {};
  const pageSize = cfg.pageSize || 5;
  const listEl = document.getElementById("reportsList");
  const emptyEl = document.getElementById("reportsEmpty");
  const loadingEl = document.getElementById("reportsLoading");
  const pagerEl = document.getElementById("reportsPager");
  const pagerMetaEl = document.getElementById("reportsPagerMeta");
  const prevPageBtn = document.getElementById("reportsPrevPage");
  const nextPageBtn = document.getElementById("reportsNextPage");
  const pageLabelEl = document.getElementById("reportsPageLabel");
  const searchEl = document.getElementById("reportsSearch");
  const modal = document.getElementById("newReportModal");
  const form = document.getElementById("newReportForm");
  const sourceTextEl = document.getElementById("reportSourceText");
  const sampleHintEl = document.getElementById("sampleActionHint");
  const pasteFields = document.getElementById("pasteFields");
  const pdfFields = document.getElementById("pdfFields");
  const pdfFileEl = document.getElementById("reportPdfFile");
  let createMode = "paste";
  let currentPage = 1;
  let searchQuery = "";
  let listMeta = { total: 0, page: 1, total_pages: 0 };
  let searchDebounceTimer = null;

  const SAMPLE_REPORT_TEXT = `【NVDA · 2026财年第一财季（2026-Q1）财报解读】
发布日：2026-05-28（盘后）

一、核心结论
本季营收继续扩张，但增速较上季放缓；毛利率维持高位，研发投入占比上升。
经营现金流低于净利润，需关注应收与渠道库存。

二、关键指标（2026-Q1，单位：百万美元）
- 营业总收入：39,300 M USD，同比 +5.1%，环比 -2.0%
- 净利润：9,700 M USD，同比 +8.0%
- 扣非净利润：9,500 M USD（剔除一次性 tax benefit 约 200M）
- 毛利率：46.2%
- ROE（年化）：28.5%

三、利润表结构（2026-Q1，百万美元）
- 营业收入：39,300
- 营业成本（COGS）：21,200
- 毛利润：18,100
- 研发费用（R&D）：7,700
- 销售及管理费用（SG&A）：6,300
- 营业利润：4,100
- 所得税：800
- 净利润：9,700

四、资产负债表要点（2026-Q1 末，百万美元）
- 现金及等价物：6,200
- 应收账款：9,800
- 存货：5,100
- 固定资产（PP&E）：45,000
- 总资产：82,000
- 流动负债：12,000
- 长期债务：18,000
- 股东权益：45,000

五、现金流量表（2026-Q1，百万美元）
- 经营活动现金流：+2,200
- 投资活动现金流：-1,500
- 筹资活动现金流：-800

六、与上季对比（2025-Q4，供趋势参考）
- 2025-Q4 营收：40,100 M USD
- 2025-Q4 净利润：9,200 M USD
- 2025-Q4 毛利率：47.1%
- 2025-Q4 经营现金流：3,800 M USD

七、风险提示
1. 净利润显著高于经营现金流，需关注回款与收入确认节奏。
2. 存货连续上升，若下游需求不及预期，存在减值风险。
3. 长期债务与流动负债合计占资产比例不低，需关注利率环境。`;

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text == null ? "" : String(text);
    return div.innerHTML;
  }

  function openModal() {
    if (modal) modal.hidden = false;
  }

  function closeModal() {
    if (modal) modal.hidden = true;
    if (form) form.reset();
    showSampleHint("");
    setCreateMode("paste");
  }

  function setCreateMode(mode) {
    createMode = mode === "pdf" ? "pdf" : "paste";
    document.querySelectorAll(".research-create-tab").forEach((btn) => {
      btn.classList.toggle("is-active", btn.dataset.mode === createMode);
    });
    if (pasteFields) pasteFields.hidden = createMode !== "paste";
    if (pdfFields) pdfFields.hidden = createMode !== "pdf";
    if (sourceTextEl) sourceTextEl.required = createMode === "paste";
    if (pdfFileEl) pdfFileEl.required = createMode === "pdf";
    const submitBtn = document.getElementById("newReportSubmitBtn");
    if (submitBtn) {
      submitBtn.textContent = createMode === "pdf" ? "上传并解析" : "创建并打开";
    }
  }

  function showSampleHint(message, ok) {
    if (!sampleHintEl) return;
    if (!message) {
      sampleHintEl.hidden = true;
      sampleHintEl.textContent = "";
      sampleHintEl.classList.remove("is-ok");
      return;
    }
    sampleHintEl.hidden = false;
    sampleHintEl.textContent = message;
    sampleHintEl.classList.toggle("is-ok", !!ok);
  }

  function normalizeFiscalPeriodInput(el) {
    if (!el || !el.value) return;
    el.value = el.value.trim().toUpperCase();
  }

  function insertSampleTemplate() {
    if (!sourceTextEl) return;
    const current = (sourceTextEl.value || "").trim();
    if (current && !window.confirm("输入框已有内容，是否替换为范例模板？")) {
      return;
    }
    sourceTextEl.value = SAMPLE_REPORT_TEXT;
    const tickerEl = document.getElementById("reportTicker");
    const periodInput = form?.querySelector('[name="fiscal_period"]');
    if (tickerEl && !tickerEl.value.trim()) tickerEl.value = "NVDA";
    if (periodInput && !periodInput.value.trim()) periodInput.value = "2026-Q1";
    showSampleHint("已插入范例模板，可按实际财报修改数字后创建。", true);
    sourceTextEl.focus();
  }

  async function copySampleTemplate() {
    try {
      await navigator.clipboard.writeText(SAMPLE_REPORT_TEXT);
      showSampleHint("范例已复制到剪贴板，可粘贴到任意编辑器修改后再填回。", true);
    } catch (err) {
      if (sourceTextEl) {
        sourceTextEl.value = SAMPLE_REPORT_TEXT;
        sourceTextEl.select();
        showSampleHint("无法访问剪贴板，已改为插入到输入框。", false);
      } else {
        showSampleHint("复制失败，请手动选择范例内容。", false);
      }
    }
  }

  function updatePagerUi() {
    const { total, page, total_pages } = listMeta;
    const hasSearch = Boolean(searchQuery.trim());

    if (pagerMetaEl) {
      if (total > 0) {
        pagerMetaEl.hidden = false;
        pagerMetaEl.textContent = `共 ${total} 条，第 ${page} / ${total_pages} 页`;
      } else {
        pagerMetaEl.hidden = true;
      }
    }

    if (pagerEl) {
      pagerEl.hidden = total_pages <= 1;
    }

    if (pageLabelEl) {
      pageLabelEl.textContent = total_pages
        ? `第 ${page} / ${total_pages} 页`
        : "第 0 / 0 页";
    }

    if (prevPageBtn) prevPageBtn.disabled = page <= 1;
    if (nextPageBtn) nextPageBtn.disabled = page >= total_pages || total_pages === 0;
  }

  function renderReports(reports) {
    if (!listEl) return;
    const total = listMeta.total;
    const hasFilter = Boolean(searchQuery.trim()) || Boolean(cfg.tickerFilter);

    if (!total && !reports.length) {
      listEl.innerHTML = "";
      emptyEl.hidden = false;
      emptyEl.textContent = hasFilter
        ? "无匹配报告，请调整搜索条件。"
        : "暂无报告，点击「新建报告」开始。";
      updatePagerUi();
      return;
    }

    emptyEl.hidden = true;
    listEl.innerHTML = reports
      .map((r) => {
        const href = cfg.detailUrlTemplate.replace("__ID__", r.id);
        let badge = r.has_analysis
          ? '<span class="research-badge">已分析</span>'
          : '<span class="research-badge pending">待分析</span>';
        if (r.parse_status === "extracting_text" || r.parse_status === "ai_analyzing") {
          badge = '<span class="research-badge pending">解析中</span>';
        } else if (r.parse_status === "failed") {
          badge = '<span class="research-badge pending">解析失败</span>';
        }
        const tickerLink = `${window.location.pathname}?tab=analysis&ticker=${encodeURIComponent(r.ticker)}`;
        const deleteUrl = cfg.deleteUrlTemplate
          ? cfg.deleteUrlTemplate.replace("__ID__", r.id)
          : "";
        const deleteBtn = deleteUrl
          ? `<button type="button" class="secondary-btn research-report-delete-btn" data-delete-url="${escapeHtml(deleteUrl)}" data-report-title="${escapeHtml(r.title)}">删除</button>`
          : "";
        return `
          <article class="research-report-card">
            <div>
              <a href="${href}"><strong>${escapeHtml(r.title)}</strong></a>
              <p class="research-report-meta">
                <a href="${tickerLink}">${escapeHtml(r.ticker)}</a>
                · ${escapeHtml(r.fiscal_period)}
                · 更新 ${escapeHtml(r.updated_at || "")}
                ${r.source_type === "pdf" ? " · PDF" : ""}
              </p>
            </div>
            <div class="research-report-card-actions">
              ${badge}
              ${deleteBtn}
            </div>
          </article>`;
      })
      .join("");
    updatePagerUi();
  }

  function buildReportsUrl() {
    const params = new URLSearchParams();
    params.set("page", String(currentPage));
    params.set("per_page", String(pageSize));
    if (searchQuery.trim()) params.set("search", searchQuery.trim());
    if (cfg.tickerFilter) params.set("ticker", cfg.tickerFilter);
    return `${cfg.reportsUrl}?${params.toString()}`;
  }

  async function loadReports() {
    if (!cfg.reportsUrl) return;
    loadingEl.hidden = false;
    emptyEl.hidden = true;
    try {
      const res = await fetch(buildReportsUrl());
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "加载失败");
      listMeta = {
        total: data.total ?? 0,
        page: data.page ?? currentPage,
        total_pages: data.total_pages ?? 0,
      };
      currentPage = listMeta.page;
      renderReports(data.reports || []);
    } catch (err) {
      listEl.innerHTML = "";
      emptyEl.hidden = false;
      emptyEl.textContent = err.message || "加载失败，请刷新页面";
      if (pagerEl) pagerEl.hidden = true;
      if (pagerMetaEl) pagerMetaEl.hidden = true;
    } finally {
      loadingEl.hidden = true;
    }
  }

  function scheduleSearch() {
    if (searchDebounceTimer) clearTimeout(searchDebounceTimer);
    searchDebounceTimer = setTimeout(() => {
      searchQuery = searchEl ? searchEl.value.trim() : "";
      currentPage = 1;
      loadReports();
    }, 300);
  }

  searchEl?.addEventListener("input", scheduleSearch);
  searchEl?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      if (searchDebounceTimer) clearTimeout(searchDebounceTimer);
      searchQuery = searchEl.value.trim();
      currentPage = 1;
      loadReports();
    }
  });

  prevPageBtn?.addEventListener("click", () => {
    if (currentPage > 1) {
      currentPage -= 1;
      loadReports();
    }
  });

  nextPageBtn?.addEventListener("click", () => {
    if (currentPage < listMeta.total_pages) {
      currentPage += 1;
      loadReports();
    }
  });

  document.getElementById("newReportBtn")?.addEventListener("click", openModal);
  document.getElementById("closeNewReportModal")?.addEventListener("click", closeModal);
  document.getElementById("cancelNewReport")?.addEventListener("click", closeModal);
  document.getElementById("insertSampleBtn")?.addEventListener("click", insertSampleTemplate);
  document.getElementById("copySampleBtn")?.addEventListener("click", copySampleTemplate);
  document.querySelectorAll(".research-create-tab").forEach((btn) => {
    btn.addEventListener("click", () => setCreateMode(btn.dataset.mode));
  });

  form?.querySelector('[name="fiscal_period"]')?.addEventListener("blur", (e) => {
    normalizeFiscalPeriodInput(e.target);
  });

  form?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const periodEl = form.querySelector('[name="fiscal_period"]');
    normalizeFiscalPeriodInput(periodEl);
    try {
      if (createMode === "pdf") {
        if (!cfg.uploadUrl) throw new Error("上传接口未配置");
        const file = pdfFileEl?.files?.[0];
        if (!file) throw new Error("请选择 PDF 文件");
        const uploadFd = new FormData();
        uploadFd.append("ticker", fd.get("ticker"));
        uploadFd.append("fiscal_period", fd.get("fiscal_period"));
        uploadFd.append("title", fd.get("title") || "");
        uploadFd.append("report_date", fd.get("report_date") || "");
        uploadFd.append("file", file);
        const res = await fetch(cfg.uploadUrl, { method: "POST", body: uploadFd });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "上传失败");
        window.location.href = cfg.detailUrlTemplate.replace("__ID__", data.report_id);
        return;
      }
      const payload = {
        ticker: fd.get("ticker"),
        fiscal_period: fd.get("fiscal_period"),
        title: fd.get("title"),
        report_date: fd.get("report_date") || null,
        source_text: fd.get("source_text"),
      };
      const res = await fetch(cfg.createUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "创建失败");
      window.location.href = cfg.detailUrlTemplate.replace("__ID__", data.report_id);
    } catch (err) {
      alert(err.message || "创建失败");
    }
  });

  listEl?.addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-delete-url]");
    if (!btn) return;
    e.preventDefault();
    const url = btn.getAttribute("data-delete-url");
    const title = btn.getAttribute("data-report-title") || "该报告";
    if (!window.confirm(`确定删除「${title}」？此操作不可恢复。`)) return;
    try {
      const res = await fetch(url, { method: "POST" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "删除失败");
      const remainingOnPage = listEl.querySelectorAll(".research-report-card").length - 1;
      if (remainingOnPage <= 0 && currentPage > 1) {
        currentPage -= 1;
      }
      await loadReports();
    } catch (err) {
      alert(err.message || "删除失败");
    }
  });

  loadReports();
})();
