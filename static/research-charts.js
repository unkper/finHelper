(function () {
  const cfg = window.FINANCIAL_REPORT_PAGE || {};
  const charts = {};
  let lastChartPayload = null;
  let parsePollTimer = null;
  let activeSection = "profitability";

  function fmtNum(v, unit) {
    if (v == null || Number.isNaN(v)) return "—";
    return `${v.toLocaleString()} ${unit === "millions" ? "M" : ""}`;
  }

  function fmtPct(v) {
    if (v == null || Number.isNaN(v)) return "";
    const sign = v > 0 ? "+" : "";
    return `${sign}${v}%`;
  }

  function renderKpis(data) {
    const grid = document.getElementById("kpiGrid");
    if (!grid) return;
    const period = data.focus_period;
    const kpis = (data.kpis && data.kpis[period]) || {};
    const cards = [
      { key: "revenue", label: "营业总收入", metric: kpis.revenue },
      { key: "net_profit", label: "净利润", metric: kpis.net_profit },
      { key: "net_profit_adjusted", label: "扣非净利润", metric: kpis.net_profit_adjusted },
      { key: "gross_margin_pct", label: "毛利率", raw: kpis.gross_margin_pct, suffix: "%" },
      { key: "roe_pct", label: "ROE", raw: kpis.roe_pct, suffix: "%" },
    ];

    grid.innerHTML = cards
      .map((c) => {
        let valueHtml = "—";
        let deltaHtml = "";
        if (c.metric) {
          valueHtml = fmtNum(c.metric.value, data.unit);
          const yoy = c.metric.yoy_pct;
          if (yoy != null) {
            const cls = yoy >= 0 ? "positive" : "negative";
            deltaHtml = `<div class="research-kpi-delta ${cls}">YoY ${fmtPct(yoy)}</div>`;
          }
        } else if (c.raw != null) {
          valueHtml = `${c.raw}${c.suffix || ""}`;
        }
        return `
          <article class="research-kpi-card">
            <div class="research-kpi-label">${c.label}</div>
            <div class="research-kpi-value">${valueHtml}</div>
            ${deltaHtml}
          </article>`;
      })
      .join("");
  }

  function renderRedFlags(flags) {
    const panel = document.getElementById("redFlagsPanel");
    if (!panel) return;
    if (!flags || !flags.length) {
      panel.hidden = true;
      return;
    }
    panel.hidden = false;
    panel.innerHTML = `<strong>风险提示</strong><ul>${flags.map((f) => `<li>${f.message}</li>`).join("")}</ul>`;
  }

  function escapeHtmlText(text) {
    const div = document.createElement("div");
    div.textContent = text == null ? "" : String(text);
    return div.innerHTML;
  }

  function renderMaterialEvents(events, unit) {
    const panel = document.getElementById("materialEventsPanel");
    if (!panel) return;
    if (!events || !events.length) {
      panel.hidden = true;
      panel.innerHTML = "";
      return;
    }
    const unitLabel = unit === "millions" ? "百万 USD" : unit || "USD";
    const profitItems = events.filter((e) => e.type === "profit");
    const lossItems = events.filter((e) => e.type === "loss");

    function renderList(items, listClass) {
      if (!items.length) return "";
      return `<ul class="research-material-events-list ${listClass}">${items
        .map((e) => {
          const amount =
            e.amount_millions != null && !Number.isNaN(e.amount_millions)
              ? `<span class="research-material-events-amount">${e.amount_millions} ${unitLabel}</span>`
              : "";
          const period = e.period
            ? `<span class="research-material-events-period">${escapeHtmlText(e.period)}</span>`
            : "";
          return `<li>
            <div class="research-material-events-head">
              <strong>${escapeHtmlText(e.title)}</strong>
              ${amount}
              ${period}
            </div>
            <p>${escapeHtmlText(e.description)}</p>
          </li>`;
        })
        .join("")}</ul>`;
    }

    panel.hidden = false;
    panel.innerHTML = `
      <strong>盈利 / 亏损大事记</strong>
      <p class="hint">来自 AI 对解读文中较大一次性事项的结构化摘录，供图表与全局解读参考。</p>
      ${profitItems.length ? `<h4 class="research-material-events-subtitle research-material-events-subtitle--profit">较大盈利事项</h4>${renderList(profitItems, "research-material-events-list--profit")}` : ""}
      ${lossItems.length ? `<h4 class="research-material-events-subtitle research-material-events-subtitle--loss">较大亏损 / 费用冲击</h4>${renderList(lossItems, "research-material-events-list--loss")}` : ""}
    `;
  }

  function initChart(id) {
    const el = document.getElementById(id);
    if (!el || !window.echarts) return null;
    if (charts[id]) charts[id].dispose();
    charts[id] = echarts.init(el);
    return charts[id];
  }

  function hasAnyValue(arr) {
    return Array.isArray(arr) && arr.some((v) => v != null && !Number.isNaN(v));
  }

  function setPanelEmpty(chartType, isEmpty) {
    const panel = document.getElementById(`panel-${chartType}`);
    if (!panel) return;
    if (isEmpty) {
      panel.dataset.empty = "1";
      panel.hidden = true;
    } else {
      delete panel.dataset.empty;
      if (panel.dataset.section === activeSection) {
        panel.hidden = false;
      }
    }
  }

  function applySectionTab(section) {
    activeSection = section;
    document.querySelectorAll(".research-section-tab").forEach((tab) => {
      tab.classList.toggle("is-active", tab.dataset.section === section);
    });
    document.querySelectorAll(".research-charts-grid .research-chart-panel").forEach((panel) => {
      const match = panel.dataset.section === section;
      const empty = panel.dataset.empty === "1";
      panel.hidden = !match || empty;
    });
    resizeVisibleCharts();
  }

  function resizeVisibleCharts() {
    Object.entries(charts).forEach(([id, chart]) => {
      const el = document.getElementById(id);
      if (chart && el && el.offsetParent !== null) {
        chart.resize();
      }
    });
  }

  function showChartInsight(chartType, text) {
    const wrap = document.querySelector(`[data-insight-wrap="${chartType}"]`);
    const panel = document.querySelector(`[data-insight-for="${chartType}"]`);
    if (panel) panel.textContent = text;
    if (wrap) {
      wrap.hidden = false;
      wrap.open = true;
    }
  }

  function renderWaterfall(data) {
    const chart = initChart("waterfallChart");
    if (!chart) return;
    const period = data.focus_period;
    const inc = (data.income_statement && data.income_statement[period]) || {};
    const steps = [
      { name: "营收", val: inc.revenue, type: "pos" },
      { name: "营业成本", val: inc.cogs ? -inc.cogs : null, type: "neg" },
      { name: "毛利", val: inc.gross_profit, type: "sub" },
      { name: "研发", val: inc.rd ? -inc.rd : null, type: "neg" },
      { name: "销管", val: inc.sga ? -inc.sga : null, type: "neg" },
      { name: "税费", val: inc.tax ? -inc.tax : null, type: "neg" },
      { name: "净利润", val: inc.net_income, type: "sub" },
    ].filter((s) => s.val != null);

    if (!steps.length) {
      chart.clear();
      setPanelEmpty("waterfall", true);
      return;
    }
    setPanelEmpty("waterfall", false);

    let running = 0;
    const placeholders = [];
    const values = [];
    steps.forEach((s) => {
      if (s.type === "pos" || s.type === "sub") {
        placeholders.push(0);
        values.push(s.val);
        running = s.val;
      } else {
        placeholders.push(running + s.val);
        values.push(-s.val);
        running += s.val;
      }
    });

    chart.setOption({
      tooltip: { trigger: "axis" },
      grid: { left: 48, right: 24, bottom: 48, top: 24 },
      xAxis: { type: "category", data: steps.map((s) => s.name) },
      yAxis: { type: "value", name: data.unit === "millions" ? "百万 USD" : data.currency },
      series: [
        { name: "辅助", type: "bar", stack: "w", itemStyle: { borderColor: "transparent", color: "transparent" }, emphasis: { itemStyle: { color: "transparent" } }, data: placeholders },
        { name: "金额", type: "bar", stack: "w", data: values, itemStyle: { color: "#2563eb" } },
      ],
    });
  }

  function renderMarginTrend(data) {
    const chart = initChart("marginTrendChart");
    if (!chart) return;
    const periods = data.periods || [];
    const trends = data.trends || {};
    const hasData = hasAnyValue(trends.gross_margin_pct) || hasAnyValue(trends.net_margin_pct);
    if (!hasData) {
      chart.clear();
      setPanelEmpty("margin_trend", true);
      return;
    }
    setPanelEmpty("margin_trend", false);
    chart.setOption({
      tooltip: { trigger: "axis" },
      legend: { data: ["毛利率", "净利率"] },
      grid: { left: 48, right: 24, bottom: 48, top: 40 },
      xAxis: { type: "category", data: periods },
      yAxis: { type: "value", name: "%", scale: true },
      series: [
        { name: "毛利率", type: "line", data: trends.gross_margin_pct || [], smooth: true },
        { name: "净利率", type: "line", data: trends.net_margin_pct || [], smooth: true },
      ],
    });
  }

  function renderBalance(data) {
    const chart = initChart("balanceChart");
    if (!chart) return;
    const period = data.focus_period;
    const b = (data.balance_sheet && data.balance_sheet[period]) || {};
    const assetParts = [
      { name: "现金", val: b.cash },
      { name: "应收", val: b.receivables },
      { name: "存货", val: b.inventory },
      { name: "固定资产", val: b.ppe },
    ].filter((p) => p.val != null);
    const liabParts = [
      { name: "流动负债", val: b.current_liabilities },
      { name: "长期债务", val: b.long_term_debt },
      { name: "股东权益", val: b.equity },
    ].filter((p) => p.val != null);

    if (!assetParts.length && !liabParts.length) {
      chart.clear();
      setPanelEmpty("balance", true);
      return;
    }
    setPanelEmpty("balance", false);

    chart.setOption({
      tooltip: { trigger: "axis" },
      legend: { type: "scroll" },
      grid: { left: 48, right: 24, bottom: 48, top: 48 },
      xAxis: { type: "category", data: ["资产构成", "负债与权益"] },
      yAxis: { type: "value", name: "百万 USD" },
      series: [
        ...assetParts.map((p, i) => ({
          name: p.name,
          type: "bar",
          stack: "assets",
          data: [p.val, 0],
          itemStyle: { color: ["#10b981", "#34d399", "#6ee7b7", "#059669"][i % 4] },
        })),
        ...liabParts.map((p, i) => ({
          name: p.name,
          type: "bar",
          stack: "liab",
          data: [0, p.val],
          itemStyle: { color: ["#f59e0b", "#fb923c", "#fdba74"][i % 3] },
        })),
      ],
    });
  }

  function renderCashflow(data) {
    const chart = initChart("cashflowChart");
    if (!chart) return;
    const period = data.focus_period;
    const c = (data.cash_flow && data.cash_flow[period]) || {};
    const items = [
      { name: "经营", val: c.operating },
      { name: "投资", val: c.investing },
      { name: "筹资", val: c.financing },
    ].filter((i) => i.val != null);
    if (!items.length) {
      chart.clear();
      setPanelEmpty("cashflow", true);
      return;
    }
    setPanelEmpty("cashflow", false);
    chart.setOption({
      tooltip: { trigger: "axis" },
      grid: { left: 48, right: 24, bottom: 48, top: 24 },
      xAxis: { type: "category", data: items.map((i) => i.name) },
      yAxis: { type: "value", name: "百万 USD" },
      series: [{
        type: "bar",
        data: items.map((i) => ({
          value: i.val,
          itemStyle: { color: i.val >= 0 ? "#059669" : "#dc2626" },
        })),
      }],
    });
  }

  function renderRevenueProfitTrend(data) {
    const chart = initChart("revenueProfitTrendChart");
    if (!chart) return;
    const periods = data.periods || [];
    const derived = data.derived || {};
    const revenue = derived.revenue_series || [];
    const netIncome = derived.net_income_series || [];
    if (!hasAnyValue(revenue) && !hasAnyValue(netIncome)) {
      chart.clear();
      setPanelEmpty("revenue_profit_trend", true);
      return;
    }
    setPanelEmpty("revenue_profit_trend", false);
    chart.setOption({
      tooltip: { trigger: "axis" },
      legend: { data: ["营收", "净利润"] },
      grid: { left: 52, right: 24, bottom: 48, top: 40 },
      xAxis: { type: "category", data: periods },
      yAxis: { type: "value", name: "百万 USD" },
      series: [
        { name: "营收", type: "bar", data: revenue },
        { name: "净利润", type: "line", data: netIncome, smooth: true },
      ],
    });
  }

  function renderExpenseRatioTrend(data) {
    const chart = initChart("expenseRatioTrendChart");
    if (!chart) return;
    const periods = data.periods || [];
    const expense = (data.derived || {}).expense_ratio_trend || {};
    const rd = expense.rd_pct || [];
    const sga = expense.sga_pct || [];
    if (!hasAnyValue(rd) && !hasAnyValue(sga)) {
      chart.clear();
      setPanelEmpty("expense_ratio_trend", true);
      return;
    }
    setPanelEmpty("expense_ratio_trend", false);
    chart.setOption({
      tooltip: { trigger: "axis" },
      legend: { data: ["研发费用率", "销管费用率"] },
      grid: { left: 48, right: 24, bottom: 48, top: 40 },
      xAxis: { type: "category", data: periods },
      yAxis: { type: "value", name: "%", scale: true },
      series: [
        { name: "研发费用率", type: "line", data: rd, smooth: true },
        { name: "销管费用率", type: "line", data: sga, smooth: true },
      ],
    });
  }

  function renderCashflowTrend(data) {
    const chart = initChart("cashflowTrendChart");
    if (!chart) return;
    const periods = data.periods || [];
    const cf = (data.derived || {}).cashflow_series || {};
    const op = cf.operating || [];
    const inv = cf.investing || [];
    const fin = cf.financing || [];
    if (!hasAnyValue(op) && !hasAnyValue(inv) && !hasAnyValue(fin)) {
      chart.clear();
      setPanelEmpty("cashflow_trend", true);
      return;
    }
    setPanelEmpty("cashflow_trend", false);
    chart.setOption({
      tooltip: { trigger: "axis" },
      legend: { data: ["经营", "投资", "筹资"] },
      grid: { left: 52, right: 24, bottom: 48, top: 40 },
      xAxis: { type: "category", data: periods },
      yAxis: { type: "value", name: "百万 USD" },
      series: [
        { name: "经营", type: "bar", data: op },
        { name: "投资", type: "bar", data: inv },
        { name: "筹资", type: "bar", data: fin },
      ],
    });
  }

  function renderAssetMix(data) {
    const chart = initChart("assetMixChart");
    if (!chart) return;
    const mix = (data.derived || {}).asset_mix || [];
    if (!mix.length) {
      chart.clear();
      setPanelEmpty("asset_mix", true);
      return;
    }
    setPanelEmpty("asset_mix", false);
    chart.setOption({
      tooltip: { trigger: "item" },
      legend: { orient: "vertical", left: "left", top: "middle" },
      series: [{
        type: "pie",
        radius: ["40%", "68%"],
        center: ["58%", "50%"],
        data: mix,
        emphasis: { itemStyle: { shadowBlur: 8, shadowOffsetX: 0 } },
      }],
    });
  }

  function renderOcfQuality(data) {
    const chart = initChart("ocfQualityChart");
    if (!chart) return;
    const periods = data.periods || [];
    const ratios = (data.derived || {}).ocf_quality_ratio || [];
    if (!hasAnyValue(ratios)) {
      chart.clear();
      setPanelEmpty("ocf_quality", true);
      return;
    }
    setPanelEmpty("ocf_quality", false);
    chart.setOption({
      tooltip: { trigger: "axis", valueFormatter: (v) => (v == null ? "—" : v.toFixed(2)) },
      grid: { left: 48, right: 24, bottom: 48, top: 32 },
      xAxis: { type: "category", data: periods },
      yAxis: { type: "value", name: "OCF/净利", scale: true },
      series: [{ name: "盈利质量", type: "line", data: ratios, smooth: true, markLine: { data: [{ yAxis: 1, name: "1x" }] } }],
    });
  }

  function renderProfitOcf(data) {
    const chart = initChart("profitOcfChart");
    if (!chart) return;
    const periods = data.periods || [];
    const netProfits = periods.map((p) => {
      const k = data.kpis && data.kpis[p] && data.kpis[p].net_profit;
      if (k && k.value != null) return k.value;
      const inc = data.income_statement && data.income_statement[p];
      return inc ? inc.net_income : null;
    });
    const ocf = periods.map((p) => {
      const c = data.cash_flow && data.cash_flow[p];
      return c ? c.operating : null;
    });
    if (!hasAnyValue(netProfits) && !hasAnyValue(ocf)) {
      chart.clear();
      setPanelEmpty("profit_ocf", true);
      return;
    }
    setPanelEmpty("profit_ocf", false);
    chart.setOption({
      tooltip: { trigger: "axis" },
      legend: { data: ["净利润", "经营现金流"] },
      grid: { left: 48, right: 24, bottom: 48, top: 40 },
      xAxis: { type: "category", data: periods },
      yAxis: { type: "value", name: "百万 USD" },
      series: [
        { name: "净利润", type: "bar", data: netProfits },
        { name: "经营现金流", type: "line", yAxisIndex: 0, data: ocf, smooth: true },
      ],
    });
  }

  function updateMergeHint(data) {
    const el = document.getElementById("mergeHint");
    if (!el) return;
    const count = data.report_count || 0;
    if (count <= 1) {
      el.hidden = true;
      return;
    }
    const periods = (data.linked_periods || data.periods || []).join("、");
    el.hidden = false;
    el.textContent = `本图已合并 ${data.ticker} 下 ${count} 份报告（${periods}）`;
  }

  function renderInsights(data) {
    if (!data) return;
    renderRedFlags(data.red_flags);
    renderMaterialEvents(data.material_events, data.unit);
    if (data.ai_summary) {
      const el = document.querySelector(".research-ai-summary");
      if (el) el.textContent = data.ai_summary;
    }
  }

  function renderChartPanels(data) {
    lastChartPayload = data;
    updateMergeHint(data);
    renderKpis(data);
    renderRevenueProfitTrend(data);
    renderWaterfall(data);
    renderMarginTrend(data);
    renderExpenseRatioTrend(data);
    renderProfitOcf(data);
    renderOcfQuality(data);
    renderBalance(data);
    renderAssetMix(data);
    renderCashflow(data);
    renderCashflowTrend(data);
    applySectionTab(activeSection);
    const dash = document.getElementById("researchDashboard");
    const insightPanel = document.getElementById("dashboardInsightPanel");
    if (dash) dash.hidden = false;
    if (insightPanel) insightPanel.hidden = false;
    if (data.ai_summary) {
      const el = document.querySelector(".research-ai-summary");
      if (el) el.textContent = data.ai_summary;
    }
    resizeVisibleCharts();
  }

  function renderAll(data) {
    renderInsights(data);
    renderChartPanels(data);
  }

  function showConfirmWarnings(warnings) {
    const el = document.getElementById("confirmExtractWarnings");
    if (!el) return;
    if (!warnings || !warnings.length) {
      el.hidden = true;
      el.textContent = "";
      return;
    }
    el.hidden = false;
    el.textContent = warnings.join(" ");
  }

  function checkExtractedWarningsClient(extracted) {
    const warnings = [];
    const summary = (extracted?.ai_summary || "").trim();
    const hasRevenueInSummary = /营收|收入|营业收入|总收入|revenue/i.test(summary);
    let hasStructuredRevenue = false;
    const kpis = extracted?.kpis || {};
    const income = extracted?.income_statement || {};
    [...Object.values(kpis), ...Object.values(income)].forEach((block) => {
      if (!block || typeof block !== "object") return;
      const rev = block.revenue;
      if (rev != null && (typeof rev !== "object" || rev.value != null)) {
        hasStructuredRevenue = true;
      }
    });
    if (hasRevenueInSummary && !hasStructuredRevenue) {
      warnings.push(
        "摘要中提及营收/收入，但 kpis 或 income_statement 未填入营收；确认后图表将无法显示营收，请补全 JSON。"
      );
    }
    return warnings;
  }

  async function loadCharts() {
    const res = await fetch(cfg.chartDataUrl);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "加载图表失败");
    renderInsights(data);
    if (!data.periods?.length) {
      return;
    }
    renderChartPanels(data);
  }

  function insightCacheKey(chartType) {
    return `finHelper:chartInsight:${cfg.reportId}:${chartType}`;
  }

  async function requestChartInsight(chartType, btn) {
    if (!cfg.chartInsightUrl || !cfg.aiConfigured) {
      alert("未配置 AI");
      return;
    }
    const cached = sessionStorage.getItem(insightCacheKey(chartType));
    if (cached) {
      showChartInsight(chartType, cached);
      return;
    }
    if (btn) {
      btn.disabled = true;
      btn.textContent = "解读中…";
    }
    try {
      const res = await fetch(cfg.chartInsightUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chart_type: chartType }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "解读失败");
      const text = data.insight || data.text || "";
      showChartInsight(chartType, text);
      sessionStorage.setItem(insightCacheKey(chartType), text);
    } catch (err) {
      alert(err.message || "AI 解读失败");
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = "AI 解读";
      }
    }
  }

  document.querySelectorAll(".research-insight-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      requestChartInsight(btn.dataset.chartType, btn);
    });
  });

  document.querySelectorAll(".research-section-tab").forEach((tab) => {
    tab.addEventListener("click", () => applySectionTab(tab.dataset.section));
  });

  function dashboardCacheKey() {
    return `finHelper:dashboardInsight:${cfg.reportId}`;
  }

  async function requestDashboardInsight() {
    if (!cfg.dashboardInsightUrl || !cfg.aiConfigured) {
      alert("未配置 AI");
      return;
    }
    const btn = document.getElementById("dashboardInsightBtn");
    const details = document.getElementById("dashboardInsightDetails");
    const body = document.getElementById("dashboardInsightBody");
    const cached = sessionStorage.getItem(dashboardCacheKey());
    if (cached && body) {
      body.textContent = cached;
      if (details) details.hidden = false;
      return;
    }
    if (btn) {
      btn.disabled = true;
      btn.textContent = "解读中…";
    }
    try {
      const res = await fetch(cfg.dashboardInsightUrl, { method: "POST" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "全局解读失败");
      const text = data.insight || "";
      if (body) body.textContent = text;
      if (details) details.hidden = false;
      sessionStorage.setItem(dashboardCacheKey(), text);
    } catch (err) {
      alert(err.message || "全局解读失败");
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = "生成全局解读";
      }
    }
  }

  document.getElementById("dashboardInsightBtn")?.addEventListener("click", requestDashboardInsight);

  const cachedDashboard = sessionStorage.getItem(dashboardCacheKey());
  if (cachedDashboard) {
    const body = document.getElementById("dashboardInsightBody");
    const details = document.getElementById("dashboardInsightDetails");
    if (body) body.textContent = cachedDashboard;
    if (details) details.hidden = false;
  }

  const confirmModal = document.getElementById("confirmAnalysisModal");
  const confirmJson = document.getElementById("confirmExtractedJson");
  const confirmSummary = document.getElementById("confirmAiSummary");

  function openConfirmModal(result) {
    confirmJson.value = JSON.stringify(result.extracted, null, 2);
    confirmSummary.value = result.ai_summary || result.extracted?.ai_summary || "";
    const warnings = result.warnings || checkExtractedWarningsClient(result.extracted);
    showConfirmWarnings(warnings);
    renderInsights({
      red_flags: result.extracted?.red_flags,
      material_events: result.extracted?.material_events,
      unit: result.extracted?.unit,
      ai_summary: confirmSummary.value,
    });
    confirmModal.hidden = false;
  }

  function closeConfirmModal() {
    confirmModal.hidden = true;
    showConfirmWarnings([]);
  }

  document.getElementById("analyzeReportBtn")?.addEventListener("click", async () => {
    const btn = document.getElementById("analyzeReportBtn");
    let startedAsync = false;
    try {
      if (btn) {
        btn.disabled = true;
        btn.textContent = "分析中…";
      }
      const res = await fetch(cfg.analyzeUrl, { method: "POST" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "分析失败");
      if (data.status === "ok" && data.report_id) {
        startedAsync = true;
        startParsePolling();
        return;
      }
      if (data.extracted) {
        openConfirmModal(data);
      }
    } catch (err) {
      alert(err.message || "AI 分析失败");
    } finally {
      if (!startedAsync && btn) {
        btn.disabled = false;
        btn.textContent = cfg.hasAnalysis ? "重新 AI 分析" : "AI 分析";
      }
    }
  });

  document.getElementById("openPendingConfirmBtn")?.addEventListener("click", () => {
    openPendingConfirm().catch(() => {});
  });

  document.getElementById("closeConfirmModal")?.addEventListener("click", closeConfirmModal);
  document.getElementById("cancelConfirm")?.addEventListener("click", closeConfirmModal);

  document.getElementById("saveConfirm")?.addEventListener("click", async () => {
    let extracted;
    try {
      extracted = JSON.parse(confirmJson.value);
    } catch (e) {
      alert("JSON 格式无效");
      return;
    }
    const clientWarnings = checkExtractedWarningsClient({
      ...extracted,
      ai_summary: confirmSummary.value,
    });
    if (clientWarnings.length && !window.confirm(`${clientWarnings.join("\n")}\n\n仍要确认入库吗？`)) {
      return;
    }
    try {
      const res = await fetch(cfg.confirmUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          extracted,
          ai_summary: confirmSummary.value,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "保存失败");
      closeConfirmModal();
      window.location.reload();
    } catch (err) {
      alert(err.message || "保存失败");
    }
  });

  document.getElementById("refreshChartsBtn")?.addEventListener("click", async () => {
    try {
      await loadCharts();
    } catch (err) {
      alert(err.message || "刷新失败");
    }
  });

  document.getElementById("reparsePdfBtn")?.addEventListener("click", async () => {
    if (!cfg.parsePdfUrl) return;
    if (!window.confirm("重新解析将覆盖当前待确认结果，是否继续？")) return;
    try {
      const res = await fetch(cfg.parsePdfUrl, { method: "POST" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "启动失败");
      startParsePolling();
    } catch (err) {
      alert(err.message || "启动解析失败");
    }
  });

  function setParseUi(status, options = {}) {
    const hasPending = !!options.hasPending;
    const panel = document.getElementById("parseProgressPanel");
    const bar = document.getElementById("parseProgressBar");
    const label = document.getElementById("parseProgressLabel");
    const errEl = document.getElementById("parseErrorText");
    const openPendingBtn = document.getElementById("openPendingConfirmBtn");
    const busy = status === "extracting_text" || status === "ai_analyzing";
    if (panel) {
      panel.hidden =
        !busy && status !== "failed" && !(status === "done" && hasPending);
    }
    if (openPendingBtn) openPendingBtn.hidden = !hasPending;
    if (bar && options.progress != null) bar.value = options.progress;
    if (label && options.message) label.textContent = options.message;
    if (errEl) {
      if (options.error) {
        errEl.hidden = false;
        errEl.textContent = options.error;
      } else {
        errEl.hidden = true;
      }
    }
    ["analyzeReportBtn", "refreshChartsBtn"].forEach((id) => {
      const btn = document.getElementById(id);
      if (btn) btn.disabled = busy;
    });
  }

  async function openPendingConfirm() {
    if (!cfg.pendingUrl) return;
    try {
      const res = await fetch(cfg.pendingUrl);
      const data = await res.json();
      if (!res.ok) return;
      openConfirmModal({
        extracted: data.extracted,
        ai_summary: data.ai_summary,
        warnings: data.warnings,
      });
    } catch (err) {
      console.warn(err);
    }
  }

  async function pollParseStatus() {
    if (!cfg.parseStatusUrl) return;
    try {
      const res = await fetch(cfg.parseStatusUrl);
      const data = await res.json();
      if (!res.ok) return;
      setParseUi(data.status, {
        hasPending: data.has_pending,
        progress: data.progress,
        message: data.message,
        error: data.error,
      });
      const bar = document.getElementById("parseProgressBar");
      if (bar && data.progress != null) bar.value = data.progress;

      if (data.status === "done" && data.has_pending) {
        if (parsePollTimer) {
          clearInterval(parsePollTimer);
          parsePollTimer = null;
        }
        await openPendingConfirm();
        return;
      }
      if (data.status === "failed") {
        if (parsePollTimer) {
          clearInterval(parsePollTimer);
          parsePollTimer = null;
        }
      }
    } catch (err) {
      console.warn(err);
    }
  }

  function startParsePolling() {
    const panel = document.getElementById("parseProgressPanel");
    if (panel) panel.hidden = false;
    pollParseStatus();
    if (parsePollTimer) clearInterval(parsePollTimer);
    parsePollTimer = setInterval(pollParseStatus, 1000);
  }

  window.addEventListener("resize", () => resizeVisibleCharts());

  if (cfg.initialInsights) {
    renderInsights(cfg.initialInsights);
  }

  if (cfg.hasAnalysis) {
    loadCharts().catch((err) => {
      console.warn(err);
      if (cfg.initialInsights) renderInsights(cfg.initialInsights);
    });
  }

  const activeParse =
    cfg.parseStatus === "extracting_text" || cfg.parseStatus === "ai_analyzing";
  if (activeParse) {
    startParsePolling();
  } else if (cfg.parseStatus === "done" && cfg.hasPending) {
    setParseUi("done", { hasPending: true, message: "分析完成，请确认结构化结果" });
    openPendingConfirm().catch(() => {});
  }
})();
