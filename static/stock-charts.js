(function () {
  const chartInstances = new Map();
  let allAssets = [];

  function formatPrice(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) {
      return "--";
    }
    return "$" + Number(value).toFixed(2);
  }

  function formatChange(changePct) {
    if (changePct === null || changePct === undefined) {
      return '<span class="change-flat">--</span>';
    }
    const cls = changePct >= 0 ? "change-up" : "change-down";
    const sign = changePct >= 0 ? "+" : "";
    return `<span class="${cls}">${sign}${changePct}%</span>`;
  }

  function uniqueThemeLabels(themes) {
    const seen = new Set();
  return themes.filter((theme) => {
      const label = `${theme.theme_title} · ${theme.assistant_name}`;
      if (seen.has(label)) return false;
      seen.add(label);
      return true;
    }).map((theme) => `${theme.theme_title} · ${theme.assistant_name}`);
  }

  function buildMarkLines(alerts) {
    return (alerts || []).map((alert) => ({
      yAxis: alert.target_price,
      label: {
        formatter: `${alert.direction === "above" ? "涨至" : "跌至"} $${Number(alert.target_price).toFixed(2)}`,
        color: alert.direction === "above" ? "#d76636" : "#1f6f5f",
      },
      lineStyle: {
        type: "dashed",
        color: alert.direction === "above" ? "#d76636" : "#1f6f5f",
      },
    }));
  }

  function buildChartOption(asset) {
    const dates = (asset.series || []).map((point) => point.date);
    const closes = (asset.series || []).map((point) => point.close);

    return {
      tooltip: {
        trigger: "axis",
        formatter(params) {
          const item = params[0];
          if (!item) return "";
          return `${item.axisValue}<br/>收盘: $${Number(item.data).toFixed(2)}`;
        },
      },
      grid: { left: 48, right: 18, top: 24, bottom: 56 },
      dataZoom: [
        { type: "inside", start: 60, end: 100 },
        { type: "slider", height: 18, bottom: 8, start: 60, end: 100 },
      ],
      xAxis: {
        type: "category",
        data: dates,
        boundaryGap: false,
        axisLabel: { color: "#75614d" },
      },
      yAxis: {
        type: "value",
        scale: true,
        axisLabel: {
          color: "#75614d",
          formatter: (value) => "$" + value,
        },
        splitLine: { lineStyle: { color: "rgba(47,36,25,0.08)" } },
      },
      series: [{
        name: asset.ticker,
        type: "line",
        smooth: true,
        symbol: "none",
        data: closes,
        lineStyle: { width: 2, color: "#1f6f5f" },
        areaStyle: {
          color: {
            type: "linear",
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: "rgba(31,111,95,0.28)" },
              { offset: 1, color: "rgba(31,111,95,0.02)" },
            ],
          },
        },
        markLine: {
          symbol: "none",
          data: buildMarkLines(asset.alerts),
        },
      }],
    };
  }

  function renderCard(asset) {
    const card = document.createElement("article");
    card.className = "stock-chart-card";
    card.dataset.ticker = asset.ticker;

    const themeTags = uniqueThemeLabels(asset.themes || [])
      .map((label) => `<span class="theme-tag">${label}</span>`)
      .join("");

    const alertTags = (asset.alerts || [])
      .map((alert) => {
        const dir = alert.direction === "above" ? "above" : "below";
        const dirLabel = alert.direction === "above" ? "涨至" : "跌至";
        const note = alert.note ? ` · ${alert.note}` : "";
        return `<span class="alert-tag ${dir}">${dirLabel} $${Number(alert.target_price).toFixed(2)}${note}</span>`;
      })
      .join("");

    const hasSeries = asset.series && asset.series.length > 0;
    const chartBlock = hasSeries
      ? `<div id="chart-${asset.ticker}" class="stock-chart-canvas"></div>`
      : `<p class="stock-chart-empty-note">${asset.exchange === "US" ? "暂无历史行情数据" : "暂仅支持美股历史走势"}</p>`;

    card.innerHTML = `
      <div class="stock-chart-head">
        <div>
          <h3 class="stock-chart-title">${asset.ticker}</h3>
          <p class="stock-chart-meta">${asset.exchange} · 关联 ${(asset.themes || []).length} 个主题</p>
        </div>
        <div class="stock-chart-price">
          <strong>${formatPrice(asset.current_price)}</strong>
          ${formatChange(asset.change_pct)}
        </div>
      </div>
      <div class="stock-theme-tags">${themeTags}</div>
      ${alertTags ? `<div class="stock-alert-tags">${alertTags}</div>` : ""}
      ${chartBlock}
    `;

    return card;
  }

  function mountChart(asset) {
    if (!asset.series || !asset.series.length || typeof echarts === "undefined") {
      return;
    }
    const dom = document.getElementById(`chart-${asset.ticker}`);
    if (!dom) return;

    const existing = chartInstances.get(asset.ticker);
    if (existing) {
      existing.dispose();
    }

    const chart = echarts.init(dom);
    chart.setOption(buildChartOption(asset));
    chartInstances.set(asset.ticker, chart);
  }

  function applyFilter(keyword) {
    const value = (keyword || "").trim().toUpperCase();
    document.querySelectorAll(".stock-chart-card").forEach((card) => {
      const ticker = card.dataset.ticker || "";
      card.classList.toggle("is-hidden", value && !ticker.includes(value));
    });
  }

  function renderAssets(payload) {
    const grid = document.getElementById("stocksGrid");
    const loading = document.getElementById("stocksLoading");
    const empty = document.getElementById("stocksEmpty");
    const summaryTicker = document.getElementById("summaryTickerCount");
    const summaryLinks = document.getElementById("summaryThemeLinks");

    chartInstances.forEach((chart) => chart.dispose());
    chartInstances.clear();
    grid.innerHTML = "";

    loading.hidden = true;

    if (!payload.assets || !payload.assets.length) {
      empty.hidden = false;
      grid.hidden = true;
      summaryTicker.textContent = "0";
      summaryLinks.textContent = "0";
      return;
    }

    empty.hidden = true;
    grid.hidden = false;
    allAssets = payload.assets;

    summaryTicker.textContent = String(payload.summary.ticker_count || payload.assets.length);
    summaryLinks.textContent = String(payload.summary.theme_link_count || 0);

    payload.assets.forEach((asset) => {
      grid.appendChild(renderCard(asset));
    });

    payload.assets.forEach((asset) => mountChart(asset));
    applyFilter(document.getElementById("tickerFilter")?.value || "");
  }

  async function loadChartData(forceRefresh) {
    const loading = document.getElementById("stocksLoading");
    const grid = document.getElementById("stocksGrid");
    const empty = document.getElementById("stocksEmpty");

    loading.hidden = false;
    grid.hidden = true;
    empty.hidden = true;

    const url = forceRefresh
      ? "/investments/stocks/api/chart-data?refresh=1"
      : "/investments/stocks/api/chart-data";

    try {
      const response = await fetch(url);
      if (!response.ok) throw new Error("加载失败");
      const payload = await response.json();
      renderAssets(payload);
    } catch (error) {
      loading.hidden = true;
      empty.hidden = false;
      empty.querySelector("p").textContent = "加载失败，请稍后重试。";
      console.error(error);
    }
  }

  function handleResize() {
    chartInstances.forEach((chart) => chart.resize());
  }

  document.addEventListener("DOMContentLoaded", () => {
    if (!document.querySelector(".stocks-page")) return;

    loadChartData(false);

    document.getElementById("refreshChartsBtn")?.addEventListener("click", () => {
      loadChartData(true);
    });

    document.getElementById("tickerFilter")?.addEventListener("input", (event) => {
      applyFilter(event.target.value);
    });

    window.addEventListener("resize", handleResize);
  });
})();
