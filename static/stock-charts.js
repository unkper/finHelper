(function () {
  const chartInstances = new Map();
  const INDICATOR_STORAGE_KEY = "finhelper-chart-indicators";
  let allAssets = [];

  const defaultIndicators = {
    ma5: true,
    ma10: true,
    ma20: true,
    macd: false,
    rsi: false,
  };

  function loadIndicatorSettings() {
    try {
      const raw = localStorage.getItem(INDICATOR_STORAGE_KEY);
      if (!raw) return { ...defaultIndicators };
      return { ...defaultIndicators, ...JSON.parse(raw) };
    } catch (e) {
      return { ...defaultIndicators };
    }
  }

  let indicatorSettings = loadIndicatorSettings();

  function saveIndicatorSettings() {
    localStorage.setItem(INDICATOR_STORAGE_KEY, JSON.stringify(indicatorSettings));
  }

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

  function sma(values, period) {
    const out = [];
    for (let i = 0; i < values.length; i += 1) {
      if (i < period - 1) {
        out.push(null);
        continue;
      }
      let sum = 0;
      for (let j = i - period + 1; j <= i; j += 1) {
        sum += values[j];
      }
      out.push(sum / period);
    }
    return out;
  }

  function ema(values, period) {
    const out = [];
    const multiplier = 2 / (period + 1);
    let prev = null;
    for (let i = 0; i < values.length; i += 1) {
      const value = values[i];
      if (value === null || value === undefined || Number.isNaN(value)) {
        out.push(null);
        continue;
      }
      if (prev === null) {
        if (i < period - 1) {
          out.push(null);
          continue;
        }
        let sum = 0;
        for (let j = i - period + 1; j <= i; j += 1) {
          sum += values[j];
        }
        prev = sum / period;
        out.push(prev);
        continue;
      }
      prev = value * multiplier + prev * (1 - multiplier);
      out.push(prev);
    }
    return out;
  }

  function calcMacd(closes, fastPeriod, slowPeriod, signalPeriod) {
    const emaFast = ema(closes, fastPeriod);
    const emaSlow = ema(closes, slowPeriod);
    const macdLine = emaFast.map((fast, i) => {
      const slow = emaSlow[i];
      if (fast == null || slow == null) return null;
      return fast - slow;
    });
    const validMacd = macdLine.map((v) => (v == null ? 0 : v));
    const signalLine = ema(validMacd, signalPeriod).map((v, i) => (
      macdLine[i] == null ? null : v
    ));
    const histogram = macdLine.map((macd, i) => {
      const signal = signalLine[i];
      if (macd == null || signal == null) return null;
      return macd - signal;
    });
    return { macdLine, signalLine, histogram };
  }

  function calcRsi(closes, period) {
    const out = [];
    if (closes.length < period + 1) {
      return closes.map(() => null);
    }
    for (let i = 0; i < closes.length; i += 1) {
      if (i < period) {
        out.push(null);
        continue;
      }
      let gains = 0;
      let losses = 0;
      for (let j = i - period + 1; j <= i; j += 1) {
        const change = closes[j] - closes[j - 1];
        if (change >= 0) gains += change;
        else losses -= change;
      }
      if (losses === 0) {
        out.push(100);
      } else {
        const rs = gains / losses;
        out.push(100 - 100 / (1 + rs));
      }
    }
    return out;
  }

  function extractSeriesData(asset) {
    const series = asset.series || [];
    const dates = series.map((p) => p.date);
    const closes = series.map((p) => Number(p.close));
    const ohlc = series.map((p) => [
      Number(p.open),
      Number(p.close),
      Number(p.low),
      Number(p.high),
    ]);
    const hasOhlc = asset.chart_type === "candlestick";
    return { dates, closes, ohlc, hasOhlc };
  }

  function buildChartLayout(settings) {
    const showMacd = settings.macd;
    const showRsi = settings.rsi;
    const grids = [{ left: 52, right: 20, top: 28, height: showMacd || showRsi ? "52%" : "72%" }];
    const xAxes = [{ type: "category", gridIndex: 0, boundaryGap: true, axisLabel: { color: "#75614d" } }];
    const yAxes = [{
      gridIndex: 0,
      scale: true,
      axisLabel: { color: "#75614d", formatter: (v) => "$" + v },
      splitLine: { lineStyle: { color: "rgba(47,36,25,0.08)" } },
    }];
    let gridIndex = 1;
    if (showMacd) {
      grids.push({ left: 52, right: 20, top: "68%", height: "14%" });
      xAxes.push({ type: "category", gridIndex, boundaryGap: true, axisLabel: { show: false } });
      yAxes.push({
        gridIndex,
        scale: true,
        splitNumber: 3,
        axisLabel: { color: "#75614d", fontSize: 10 },
        splitLine: { lineStyle: { color: "rgba(47,36,25,0.06)" } },
      });
      gridIndex += 1;
    }
    if (showRsi) {
      const top = showMacd ? "85%" : "72%";
      const height = showMacd ? "11%" : "18%";
      grids.push({ left: 52, right: 20, top, height });
      xAxes.push({ type: "category", gridIndex, boundaryGap: true, axisLabel: { show: false } });
      yAxes.push({
        gridIndex,
        min: 0,
        max: 100,
        splitNumber: 2,
        axisLabel: { color: "#75614d", fontSize: 10 },
        splitLine: { lineStyle: { color: "rgba(47,36,25,0.06)" } },
      });
    }
    return { grids, xAxes, yAxes, showMacd, showRsi };
  }

  function buildChartOption(asset) {
    const settings = indicatorSettings;
    const { dates, closes, ohlc, hasOhlc } = extractSeriesData(asset);
    const layout = buildChartLayout(settings);
    const dataZoom = [
      { type: "inside", xAxisIndex: layout.xAxes.map((_, i) => i), start: 55, end: 100 },
      { type: "slider", xAxisIndex: layout.xAxes.map((_, i) => i), height: 18, bottom: 6, start: 55, end: 100 },
    ];

    layout.xAxes.forEach((axis) => {
      axis.data = dates;
    });

    const series = [];
    const markLineData = buildMarkLines(asset.alerts);

    if (hasOhlc) {
      series.push({
        name: asset.ticker,
        type: "candlestick",
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: ohlc,
        itemStyle: {
          color: "#d76636",
          color0: "#1f6f5f",
          borderColor: "#d76636",
          borderColor0: "#1f6f5f",
        },
        markLine: markLineData.length ? { symbol: "none", data: markLineData } : undefined,
      });
    } else {
      series.push({
        name: asset.ticker,
        type: "line",
        xAxisIndex: 0,
        yAxisIndex: 0,
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
        markLine: markLineData.length ? { symbol: "none", data: markLineData } : undefined,
      });
    }

    const maColors = { ma5: "#3957b8", ma10: "#d76636", ma20: "#8c6b4f" };
    const maPeriods = { ma5: 5, ma10: 10, ma20: 20 };
    Object.keys(maPeriods).forEach((key) => {
      if (!settings[key]) return;
      series.push({
        name: key.toUpperCase(),
        type: "line",
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: sma(closes, maPeriods[key]),
        smooth: true,
        symbol: "none",
        lineStyle: { width: 1.2, color: maColors[key] },
      });
    });

    let subAxisIndex = 1;
    if (layout.showMacd) {
      const { macdLine, signalLine, histogram } = calcMacd(closes, 12, 26, 9);
      series.push({
        name: "MACD",
        type: "bar",
        xAxisIndex: subAxisIndex,
        yAxisIndex: subAxisIndex,
        data: histogram,
        itemStyle: {
          color: (params) => (params.data >= 0 ? "rgba(215,102,54,0.65)" : "rgba(31,111,95,0.65)"),
        },
      });
      series.push({
        name: "DIF",
        type: "line",
        xAxisIndex: subAxisIndex,
        yAxisIndex: subAxisIndex,
        data: macdLine,
        symbol: "none",
        lineStyle: { width: 1, color: "#3957b8" },
      });
      series.push({
        name: "DEA",
        type: "line",
        xAxisIndex: subAxisIndex,
        yAxisIndex: subAxisIndex,
        data: signalLine,
        symbol: "none",
        lineStyle: { width: 1, color: "#d76636" },
      });
      subAxisIndex += 1;
    }

    if (layout.showRsi) {
      series.push({
        name: "RSI",
        type: "line",
        xAxisIndex: subAxisIndex,
        yAxisIndex: subAxisIndex,
        data: calcRsi(closes, 14),
        symbol: "none",
        lineStyle: { width: 1.2, color: "#8c6b4f" },
        markLine: {
          symbol: "none",
          data: [
            { yAxis: 70, lineStyle: { type: "dashed", color: "#d76636", opacity: 0.5 } },
            { yAxis: 30, lineStyle: { type: "dashed", color: "#1f6f5f", opacity: 0.5 } },
          ],
        },
      });
    }

    return {
      animation: false,
      legend: {
        top: 4,
        right: 8,
        textStyle: { color: "#75614d", fontSize: 11 },
      },
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "cross" },
        formatter(params) {
          if (!params || !params.length) return "";
          const date = params[0].axisValue;
          const lines = [`<strong>${date}</strong>`];
          params.forEach((item) => {
            if (item.seriesType === "candlestick" && Array.isArray(item.data)) {
              const [open, close, low, high] = item.data;
              lines.push(
                `开 $${open.toFixed(2)} 高 $${high.toFixed(2)}`,
                `低 $${low.toFixed(2)} 收 $${close.toFixed(2)}`
              );
            } else if (item.data != null && item.seriesName !== "MACD") {
              const val = Number(item.data);
              const prefix = item.seriesName === "RSI" ? "" : "$";
              const suffix = item.seriesName === "RSI" ? "" : "";
              lines.push(`${item.seriesName}: ${prefix}${val.toFixed(2)}${suffix}`);
            }
          });
          return lines.join("<br/>");
        },
      },
      grid: layout.grids,
      dataZoom,
      xAxis: layout.xAxes,
      yAxis: layout.yAxes,
      series,
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
    const chartTypeNote = asset.chart_type === "candlestick"
      ? '<span class="chart-type-tag">日K蜡烛图</span>'
      : '<span class="chart-type-tag muted">收盘价折线</span>';

    const chartBlock = hasSeries
      ? `<div id="chart-${asset.ticker}" class="stock-chart-canvas"></div>`
      : `<p class="stock-chart-empty-note">${asset.exchange === "US" ? "暂无历史行情数据" : "暂仅支持美股历史走势"}</p>`;

    card.innerHTML = `
      <div class="stock-chart-head">
        <div>
          <h3 class="stock-chart-title">${asset.ticker} ${chartTypeNote}</h3>
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

    const chartHeight = indicatorSettings.macd || indicatorSettings.rsi ? 360 : 300;
    dom.style.height = `${chartHeight}px`;

    const chart = echarts.init(dom);
    chart.setOption(buildChartOption(asset), true);
    chartInstances.set(asset.ticker, chart);
  }

  function remountAllCharts() {
    allAssets.forEach((asset) => mountChart(asset));
  }

  function syncIndicatorToolbar() {
    document.querySelectorAll("[data-indicator]").forEach((input) => {
      const key = input.dataset.indicator;
      if (key in indicatorSettings) {
        input.checked = indicatorSettings[key];
      }
    });
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
    const chartModeHint = document.getElementById("chartModeHint");

    chartInstances.forEach((chart) => chart.dispose());
    chartInstances.clear();
    grid.innerHTML = "";

    loading.hidden = true;

    if (!payload.assets || !payload.assets.length) {
      empty.hidden = false;
      grid.hidden = true;
      summaryTicker.textContent = "0";
      summaryLinks.textContent = "0";
      if (chartModeHint) chartModeHint.textContent = "";
      return;
    }

    empty.hidden = true;
    grid.hidden = false;
    allAssets = payload.assets;

    summaryTicker.textContent = String(payload.summary.ticker_count || payload.assets.length);
    summaryLinks.textContent = String(payload.summary.theme_link_count || 0);

    const candleCount = payload.assets.filter((a) => a.chart_type === "candlestick").length;
    if (chartModeHint) {
      if (payload.summary.eodhd_configured && candleCount > 0) {
        chartModeHint.textContent = `${candleCount} 个标的使用 EODHD 日K蜡烛图，其余为折线`;
      } else if (payload.summary.eodhd_configured) {
        chartModeHint.textContent = "已配置 EODHD，刷新后可获取 OHLC 蜡烛图数据";
      } else {
        chartModeHint.textContent = "未配置 EODHD，仅显示收盘价折线";
      }
    }

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

    syncIndicatorToolbar();

    document.querySelectorAll("[data-indicator]").forEach((input) => {
      input.addEventListener("change", () => {
        const key = input.dataset.indicator;
        indicatorSettings[key] = input.checked;
        saveIndicatorSettings();
        remountAllCharts();
      });
    });

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
