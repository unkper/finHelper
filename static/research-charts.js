(function () {
  const cfg = window.FINANCIAL_REPORT_PAGE || {};
  const charts = {};
  let lastChartPayload = null;
  let lastGameRules = null;
  let lastNarratives = {};
  let parsePollTimer = null;
  let activeSection = "profitability";
  const STYLE_STORAGE_KEY = "finHelper:narrativeStyle";

  function getNarrativeStyle() {
    const saved = localStorage.getItem(STYLE_STORAGE_KEY);
    if (saved === "professional" || saved === "game") return saved;
    return "professional";
  }

  function setNarrativeStyle(style) {
    localStorage.setItem(STYLE_STORAGE_KEY, style);
    applyNarrativeStyle(style);
  }

  function applyThemeClass(style) {
    const root = document.getElementById("researchDetailRoot");
    if (!root) return;
    root.classList.toggle("research-theme-game", style === "game");
  }

  function updateStyleToggleUi(style) {
    document.querySelectorAll(".research-style-btn").forEach((btn) => {
      btn.classList.toggle("is-active", btn.dataset.style === style);
    });
  }

  function updateSectionTabLabels(style) {
    document.querySelectorAll(".research-section-tab").forEach((tab) => {
      const label =
        style === "game"
          ? tab.dataset.labelGame || tab.textContent
          : tab.dataset.labelPro || tab.textContent;
      tab.textContent = label;
    });
  }

  function setDashboardWrapOpen(open) {
    const wrap = document.getElementById("researchDashboardWrap");
    if (wrap) wrap.open = open;
  }

  function verdictLabel(verdict) {
    if (verdict === "winning") return "势如破竹";
    if (verdict === "losing") return "逆风局";
    return "僵持局";
  }

  function renderProfessionalNarrative(narrative) {
    const summaryEl = document.querySelector(".research-ai-summary");
    const bulletsEl = document.getElementById("professionalBullets");
    if (!narrative) return;
    if (summaryEl && narrative.headline) {
      summaryEl.textContent = narrative.headline;
      summaryEl.hidden = false;
    }
    if (bulletsEl && narrative.bullets?.length) {
      bulletsEl.innerHTML = narrative.bullets.map((b) => `<li>${escapeHtmlText(b)}</li>`).join("");
      bulletsEl.hidden = false;
    } else if (bulletsEl) {
      bulletsEl.hidden = true;
    }
    if (narrative.risk_cards?.length) {
      renderProfessionalRiskCards(narrative.risk_cards);
    }
  }

  function renderProfessionalRiskCards(cards) {
    const panel = document.getElementById("redFlagsPanel");
    if (!panel) return;
    panel.hidden = false;
    panel.className = "panel research-red-flags";
    panel.innerHTML = `<strong>风险提示</strong><ul>${cards
      .map(
        (c) =>
          `<li><strong>${escapeHtmlText(c.title)}</strong> — ${escapeHtmlText(c.one_liner || "")}</li>`
      )
      .join("")}</ul>`;
  }

  function renderGameStats(stats, flavors) {
    const panel = document.getElementById("gameStatsPanel");
    if (!panel) return;
    if (!stats?.length) {
      panel.hidden = true;
      return;
    }
    panel.hidden = false;
    panel.innerHTML = `
      <strong>角色属性</strong>
      <div class="research-game-stats-grid">${stats
        .map((s) => {
          const tier = (s.tier || "B").toLowerCase();
          const debuff = s.debuff ? " research-game-stat--debuff" : "";
          const deltaCls =
            s.delta && String(s.delta).includes("-") ? " negative" : "";
          const flavor = flavors?.[s.key] ? `<div class="research-game-stat-flavor">${escapeHtmlText(flavors[s.key])}</div>` : "";
          return `<article class="research-game-stat research-game-stat--tier-${tier}${debuff}">
            <div class="research-game-stat-label">${escapeHtmlText(s.label)}</div>
            <div class="research-game-stat-value">${escapeHtmlText(s.value)}</div>
            ${s.delta ? `<div class="research-game-stat-delta${deltaCls}">${escapeHtmlText(s.delta)}</div>` : ""}
            ${flavor}
          </article>`;
        })
        .join("")}</div>`;
  }

  function renderGameRun(narrative, gameRules) {
    const panel = document.getElementById("gameRunPanel");
    if (!panel) return;
    const verdict = narrative?.run_verdict || gameRules?.run_verdict || "stalemate";
    const hp = narrative?.hp_pct ?? gameRules?.hp_pct ?? 50;
    const ticker = cfg.ticker || "";
    const season = cfg.fiscalPeriod ? `${cfg.fiscalPeriod} 赛季` : "本赛季";
    panel.hidden = false;
    panel.innerHTML = `
      <div class="research-game-run-head">
        <div>
          <div class="research-game-guild">${escapeHtmlText(narrative?.guild_title || `${ticker} 公会`)}</div>
          <div class="research-game-season">${escapeHtmlText(season)}结算</div>
        </div>
        <span class="research-game-verdict research-game-verdict--${verdict}">${verdictLabel(verdict)}</span>
      </div>
      <p class="research-game-headline">${escapeHtmlText(narrative?.run_headline || "战报生成中…")}</p>
      <div class="research-game-hp" title="综合血条（规则计算）"><div class="research-game-hp-fill" style="width:${hp}%"></div></div>
      ${
        narrative?.patch_notes?.length
          ? `<ul class="research-game-patch-notes">${narrative.patch_notes
              .map((n) => `<li>${escapeHtmlText(n)}</li>`)
              .join("")}</ul>`
          : ""
      }
      <p class="research-game-footnote">${escapeHtmlText(narrative?.footnote || "")}</p>`;
  }

  function renderGameBosses(bosses) {
    const panel = document.getElementById("gameBossPanel");
    if (!panel) return;
    if (!bosses?.length) {
      panel.hidden = true;
      return;
    }
    panel.hidden = false;
    panel.innerHTML = `
      <strong>BOSS 遭遇战</strong>
      ${bosses
        .map((b) => {
          const threat = b.threat || "medium";
          const bars = b.hp_bars || (threat === "high" ? 3 : threat === "low" ? 1 : 2);
          const barHtml = Array.from({ length: bars })
            .map(() => '<span class="research-game-boss-bar"></span>')
            .join("");
          return `<article class="research-game-boss-card research-game-boss-card--${threat}">
            <div class="research-game-boss-name">${escapeHtmlText(b.boss_name)}</div>
            <div class="research-game-boss-threat">威胁：${escapeHtmlText(threat)}</div>
            <div class="research-game-boss-bars">${barHtml}</div>
            ${b.attack_pattern ? `<p>${escapeHtmlText(b.attack_pattern)}</p>` : ""}
            ${b.counter_tip ? `<p><em>应对：</em>${escapeHtmlText(b.counter_tip)}</p>` : ""}
          </article>`;
        })
        .join("")}`;
  }

  function renderGameQuests(quests, materialEvents, unit) {
    const panel = document.getElementById("gameQuestPanel");
    const legacy = document.getElementById("materialEventsPanel");
    if (!panel) return;
    const items = [];
    if (quests?.length) {
      quests.forEach((q) => {
        items.push({
          title: q.quest_title,
          type: q.quest_type === "penalty" ? "penalty" : "reward",
          body: q.objective,
        });
      });
    } else if (materialEvents?.length) {
      materialEvents.forEach((e) => {
        items.push({
          title: e.title,
          type: e.type === "loss" ? "penalty" : "reward",
          body: e.description,
          amount: e.amount_millions,
        });
      });
    }
    if (!items.length) {
      panel.hidden = true;
      if (legacy && getNarrativeStyle() !== "game") {
        /* legacy panel handled by renderMaterialEvents */
      }
      return;
    }
    panel.hidden = false;
    if (legacy) legacy.hidden = true;
    const unitLabel = unit === "millions" ? " M USD" : "";
    panel.innerHTML = `
      <strong>支线任务</strong>
      ${items
        .map((q) => {
          const cls = q.type === "penalty" ? "penalty" : "reward";
          const amt =
            q.amount != null ? `<span> · ${q.amount}${unitLabel}</span>` : "";
          return `<article class="research-game-quest-card research-game-quest-card--${cls}">
            <strong>${escapeHtmlText(q.title)}</strong>${amt}
            <p>${escapeHtmlText(q.body || "")}</p>
          </article>`;
        })
        .join("")}`;
  }

  function applyNarrativeStyle(style) {
    updateStyleToggleUi(style);
    applyThemeClass(style);
    updateSectionTabLabels(style);
    const proPanel = document.getElementById("professionalNarrative");
    const gamePanel = document.getElementById("gameNarrative");
    const bossPanel = document.getElementById("gameBossPanel");
    const questPanel = document.getElementById("gameQuestPanel");
    const redPanel = document.getElementById("redFlagsPanel");

    if (style === "game") {
      if (proPanel) proPanel.hidden = true;
      if (gamePanel) gamePanel.hidden = false;
      if (redPanel) redPanel.hidden = true;
      setDashboardWrapOpen(false);
      const rules = lastGameRules;
      const narrative = lastNarratives.game;
      if (rules) {
        renderGameStats(
          narrative?.game_rules?.stats || rules.stats,
          narrative?.stat_flavors || {}
        );
      }
      if (narrative) {
        renderGameRun(narrative, rules);
        renderGameBosses(narrative.boss_encounters);
        renderGameQuests(narrative.quests, null, lastChartPayload?.unit);
      } else if (rules) {
        renderGameRun({ run_headline: "点击下方可刷新战报，或等待 AI 生成…" }, rules);
        renderGameBosses(
          (rules.boss_defaults || []).map((b) => ({
            boss_name: b.boss_name,
            threat: b.threat,
            hp_bars: b.hp_bars,
            attack_pattern: "",
            counter_tip: "",
          }))
        );
      }
      if (!narrative?.quests?.length && lastChartPayload) {
        renderGameQuests(null, lastChartPayload.material_events, lastChartPayload.unit);
      }
    } else {
      if (proPanel) proPanel.hidden = false;
      if (gamePanel) gamePanel.hidden = true;
      if (bossPanel) bossPanel.hidden = true;
      if (questPanel) questPanel.hidden = true;
      setDashboardWrapOpen(true);
      const narrative = lastNarratives.professional;
      if (narrative) renderProfessionalNarrative(narrative);
      else if (lastChartPayload) renderInsights(lastChartPayload);
    }
  }

  async function fetchNarrative(style, force = false) {
    if (!cfg.narrativeUrl || !cfg.aiConfigured || !cfg.hasAnalysis) return null;
    if (!force && lastNarratives[style]) return lastNarratives[style];
    const loading = document.getElementById("gameNarrativeLoading");
    if (loading && style === "game") loading.hidden = false;
    try {
      const res = await fetch(cfg.narrativeUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ style }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "叙事生成失败");
      if (data.game_rules) lastGameRules = data.game_rules;
      if (data.narrative) lastNarratives[style] = data.narrative;
      return data.narrative;
    } catch (err) {
      console.warn(err);
      return null;
    } finally {
      if (loading) loading.hidden = true;
    }
  }

  async function ensureNarrativeForStyle(style) {
    if (lastNarratives[style]) {
      applyNarrativeStyle(style);
      return;
    }
    if (style === "professional" && document.querySelector(".research-ai-summary")?.textContent) {
      lastNarratives.professional = {
        headline: document.querySelector(".research-ai-summary").textContent,
        bullets: [],
        risk_cards: (lastChartPayload?.red_flags || []).map((f) => ({
          title: f.message?.slice(0, 60),
          one_liner: f.message,
          severity: "medium",
        })),
      };
      applyNarrativeStyle(style);
      fetchNarrative("professional").then(() => applyNarrativeStyle(style));
      return;
    }
    await fetchNarrative(style);
    applyNarrativeStyle(style);
  }

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
    if (getNarrativeStyle() === "game") {
      panel.hidden = true;
      if (flags?.length && lastGameRules) {
        renderGameBosses(
          (lastNarratives.game?.boss_encounters) ||
            (lastGameRules.boss_defaults || []).map((b) => ({
              boss_name: b.boss_name,
              threat: b.threat,
              hp_bars: b.hp_bars,
            }))
        );
      }
      return;
    }
    if (!flags || !flags.length) {
      panel.hidden = true;
      return;
    }
    panel.hidden = false;
    panel.innerHTML = `<strong>风险提示</strong><ul>${flags.map((f) => `<li>${escapeHtmlText(f.message)}</li>`).join("")}</ul>`;
  }

  function escapeHtmlText(text) {
    const div = document.createElement("div");
    div.textContent = text == null ? "" : String(text);
    return div.innerHTML;
  }

  function renderMaterialEvents(events, unit) {
    const panel = document.getElementById("materialEventsPanel");
    if (!panel) return;
    if (getNarrativeStyle() === "game") {
      renderGameQuests(lastNarratives.game?.quests, events, unit);
      return;
    }
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
    document.querySelectorAll(".research-charts-grid [data-section]").forEach((panel) => {
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
    const insightPanel = document.getElementById("dashboardInsightPanel");
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
    lastChartPayload = data;
    if (data.game_rules) lastGameRules = data.game_rules;
    if (data.narratives && typeof data.narratives === "object") {
      lastNarratives = { ...lastNarratives, ...data.narratives };
    }
    renderFilingMeta(data.filing_meta, document.getElementById("confirmFilingMeta"));
    if (data.filing_meta) {
      const panel = document.getElementById("secFilingMetaPanel");
      const list = document.getElementById("secFilingMetaList");
      if (panel && list) {
        panel.hidden = false;
        list.innerHTML = [
          ["表单", data.filing_meta.form_type],
          ["报告期末", data.filing_meta.period_end],
          ["日历季", data.filing_meta.calendar_period],
          [
            "公司财年",
            data.filing_meta.filing_fy && data.filing_meta.filing_fq
              ? `FY${data.filing_meta.filing_fy} Q${data.filing_meta.filing_fq}`
              : "—",
          ],
          ["现金流口径", data.filing_meta.cash_flow_scope],
        ]
          .map(([k, v]) => `<div><span>${k}</span><strong>${v ?? "—"}</strong></div>`)
          .join("");
      }
    }
    const wrap = document.getElementById("researchDashboardWrap");
    if (wrap) wrap.hidden = false;
    const styleToggle = document.getElementById("narrativeStyleToggle");
    if (styleToggle) styleToggle.hidden = false;
    renderInsights(data);
    if (!data.periods?.length) {
      applyNarrativeStyle(getNarrativeStyle());
      ensureNarrativeForStyle(getNarrativeStyle());
      return;
    }
    renderChartPanels(data);
    if (typeof window.renderResearchValuation === "function") {
      window.renderResearchValuation(data.valuation || null);
    }
    applyNarrativeStyle(getNarrativeStyle());
    ensureNarrativeForStyle(getNarrativeStyle());
  }

  function insightCacheKey(chartType) {
    return `finHelper:chartInsight:${cfg.reportId}:${chartType}:${getNarrativeStyle()}`;
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
        body: JSON.stringify({ chart_type: chartType, style: getNarrativeStyle() }),
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
    return `finHelper:dashboardInsight:${cfg.reportId}:${getNarrativeStyle()}`;
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
      const res = await fetch(cfg.dashboardInsightUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ style: getNarrativeStyle() }),
      });
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

  function renderFilingMeta(meta, container) {
    if (!container || !meta || !["sec_fmp", "sec_xls"].includes(meta.source)) {
      if (container) container.hidden = true;
      return;
    }
    const rows = [
      ["表单", meta.form_type],
      ["报告期末", meta.period_end],
      ["日历季", meta.calendar_period],
      ["FMP 财年/期", meta.fmp_year && meta.fmp_period ? `FY${meta.fmp_year} ${meta.fmp_period}` : "—"],
      ["公司财年", meta.filing_fy && meta.filing_fq ? `FY${meta.filing_fy} Q${meta.filing_fq}` : "—"],
      ["现金流口径", meta.cash_flow_scope],
      ["CIK", meta.cik],
    ];
    container.hidden = false;
    container.innerHTML = rows
      .map(([k, v]) => `<div><span>${k}</span><strong>${v ?? "—"}</strong></div>`)
      .join("");
  }

  function openConfirmModal(result) {
    confirmJson.value = JSON.stringify(result.extracted, null, 2);
    confirmSummary.value = result.ai_summary || result.extracted?.ai_summary || "";
    renderFilingMeta(result.extracted?.filing_meta, document.getElementById("confirmFilingMeta"));
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

  document.getElementById("filingNarrativeBtn")?.addEventListener("click", async () => {
    if (!cfg.filingNarrativeUrl) return;
    const btn = document.getElementById("filingNarrativeBtn");
    try {
      if (btn) {
        btn.disabled = true;
        btn.textContent = "生成中…";
      }
      const res = await fetch(cfg.filingNarrativeUrl, { method: "POST" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "生成失败");
      alert("摘要已生成，请刷新页面或打开确认查看。");
      window.location.reload();
    } catch (err) {
      alert(err.message || "生成失败");
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = "AI 生成摘要";
      }
    }
  });

  const supplementInput = document.getElementById("supplementDocxInput");
  const supplementBtn = document.getElementById("supplementDocxBtn");

  supplementBtn?.addEventListener("click", () => supplementInput?.click());

  supplementInput?.addEventListener("change", async () => {
    const file = supplementInput.files?.[0];
    if (!file || !cfg.supplementDocxUrl) return;
    if (!window.confirm(`上传「${file.name}」作为 10-K Word 补充？AI 将归纳事件与风险并进入待确认。`)) {
      supplementInput.value = "";
      return;
    }
    const fd = new FormData();
    fd.append("file", file);
    try {
      if (supplementBtn) {
        supplementBtn.disabled = true;
        supplementBtn.textContent = "上传中…";
      }
      const res = await fetch(cfg.supplementDocxUrl, { method: "POST", body: fd });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "上传失败");
      setParseUi("done", { hasPending: true, message: "Word 补充已合并，请确认结构化结果" });
      const openPendingBtn = document.getElementById("openPendingConfirmBtn");
      if (openPendingBtn) openPendingBtn.hidden = false;
      const badge = document.getElementById("supplementBadge");
      if (badge) {
        badge.hidden = false;
        badge.textContent = `已附 Word · ${file.name}`;
      }
      await openPendingConfirm();
    } catch (err) {
      alert(err.message || "Word 补充失败");
    } finally {
      supplementInput.value = "";
      if (supplementBtn) {
        supplementBtn.disabled = false;
        supplementBtn.textContent = "上传 10-K Word 补充";
      }
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

  document.querySelectorAll(".research-style-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const style = btn.dataset.style;
      if (style) setNarrativeStyle(style);
      ensureNarrativeForStyle(style);
    });
  });

  updateStyleToggleUi(getNarrativeStyle());
  applyThemeClass(getNarrativeStyle());

  window.reloadResearchCharts = loadCharts;

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
  } else if (cfg.hasAnalysis) {
    applyNarrativeStyle(getNarrativeStyle());
  }
})();
