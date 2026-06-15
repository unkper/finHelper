(function () {
  const cfg = window.SETTINGS_PAGE || {};
  const CHART_ID = "apiUsageChart";

  const CHART_COLORS = {
    eodhd: "#0052cc",
    alpha_vantage: "#36b37e",
    fmp: "#ff5630",
    deepseek: "#6554c0",
  };

  function $(id) {
    return document.getElementById(id);
  }

  function setStatus(text, isError) {
    const el = $("apiUsageStatus");
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

  function renderSummary(data) {
    const todayEl = $("apiUsageTodayTotal");
    const periodEl = $("apiUsagePeriodTotal");
    if (todayEl) todayEl.textContent = String(data.today_total ?? 0);
    if (periodEl) periodEl.textContent = String(data.period_total ?? 0);
    const periodLabel = $("apiUsagePeriodLabel");
    if (periodLabel) periodLabel.textContent = data.all_time ? "累计合计" : "区间合计";

    const totalsWrap = $("apiUsageProviderTotals");
    if (!totalsWrap) return;
    totalsWrap.innerHTML = "";
    const labels = data.provider_labels || {};
    (data.providers || []).forEach((provider) => {
      const pill = document.createElement("span");
      pill.className = "api-usage-provider-pill";
      const count = (data.totals || {})[provider] ?? 0;
      pill.innerHTML = `${labels[provider] || provider}<strong>${count}</strong>`;
      totalsWrap.appendChild(pill);
    });
  }

  function renderChart(data) {
    if (!window.FinChart) return;
    const labels = data.provider_labels || {};
    const series = (data.providers || []).map((provider) => ({
      name: labels[provider] || provider,
      color: CHART_COLORS[provider],
      data: (data.series || {})[provider] || [],
    }));

    const option = FinChart.stackedBarOption({
      categories: data.dates || [],
      series,
      yAxisName: "调用次数",
      categoryLabelFormatter(value) {
        const text = String(value || "");
        if (data.all_time && text.length > 7) return text.slice(2, 7);
        return text.slice(5);
      },
    });

    FinChart.mount(CHART_ID, option);
  }

  async function loadUsageStats() {
    if (!cfg.usageStatsUrl) return;
    const days = cfg.defaultDays ?? 30;
    setStatus("加载中…", false);
    try {
      const res = await fetch(`${cfg.usageStatsUrl}?days=${encodeURIComponent(days)}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "加载失败");
      renderSummary(data);
      renderChart(data);
      setStatus("", false);
    } catch (error) {
      setStatus(error.message || "加载失败", true);
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    if (cfg.activeTab !== "api-usage") return;
    loadUsageStats();
    window.addEventListener("resize", () => FinChart?.resize(CHART_ID));
  });
})();
