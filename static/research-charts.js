(function () {
  const cfg = window.FINANCIAL_REPORT_PAGE || {};
  const charts = {};
  let lastChartPayload = null;
  let parsePollTimer = null;

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

  function initChart(id) {
    const el = document.getElementById(id);
    if (!el || !window.echarts) return null;
    if (charts[id]) charts[id].dispose();
    charts[id] = echarts.init(el);
    return charts[id];
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
      return;
    }

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
      return;
    }

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

  function renderAll(data) {
    lastChartPayload = data;
    updateMergeHint(data);
    renderKpis(data);
    renderRedFlags(data.red_flags);
    renderWaterfall(data);
    renderMarginTrend(data);
    renderBalance(data);
    renderCashflow(data);
    renderProfitOcf(data);
    if (data.ai_summary) {
      const el = document.querySelector(".research-ai-summary");
      if (el) el.textContent = data.ai_summary;
    }
  }

  async function loadCharts() {
    const res = await fetch(cfg.chartDataUrl);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "加载图表失败");
    if (!data.periods?.length) return;
    renderAll(data);
  }

  function insightCacheKey(chartType) {
    return `finHelper:chartInsight:${cfg.reportId}:${chartType}`;
  }

  async function requestChartInsight(chartType, btn) {
    if (!cfg.chartInsightUrl || !cfg.aiConfigured) {
      alert("未配置 AI");
      return;
    }
    const panel = document.querySelector(`[data-insight-for="${chartType}"]`);
    const cached = sessionStorage.getItem(insightCacheKey(chartType));
    if (cached && panel) {
      panel.hidden = false;
      panel.textContent = cached;
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
      if (panel) {
        panel.hidden = false;
        panel.textContent = text;
      }
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

  const confirmModal = document.getElementById("confirmAnalysisModal");
  const confirmJson = document.getElementById("confirmExtractedJson");
  const confirmSummary = document.getElementById("confirmAiSummary");

  function openConfirmModal(result) {
    confirmJson.value = JSON.stringify(result.extracted, null, 2);
    confirmSummary.value = result.ai_summary || result.extracted?.ai_summary || "";
    confirmModal.hidden = false;
  }

  function closeConfirmModal() {
    confirmModal.hidden = true;
  }

  document.getElementById("analyzeReportBtn")?.addEventListener("click", async () => {
    try {
      const res = await fetch(cfg.analyzeUrl, { method: "POST" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "分析失败");
      openConfirmModal(data);
    } catch (err) {
      alert(err.message || "AI 分析失败");
    }
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

  function setParseUi(status) {
    const panel = document.getElementById("parseProgressPanel");
    const bar = document.getElementById("parseProgressBar");
    const label = document.getElementById("parseProgressLabel");
    const errEl = document.getElementById("parseErrorText");
    const busy = status === "extracting_text" || status === "ai_analyzing";
    if (panel) panel.hidden = !busy && status !== "failed" && status !== "done";
    if (bar && status?.progress != null) bar.value = status.progress;
    if (label && status?.message) label.textContent = status.message;
    if (errEl) {
      if (status?.error) {
        errEl.hidden = false;
        errEl.textContent = status.error;
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
      openConfirmModal({ extracted: data.extracted, ai_summary: data.ai_summary });
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
      setParseUi({
        status: data.status,
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

  window.addEventListener("resize", () => {
    Object.values(charts).forEach((c) => c && c.resize());
  });

  if (cfg.hasAnalysis) {
    loadCharts().catch((err) => console.warn(err));
  }

  const activeParse =
    cfg.parseStatus === "extracting_text" || cfg.parseStatus === "ai_analyzing";
  if (activeParse) {
    startParsePolling();
  } else if (cfg.parseStatus === "done" && cfg.hasPending) {
    openPendingConfirm().catch(() => {});
  }
})();
