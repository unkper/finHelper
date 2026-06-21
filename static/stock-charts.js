(function () {
  const chartInstances = new Map();
  const INDICATOR_STORAGE_KEY = "finhelper-chart-indicators";
  const PER_PAGE_STORAGE_KEY = "finhelper-stocks-per-page";
  const DEFAULT_PER_PAGE = 8;
  let allAssets = [];
  let currentPage = 1;
  let perPage = DEFAULT_PER_PAGE;
  let filterDebounceTimer = null;

  const defaultIndicators = {
    ma5: true,
    ma10: true,
    ma20: true,
    macd: false,
    rsi6: false,
    rsi12: false,
    rsi24: false,
  };

  function hasAnyRsi(settings) {
    return settings.rsi6 || settings.rsi12 || settings.rsi24;
  }

  function loadIndicatorSettings() {
    try {
      const raw = localStorage.getItem(INDICATOR_STORAGE_KEY);
      if (!raw) return { ...defaultIndicators };
      const parsed = JSON.parse(raw);
      if (parsed.rsi === true) {
        parsed.rsi6 = parsed.rsi6 ?? true;
        parsed.rsi12 = parsed.rsi12 ?? true;
        parsed.rsi24 = parsed.rsi24 ?? true;
      }
      delete parsed.rsi;
      return { ...defaultIndicators, ...parsed };
    } catch (e) {
      return { ...defaultIndicators };
    }
  }

  let indicatorSettings = loadIndicatorSettings();

  function buildMacdSignalTags(macd) {
    if (!macd || !macd.ready) return "";
    const labels = macd.signal_labels || [];
    if (!labels.length) return "";
    const dateNote = macd.bar_date ? ` · ${macd.bar_date}` : "";
    return labels.map((item) => {
      const cls = item.type === "golden_cross_above_zero" ? "golden" : "death";
      return `<span class="macd-signal-tag ${cls}">${item.label}${dateNote}</span>`;
    }).join("");
  }

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
    if (changePct === null || changePct === undefined || Number.isNaN(Number(changePct))) {
      return '<span class="change-flat">--</span>';
    }
    const cls = changePct >= 0 ? "change-up" : "change-down";
    const sign = changePct >= 0 ? "+" : "";
    return `<span class="${cls}">${sign}${Number(changePct).toFixed(2)}%</span>`;
  }

  function calcDailyChangePct(points, index) {
    if (!points || index < 1 || index >= points.length) return null;
    const prev = Number(points[index - 1].close);
    const cur = Number(points[index].close);
    if (!prev || Number.isNaN(prev) || Number.isNaN(cur)) return null;
    return Math.round((cur - prev) / prev * 10000) / 100;
  }

  function calcPeriodChangePct(points, startIdx, endIdx) {
    if (!points || !points.length) return null;
    let start = Math.max(0, startIdx);
    let end = Math.min(points.length - 1, endIdx);
    if (start > end) {
      const tmp = start;
      start = end;
      end = tmp;
    }
    const first = Number(points[start].close);
    const last = Number(points[end].close);
    if (!first || Number.isNaN(first) || Number.isNaN(last)) return null;
    return Math.round((last - first) / first * 10000) / 100;
  }

  function visibleIndexRange(dataLen, startPercent, endPercent) {
    if (dataLen <= 0) return { start: 0, end: 0 };
    if (dataLen === 1) return { start: 0, end: 0 };
    const start = Math.max(0, Math.floor((startPercent / 100) * (dataLen - 1)));
    const end = Math.min(dataLen - 1, Math.ceil((endPercent / 100) * (dataLen - 1)));
    return { start, end };
  }

  function isDefaultChartZoom(startPercent, endPercent) {
    return startPercent >= 54 && endPercent >= 99;
  }

  function getChartDataZoomRange(chart) {
    const opt = chart.getOption();
    const zoomList = opt.dataZoom || [];
    let start = 55;
    let end = 100;
    zoomList.forEach((z) => {
      if (z.start != null && z.end != null) {
        start = z.start;
        end = z.end;
      }
    });
    return { start, end };
  }

  function updateCardChangeDisplay(card, asset, chart) {
    const points = asset.series || [];
    const changeEl = card.querySelector(".stock-chart-change");
    const labelEl = card.querySelector(".stock-chart-change-label");
    if (!changeEl) return;

    let label = "日涨跌";
    let pct = asset.change_pct;

    if (chart && points.length > 1) {
      const { start, end } = getChartDataZoomRange(chart);
      const range = visibleIndexRange(points.length, start, end);
      if (!isDefaultChartZoom(start, end)) {
        const dayCount = range.end - range.start + 1;
        label = dayCount <= 1 ? "日涨跌" : `区间 ${dayCount} 日`;
        pct = calcPeriodChangePct(points, range.start, range.end);
      } else {
        pct = calcDailyChangePct(points, points.length - 1);
      }
    } else if (points.length > 1) {
      pct = calcDailyChangePct(points, points.length - 1);
    }

    if (labelEl) labelEl.textContent = label;
    changeEl.innerHTML = formatChange(pct);
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

  /** Wilder 平滑 RSI（与通达信/同花顺默认算法一致） */
  function calcRsiWilder(closes, period) {
    const out = new Array(closes.length).fill(null);
    if (closes.length <= period) return out;

    let avgGain = 0;
    let avgLoss = 0;
    for (let i = 1; i <= period; i += 1) {
      const change = closes[i] - closes[i - 1];
      avgGain += change > 0 ? change : 0;
      avgLoss += change < 0 ? -change : 0;
    }
    avgGain /= period;
    avgLoss /= period;

    out[period] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);

    for (let i = period + 1; i < closes.length; i += 1) {
      const change = closes[i] - closes[i - 1];
      const gain = change > 0 ? change : 0;
      const loss = change < 0 ? -change : 0;
      avgGain = (avgGain * (period - 1) + gain) / period;
      avgLoss = (avgLoss * (period - 1) + loss) / period;
      out[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
    }
    return out;
  }

  function extractSeriesData(asset) {
    const series = asset.series || [];
    const dates = series.map((p) => p.date);
    const closes = series.map((p) => Number(p.close));
    // ECharts 蜡烛图顺序：[开盘, 收盘, 最低, 最高]
    const ohlc = series.map((p) => [
      Number(p.open),
      Number(p.close),
      Number(p.low),
      Number(p.high),
    ]);
    const hasOhlc = asset.chart_type === "candlestick";
    return { series, dates, closes, ohlc, hasOhlc };
  }

  function formatOhlcTooltip(point, dayChangePct) {
    const open = Number(point.open);
    const high = Number(point.high);
    const low = Number(point.low);
    const close = Number(point.close);
    const lines = [
      `开 $${open.toFixed(2)} 高 $${high.toFixed(2)}`,
      `低 $${low.toFixed(2)} 收 $${close.toFixed(2)}`,
    ];
    if (dayChangePct != null) {
      const sign = dayChangePct >= 0 ? "+" : "";
      lines.push(`日涨跌 ${sign}${dayChangePct.toFixed(2)}%`);
    }
    return lines;
  }

  function buildChartLayout(settings) {
    const showMacd = settings.macd;
    const showRsi = hasAnyRsi(settings);
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
    const { series: seriesPoints, dates, closes, ohlc, hasOhlc } = extractSeriesData(asset);
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
      const rsiConfigs = [
        { key: "rsi6", period: 6, color: "#d76636", label: "RSI(6)" },
        { key: "rsi12", period: 12, color: "#3957b8", label: "RSI(12)" },
        { key: "rsi24", period: 24, color: "#1f6f5f", label: "RSI(24)" },
      ];
      let firstRsi = true;
      rsiConfigs.forEach(({ key, period, color, label }) => {
        if (!settings[key]) return;
        series.push({
          name: label,
          type: "line",
          xAxisIndex: subAxisIndex,
          yAxisIndex: subAxisIndex,
          data: calcRsiWilder(closes, period),
          symbol: "none",
          lineStyle: { width: 1.2, color },
          markLine: firstRsi ? {
            symbol: "none",
            data: [
              { yAxis: 70, lineStyle: { type: "dashed", color: "rgba(215,102,54,0.45)" } },
              { yAxis: 30, lineStyle: { type: "dashed", color: "rgba(31,111,95,0.45)" } },
            ],
          } : undefined,
        });
        firstRsi = false;
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
            if (item.seriesType === "candlestick") {
              const idx = item.dataIndex;
              const point = seriesPoints[idx];
              if (point && point.open != null && point.high != null && point.low != null) {
                lines.push(...formatOhlcTooltip(point, calcDailyChangePct(seriesPoints, idx)));
              }
            } else if (item.data != null && item.seriesName !== "MACD") {
              const val = Number(item.data);
              const isRsi = String(item.seriesName).startsWith("RSI");
              lines.push(
                `${item.seriesName}: ${isRsi ? val.toFixed(2) : "$" + val.toFixed(2)}`
              );
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

    const macdTags = buildMacdSignalTags(asset.macd);

    card.innerHTML = `
      <div class="stock-chart-head">
        <div>
          <h3 class="stock-chart-title">${asset.ticker} ${chartTypeNote}</h3>
          <p class="stock-chart-meta">${asset.exchange} · 关联 ${(asset.themes || []).length} 个主题</p>
        </div>
        <div class="stock-chart-price">
          <strong>${formatPrice(asset.current_price)}</strong>
          <div class="stock-chart-change-wrap">
            <span class="stock-chart-change-label">日涨跌</span>
            <span class="stock-chart-change">${formatChange(asset.change_pct)}</span>
          </div>
        </div>
      </div>
      <div class="stock-theme-tags">${themeTags}</div>
      ${alertTags ? `<div class="stock-alert-tags">${alertTags}</div>` : ""}
      ${macdTags ? `<div class="stock-macd-tags">${macdTags}</div>` : ""}
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

    const chartHeight = indicatorSettings.macd || hasAnyRsi(indicatorSettings) ? 360 : 300;
    dom.style.height = `${chartHeight}px`;

    const chart = echarts.init(dom);
    chart.setOption(buildChartOption(asset), true);

    const card = dom.closest(".stock-chart-card");
    if (card) {
      updateCardChangeDisplay(card, asset, chart);
      chart.on("dataZoom", () => updateCardChangeDisplay(card, asset, chart));
    }

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

  function loadPerPageSetting() {
    try {
      const raw = localStorage.getItem(PER_PAGE_STORAGE_KEY);
      const parsed = parseInt(raw, 10);
      if (parsed >= 4 && parsed <= 24) return parsed;
    } catch (e) {
      /* ignore */
    }
    return DEFAULT_PER_PAGE;
  }

  function savePerPageSetting(value) {
    localStorage.setItem(PER_PAGE_STORAGE_KEY, String(value));
  }

  function syncPerPageSelect() {
    const select = document.getElementById("stocksPerPage");
    if (!select) return;
    if (![...select.options].some((opt) => Number(opt.value) === perPage)) {
      const option = document.createElement("option");
      option.value = String(perPage);
      option.textContent = `${perPage} 个`;
      select.appendChild(option);
    }
    select.value = String(perPage);
  }

  function buildChartDataUrl(forceRefresh) {
    const params = new URLSearchParams();
    params.set("page", String(currentPage));
    params.set("per_page", String(perPage));
    const q = document.getElementById("tickerFilter")?.value?.trim();
    if (q) params.set("q", q);
    if (forceRefresh) params.set("refresh", "1");
    return `/investments/stocks/api/chart-data?${params.toString()}`;
  }

  function updatePaginationControls(summary) {
    const nav = document.getElementById("stocksPagination");
    const info = document.getElementById("stocksPageInfo");
    const prevBtn = document.getElementById("stocksPrevPage");
    const nextBtn = document.getElementById("stocksNextPage");
    if (!nav || !summary) return;

    const total = summary.ticker_count || 0;
    const totalPages = summary.total_pages || 0;
    if (total <= 0) {
      nav.hidden = true;
      return;
    }

    nav.hidden = false;
    const page = summary.page || 1;
    if (info) {
      info.textContent = `第 ${page} / ${totalPages} 页 · 本页 ${summary.page_count || 0} 个`;
    }
    if (prevBtn) prevBtn.disabled = page <= 1;
    if (nextBtn) nextBtn.disabled = page >= totalPages;
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

    const summary = payload.summary || {};
    summaryTicker.textContent = String(summary.ticker_count || 0);
    summaryLinks.textContent = String(summary.theme_link_count || 0);
    updatePaginationControls(summary);

    if (!summary.ticker_count) {
      empty.hidden = false;
      grid.hidden = true;
      const emptyMsg = empty.querySelector("p");
      if (emptyMsg) {
        emptyMsg.textContent = "请先在投资主题详情页添加监控标的。";
      }
      if (chartModeHint) chartModeHint.textContent = "";
      return;
    }

    if (!payload.assets || !payload.assets.length) {
      empty.hidden = false;
      grid.hidden = true;
      const emptyMsg = empty.querySelector("p");
      if (emptyMsg) {
        emptyMsg.textContent = summary.filtered
          ? "没有匹配的标的，请调整筛选条件。"
          : "当前页暂无数据。";
      }
      if (chartModeHint) chartModeHint.textContent = "";
      return;
    }

    empty.hidden = true;
    grid.hidden = false;
    allAssets = payload.assets;

    currentPage = summary.page || currentPage;

    const candleCount = payload.assets.filter((a) => a.chart_type === "candlestick").length;
    if (chartModeHint) {
      if (payload.summary.ohlc_available && candleCount > 0) {
        chartModeHint.textContent = `${candleCount} 个标的使用 FMP 日K蜡烛图，其余为折线`;
      } else if (payload.summary.ohlc_available || payload.summary.fmp_configured) {
        chartModeHint.textContent = "已配置 FMP，刷新后可获取 OHLC 蜡烛图数据";
      } else {
        chartModeHint.textContent = "未配置 FMP，仅显示收盘价折线";
      }
    }

    payload.assets.forEach((asset) => {
      grid.appendChild(renderCard(asset));
    });

    payload.assets.forEach((asset) => mountChart(asset));
  }

  async function loadChartData(forceRefresh) {
    const loading = document.getElementById("stocksLoading");
    const grid = document.getElementById("stocksGrid");
    const empty = document.getElementById("stocksEmpty");

    loading.hidden = false;
    grid.hidden = true;
    empty.hidden = true;

    try {
      const response = await fetch(buildChartDataUrl(forceRefresh));
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

    perPage = loadPerPageSetting();
    syncPerPageSelect();

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

    document.getElementById("stocksPerPage")?.addEventListener("change", (event) => {
      perPage = parseInt(event.target.value, 10) || DEFAULT_PER_PAGE;
      savePerPageSetting(perPage);
      currentPage = 1;
      loadChartData(false);
    });

    document.getElementById("stocksPrevPage")?.addEventListener("click", () => {
      if (currentPage > 1) {
        currentPage -= 1;
        loadChartData(false);
      }
    });

    document.getElementById("stocksNextPage")?.addEventListener("click", () => {
      currentPage += 1;
      loadChartData(false);
    });

    document.getElementById("tickerFilter")?.addEventListener("input", () => {
      clearTimeout(filterDebounceTimer);
      filterDebounceTimer = setTimeout(() => {
        currentPage = 1;
        loadChartData(false);
      }, 350);
    });

    window.addEventListener("resize", handleResize);
  });
})();
