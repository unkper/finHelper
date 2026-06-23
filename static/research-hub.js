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
  const secFields = document.getElementById("secFields");
  const pdfFileEl = document.getElementById("reportPdfFile");
  const fmpPeriodFields = document.getElementById("fmpPeriodFields");
  const manualPeriodFields = document.getElementById("manualPeriodFields");
  const fmpYearEl = document.getElementById("fmpYear");
  const fmpPeriodEl = document.getElementById("fmpPeriod");
  const fmpPeriodHintEl = document.getElementById("fmpPeriodHint");
  const calYearEl = document.getElementById("calYear");
  const calQuarterEl = document.getElementById("calQuarter");
  const fiscalPeriodHidden = document.getElementById("fiscalPeriodHidden");
  let fmpPeriodsCache = [];
  let fmpPeriodsLoadToken = 0;
  let createMode = "sec";
  let currentPage = 1;
  let searchQuery = "";
  let listMeta = { total: 0, page: 1, total_pages: 0 };
  let searchDebounceTimer = null;
  let batchPollTimer = null;
  let activeBatchJobId = null;

  async function safeJson(res) {
    const text = await res.text();
    try {
      return { ok: res.ok, data: JSON.parse(text) };
    } catch {
      throw new Error(
        res.status === 504 ? "网关超时，请稍后重试" : "服务返回非 JSON（可能登录过期）"
      );
    }
  }

  const batchModal = document.getElementById("batchTrackModal");
  const batchForm = document.getElementById("batchTrackForm");
  const batchJobPanel = document.getElementById("batchJobPanel");
  const batchJobMessage = document.getElementById("batchJobMessage");
  const batchJobProgress = document.getElementById("batchJobProgress");
  const batchJobItems = document.getElementById("batchJobItems");
  const batchSubmitBtn = document.getElementById("batchTrackSubmitBtn");

  function populateManualYearOptions() {
    if (!calYearEl) return;
    const now = new Date().getFullYear();
    calYearEl.innerHTML = "";
    for (let y = now + 1; y >= now - 7; y -= 1) {
      const opt = document.createElement("option");
      opt.value = String(y);
      opt.textContent = String(y);
      calYearEl.appendChild(opt);
    }
  }

  function composeManualFiscalPeriod() {
    const year = calYearEl?.value;
    const quarter = calQuarterEl?.value;
    if (!year || !quarter) return "";
    return `${year}-${quarter}`;
  }

  function syncManualFiscalPeriodHidden() {
    if (fiscalPeriodHidden && createMode !== "sec") {
      fiscalPeriodHidden.value = composeManualFiscalPeriod();
    }
  }

  function resetFmpPeriodSelects(message) {
    if (fmpYearEl) {
      fmpYearEl.innerHTML = `<option value="">${message || "请先输入 Ticker"}</option>`;
      fmpYearEl.disabled = true;
    }
    if (fmpPeriodEl) {
      fmpPeriodEl.innerHTML = `<option value="">${message ? "无可用报告期" : "请先选择财年"}</option>`;
      fmpPeriodEl.disabled = true;
    }
    if (fmpPeriodHintEl) {
      fmpPeriodHintEl.textContent = message || "从 FMP 拉取可用 10-Q/10-K 报告期；选定后显示对应日历季。";
    }
    fmpPeriodsCache = [];
  }

  function renderFmpPeriodOptions() {
    if (!fmpYearEl || !fmpPeriodEl) return;
    const years = [...new Set(fmpPeriodsCache.map((p) => String(p.year)))].sort((a, b) => Number(b) - Number(a));
    fmpYearEl.innerHTML = years.length
      ? '<option value="">选择财年</option>' + years.map((y) => `<option value="${y}">FY${y}</option>`).join("")
      : '<option value="">无可用报告期</option>';
    fmpYearEl.disabled = !years.length;
    fmpPeriodEl.innerHTML = '<option value="">请先选择财年</option>';
    fmpPeriodEl.disabled = true;
    if (fmpPeriodHintEl) {
      fmpPeriodHintEl.textContent = years.length
        ? `共 ${fmpPeriodsCache.length} 个 FMP 报告期可选。`
        : "该 Ticker 在 FMP 无可用 SEC 报告期。";
    }
  }

  function renderFmpPeriodsForYear(year) {
    if (!fmpPeriodEl) return;
    const items = fmpPeriodsCache.filter((p) => String(p.year) === String(year));
    fmpPeriodEl.innerHTML = items.length
      ? '<option value="">选择报告期</option>' +
        items
          .map((p) => `<option value="${p.period}" data-form="${p.form_type || ""}">${escapeHtml(p.label || `${p.period}`)}</option>`)
          .join("")
      : '<option value="">无报告期</option>';
    fmpPeriodEl.disabled = !items.length;
    updateFmpPeriodHint();
  }

  async function updateFmpPeriodHint() {
    if (!fmpPeriodHintEl || createMode !== "sec") return;
    const ticker = form?.querySelector('[name="ticker"]')?.value?.trim().toUpperCase();
    const year = fmpYearEl?.value;
    const period = fmpPeriodEl?.value;
    if (!ticker || !year || !period) {
      fmpPeriodHintEl.textContent = "选定 FMP 财年与报告期后将显示对应日历季。";
      return;
    }
    const cached = fmpPeriodsCache.find((p) => String(p.year) === String(year) && p.period === period);
    if (cached?.calendar_period) {
      fmpPeriodHintEl.textContent = `日历季：${cached.calendar_period}${cached.period_end ? ` · 期末 ${cached.period_end}` : ""}`;
      return;
    }
    if (!cfg.fmpPeriodsUrl) return;
    fmpPeriodHintEl.textContent = "正在解析日历季…";
    try {
      const url = `${cfg.fmpPeriodsUrl}?ticker=${encodeURIComponent(ticker)}&year=${encodeURIComponent(year)}&period=${encodeURIComponent(period)}`;
      const res = await fetch(url);
      const { ok, data } = await safeJson(res);
      if (!ok) throw new Error(data.error || "预览失败");
      const match = (data.periods || []).find((p) => String(p.year) === String(year) && p.period === period);
      if (match?.calendar_period) {
        cached.calendar_period = match.calendar_period;
        cached.period_end = match.period_end;
        fmpPeriodHintEl.textContent = `日历季：${match.calendar_period}${match.period_end ? ` · 期末 ${match.period_end}` : ""}`;
      } else {
        fmpPeriodHintEl.textContent = "未能解析日历季，提交后将由服务端映射。";
      }
    } catch (err) {
      fmpPeriodHintEl.textContent = err.message || "日历季预览失败";
    }
  }

  async function loadFmpPeriods(ticker) {
    const symbol = (ticker || "").trim().toUpperCase();
    if (!symbol || !cfg.fmpPeriodsUrl) {
      resetFmpPeriodSelects();
      return;
    }
    const token = ++fmpPeriodsLoadToken;
    resetFmpPeriodSelects("加载中…");
    try {
      const res = await fetch(`${cfg.fmpPeriodsUrl}?ticker=${encodeURIComponent(symbol)}`);
      const { ok, data } = await safeJson(res);
      if (!ok) throw new Error(data.error || "加载失败");
      if (token !== fmpPeriodsLoadToken) return;
      fmpPeriodsCache = data.periods || [];
      renderFmpPeriodOptions();
    } catch (err) {
      if (token !== fmpPeriodsLoadToken) return;
      resetFmpPeriodSelects(err.message || "加载 FMP 报告期失败");
    }
  }

  const SAMPLE_REPORT_TEXT = `【NVDA · 2026财年第一财季（2026-Q1）财报解读】

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
    setCreateMode("sec");
  }

  function setCreateMode(mode) {
    createMode = mode === "pdf" ? "pdf" : mode === "paste" ? "paste" : "sec";
    document.querySelectorAll(".research-create-tab").forEach((btn) => {
      btn.classList.toggle("is-active", btn.dataset.mode === createMode);
    });
    if (secFields) secFields.hidden = createMode !== "sec";
    if (pasteFields) pasteFields.hidden = createMode !== "paste";
    if (pdfFields) pdfFields.hidden = createMode !== "pdf";
    if (fmpPeriodFields) fmpPeriodFields.hidden = createMode !== "sec";
    if (manualPeriodFields) manualPeriodFields.hidden = createMode === "sec";
    if (sourceTextEl) sourceTextEl.required = createMode === "paste";
    if (pdfFileEl) pdfFileEl.required = createMode === "pdf";
    if (fmpYearEl) fmpYearEl.required = createMode === "sec";
    if (fmpPeriodEl) fmpPeriodEl.required = createMode === "sec";
    const tickerEl = form?.querySelector('[name="ticker"]');
    if (tickerEl) tickerEl.required = true;
    syncManualFiscalPeriodHidden();
    const submitBtn = document.getElementById("newReportSubmitBtn");
    if (submitBtn) {
      if (createMode === "pdf") submitBtn.textContent = "上传并解析";
      else if (createMode === "sec") submitBtn.textContent = "从 FMP 获取并解析";
      else submitBtn.textContent = "创建并打开";
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
    if (tickerEl && !tickerEl.value.trim()) tickerEl.value = "NVDA";
    if (calYearEl) calYearEl.value = "2026";
    if (calQuarterEl) calQuarterEl.value = "Q1";
    syncManualFiscalPeriodHidden();
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
        } else if (r.has_pending) {
          badge = '<span class="research-badge research-badge--confirm">待确认</span>';
        }
        const tickerLink = `${window.location.pathname}?tab=analysis&ticker=${encodeURIComponent(r.ticker)}`;
        const deleteUrl = cfg.deleteUrlTemplate
          ? cfg.deleteUrlTemplate.replace("__ID__", r.id)
          : "";
        const deleteBtn = deleteUrl
          ? `<button type="button" class="secondary-btn research-report-delete-btn" data-delete-url="${escapeHtml(deleteUrl)}" data-report-title="${escapeHtml(r.title)}">删除</button>`
          : "";
        const sourceLabel =
          r.source_type === "sec_fmp"
            ? ` · ${escapeHtml(r.filing_form_type || "FMP")}${r.filing_fy && r.filing_fq ? ` FY${r.filing_fy} Q${r.filing_fq}` : ""}`
            : r.source_type === "pdf"
              ? " · PDF"
              : "";
        return `
          <article class="research-report-card">
            <div>
              <a href="${href}"><strong>${escapeHtml(r.title)}</strong></a>
              <p class="research-report-meta">
                <a href="${tickerLink}">${escapeHtml(r.ticker)}</a>
                · ${escapeHtml(r.fiscal_period)}
                · 更新 ${escapeHtml(r.updated_at || "")}
                ${sourceLabel}
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

  form?.querySelector('[name="ticker"]')?.addEventListener("change", (e) => {
    if (createMode === "sec") loadFmpPeriods(e.target.value);
  });
  form?.querySelector('[name="ticker"]')?.addEventListener("blur", (e) => {
    if (createMode === "sec") loadFmpPeriods(e.target.value);
  });
  fmpYearEl?.addEventListener("change", (e) => {
    renderFmpPeriodsForYear(e.target.value);
  });
  fmpPeriodEl?.addEventListener("change", () => {
    updateFmpPeriodHint();
  });
  calYearEl?.addEventListener("change", syncManualFiscalPeriodHidden);
  calQuarterEl?.addEventListener("change", syncManualFiscalPeriodHidden);

  form?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    syncManualFiscalPeriodHidden();
    try {
      if (createMode === "sec") {
        if (!cfg.fetchFmpUrl) throw new Error("FMP 接口未配置");
        const ticker = String(fd.get("ticker") || "").trim().toUpperCase();
        const year = fmpYearEl?.value;
        const period = fmpPeriodEl?.value;
        if (!ticker) throw new Error("请填写 Ticker");
        if (!year || !period) throw new Error("请选择 FMP 财年与报告期");
        const payload = {
          ticker,
          year: Number(year),
          period,
          title: fd.get("title") || "",
          report_date: fd.get("report_date") || null,
        };
        const res = await fetch(cfg.fetchFmpUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const { ok, data } = await safeJson(res);
        if (!ok) throw new Error(data.error || "获取失败");
        window.location.href = cfg.detailUrlTemplate.replace("__ID__", data.report_id);
        return;
      }
      if (createMode === "pdf") {
        if (!cfg.uploadUrl) throw new Error("上传接口未配置");
        const file = pdfFileEl?.files?.[0];
        if (!file) throw new Error("请选择 PDF 文件");
        const fiscalPeriod = composeManualFiscalPeriod();
        if (!fiscalPeriod) throw new Error("请选择日历年份与季度");
        const uploadFd = new FormData();
        uploadFd.append("ticker", fd.get("ticker"));
        uploadFd.append("fiscal_period", fiscalPeriod);
        uploadFd.append("title", fd.get("title") || "");
        uploadFd.append("report_date", fd.get("report_date") || "");
        uploadFd.append("file", file);
        const res = await fetch(cfg.uploadUrl, { method: "POST", body: uploadFd });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "上传失败");
        window.location.href = cfg.detailUrlTemplate.replace("__ID__", data.report_id);
        return;
      }
      const fiscalPeriod = composeManualFiscalPeriod();
      if (!fiscalPeriod) throw new Error("请选择日历年份与季度");
      const payload = {
        ticker: fd.get("ticker"),
        fiscal_period: fiscalPeriod,
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

  function batchItemStatusLabel(status) {
    const map = {
      success: "成功",
      skipped: "跳过",
      failed: "失败",
      pending: "处理中",
    };
    return map[status] || status;
  }

  function renderBatchJob(job) {
    if (!batchJobPanel) return;
    batchJobPanel.hidden = false;
    if (batchJobMessage) {
      const err = job.error ? ` · ${job.error}` : "";
      batchJobMessage.textContent = `${job.message || ""}${err}`;
    }
    if (batchJobProgress) batchJobProgress.value = job.progress || 0;
    if (!batchJobItems) return;
    const items = job.items || [];
    batchJobItems.innerHTML = items
      .map((item) => {
        const fp = item.fiscal_period ? ` · ${escapeHtml(item.fiscal_period)}` : "";
        const err = item.error ? ` — ${escapeHtml(item.error)}` : "";
        const link =
          item.report_id && cfg.detailUrlTemplate
            ? ` <a href="${cfg.detailUrlTemplate.replace("__ID__", item.report_id)}">查看</a>`
            : "";
        return `<li class="research-batch-item research-batch-item--${escapeHtml(item.status)}">
          FY${item.fmp_year} ${escapeHtml(item.fmp_period)}${fp}
          · ${batchItemStatusLabel(item.status)}${err}${link}
        </li>`;
      })
      .join("");
  }

  function openBatchModal() {
    if (!batchModal) return;
    batchModal.hidden = false;
    if (batchJobPanel) batchJobPanel.hidden = true;
    if (batchForm) batchForm.hidden = false;
    if (batchSubmitBtn) batchSubmitBtn.disabled = false;
    const tickerEl = document.getElementById("batchTicker");
    if (tickerEl && cfg.tickerFilter) tickerEl.value = cfg.tickerFilter;
  }

  function closeBatchModal() {
    if (batchModal) batchModal.hidden = true;
    if (batchPollTimer) {
      clearInterval(batchPollTimer);
      batchPollTimer = null;
    }
    activeBatchJobId = null;
    if (batchForm) {
      batchForm.reset();
      batchForm.hidden = false;
    }
    if (batchJobPanel) batchJobPanel.hidden = true;
  }

  async function pollBatchJob(jobId) {
    if (!cfg.batchJobUrlTemplate) return;
    try {
      const url = cfg.batchJobUrlTemplate.replace("__ID__", jobId);
      const res = await fetch(url);
      const { ok, data } = await safeJson(res);
      if (!ok) throw new Error(data.error || "查询失败");
      renderBatchJob(data);
      if (data.status === "done" || data.status === "failed") {
        if (batchPollTimer) {
          clearInterval(batchPollTimer);
          batchPollTimer = null;
        }
        if (batchSubmitBtn) batchSubmitBtn.disabled = false;
        await loadReports();
      }
    } catch (err) {
      if (batchJobMessage) batchJobMessage.textContent = err.message || "轮询失败";
    }
  }

  function startBatchPolling(jobId) {
    activeBatchJobId = jobId;
    if (batchForm) batchForm.hidden = true;
    if (batchSubmitBtn) batchSubmitBtn.disabled = true;
    pollBatchJob(jobId);
    if (batchPollTimer) clearInterval(batchPollTimer);
    batchPollTimer = setInterval(() => pollBatchJob(jobId), 3000);
  }

  batchForm?.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!cfg.batchJobsUrl) {
      alert("批量接口未配置");
      return;
    }
    const ticker = String(new FormData(batchForm).get("ticker") || "")
      .trim()
      .toUpperCase();
    if (!ticker) {
      alert("请填写 Ticker");
      return;
    }
    try {
      if (batchSubmitBtn) {
        batchSubmitBtn.disabled = true;
        batchSubmitBtn.textContent = "提交中…";
      }
      const res = await fetch(cfg.batchJobsUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticker, target_count: 4 }),
      });
      const { ok, data } = await safeJson(res);
      if (!ok) throw new Error(data.error || "启动失败");
      startBatchPolling(data.job_id);
    } catch (err) {
      alert(err.message || "批量任务启动失败");
      if (batchSubmitBtn) batchSubmitBtn.disabled = false;
    } finally {
      if (batchSubmitBtn) batchSubmitBtn.textContent = "开始批量拉取";
    }
  });

  document.getElementById("batchTrackBtn")?.addEventListener("click", openBatchModal);
  document.getElementById("closeBatchTrackModal")?.addEventListener("click", closeBatchModal);
  document.getElementById("cancelBatchTrack")?.addEventListener("click", closeBatchModal);

  populateManualYearOptions();
  setCreateMode("sec");
  loadReports();
})();
