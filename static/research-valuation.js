(function () {
  const cfg = window.FINANCIAL_REPORT_PAGE || {};

  const MARKET_CAP_UNITS = {
    yi: { label: "亿", title: "亿美元", factor: 1e8 },
    wan: { label: "万", title: "万美元", factor: 1e4 },
    raw: { label: "$", title: "美元", factor: 1 },
  };

  const SHARES_UNITS = {
    yi: { label: "亿股", title: "亿股", factor: 1e8 },
    wan: { label: "万股", title: "万股", factor: 1e4 },
    raw: { label: "股", title: "股", factor: 1 },
  };

  let pendingAiParams = null;
  let currentValuation = null;
  let activeModel = "damodaran";

  function $(id) {
    return document.getElementById(id);
  }

  function escapeHtml(text) {
    return String(text ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function fmtNum(value, digits = 2) {
    if (value == null || Number.isNaN(Number(value))) return "—";
    return Number(value).toLocaleString("zh-CN", {
      maximumFractionDigits: digits,
      minimumFractionDigits: 0,
    });
  }

  function fmtUsd(value) {
    if (value == null) return "—";
    const n = Number(value);
    if (Math.abs(n) >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
    if (Math.abs(n) >= 1e6) return `$${(n / 1e6).toFixed(2)}M`;
    return `$${fmtNum(n)}`;
  }

  function fmtUsdYi(value) {
    if (value == null) return null;
    return `${fmtNum(Number(value) / 1e8, 2)} 亿美元`;
  }

  function fmtSharesYi(shares) {
    if (shares == null) return null;
    return `${fmtNum(Number(shares) / 1e8, 2)} 亿股`;
  }

  function toDisplayValue(raw, unitKey, units) {
    if (raw == null || raw === "") return "";
    const factor = units[unitKey]?.factor || 1;
    const n = Number(raw) / factor;
    if (Number.isNaN(n)) return "";
    return String(Number(n.toPrecision(10)));
  }

  function toRawValue(inputValue, unitKey, units) {
    if (inputValue === "" || inputValue == null) return null;
    const n = Number(inputValue);
    if (Number.isNaN(n)) return null;
    const factor = units[unitKey]?.factor || 1;
    return n * factor;
  }

  function renderUnitOptions(units, selected) {
    return Object.entries(units)
      .map(([key, meta]) => {
        const title = meta.title ? ` title="${escapeHtml(meta.title)}"` : "";
        return `<option value="${key}"${key === selected ? " selected" : ""}${title}>${escapeHtml(meta.label)}</option>`;
      })
      .join("");
  }

  function renderInputWithUnit(id, unitId, value, units, placeholder) {
    const unitTitle = Object.values(units)
      .map((m) => m.title)
      .filter(Boolean)
      .join(" / ");
    return `
      <div class="research-valuation-input-group">
        <input type="number" step="any" id="${id}" value="${escapeHtml(value)}" placeholder="${escapeHtml(placeholder)}">
        <select id="${unitId}" class="research-valuation-unit" aria-label="单位" title="${escapeHtml(unitTitle)}">
          ${renderUnitOptions(units, "yi")}
        </select>
      </div>`;
  }

  function renderKpiCard(label, value, hint) {
    return `
      <article class="research-kpi-card">
        <div class="research-kpi-label">${escapeHtml(label)}</div>
        <div class="research-kpi-value">${escapeHtml(value)}</div>
        ${hint ? `<div class="research-kpi-delta">${escapeHtml(hint)}</div>` : ""}
      </article>
    `;
  }

  function renderDataGaps(dataGaps) {
    if (!dataGaps || !dataGaps.has_gaps) return "";
    const items = dataGaps.items || [];
    const rows = items
      .filter((item) => item.status !== "ok")
      .map((item) => {
        const statusLabel =
          item.status === "missing" ? "缺失" : item.status === "partial" ? "不足" : "就绪";
        const action = item.action
          ? `<div class="research-valuation-gap-action">${escapeHtml(item.action)}</div>`
          : "";
        return `<li class="research-valuation-gap-item research-valuation-gap-${item.status}">
          <span class="research-valuation-gap-badge">${statusLabel}</span>
          <div class="research-valuation-gap-body">
            <strong>${escapeHtml(item.label)}</strong>
            <span>${escapeHtml(item.detail || "")}</span>
            ${action}
          </div>
        </li>`;
      })
      .join("");
    if (!rows) return "";
    return `
      <section class="research-valuation-gaps" aria-label="数据就绪情况">
        <h4>数据就绪情况</h4>
        <p class="hint">以下数据缺失或不足，可能影响估值指标：</p>
        <ul class="research-valuation-gap-list">${rows}</ul>
      </section>`;
  }

  function renderScenarioTable(modelData) {
    const rows = (modelData && modelData.scenarios) || [];
    if (!rows.length) {
      return `<p class="hint">缺少必要数据或参数无效，无法计算。见下方「数据就绪情况」。</p>`;
    }
    const head = `
      <thead><tr>
        <th>情景</th><th>增长假设</th><th>永续增长</th><th>隐含股价</th><th>较现价</th>
      </tr></thead>`;
    const body = rows
      .map((row) => {
        const diff = row.vs_current_price_pct;
        const diffText = diff == null ? "—" : `${diff > 0 ? "+" : ""}${diff}%`;
        return `<tr>
          <td>${escapeHtml(row.label || row.name)}</td>
          <td>${fmtNum(row.growth_pct)}%</td>
          <td>${fmtNum(row.terminal_growth_pct)}%</td>
          <td>${row.implied_price != null ? "$" + fmtNum(row.implied_price, 2) : "—"}</td>
          <td>${diffText}</td>
        </tr>`;
      })
      .join("");
    return `<table class="research-valuation-dcf-table">${head}<tbody>${body}</tbody></table>`;
  }

  function renderImpliedWacc(implied) {
    const data = implied || {};
    if (data.available && data.value != null) {
      return `
        <div class="research-valuation-implied-wacc" id="impliedWaccRow">
          <span>现价隐含 WACC（中性）：<strong>${fmtNum(data.value)}%</strong></span>
          <button type="button" class="secondary-btn" id="applyImpliedWaccBtn">应用到 WACC</button>
        </div>`;
    }
    const reason = data.reason || "无法计算";
    return `
      <div class="research-valuation-implied-wacc" id="impliedWaccRow">
        <span class="hint">现价隐含 WACC（中性）：${escapeHtml(reason)}</span>
      </div>`;
  }

  function renderModelToggle(selected) {
    return `
      <div class="research-valuation-model-toggle" role="tablist" aria-label="估值模型">
        <button type="button" class="research-valuation-model-btn${selected === "damodaran" ? " active" : ""}" data-model="damodaran" role="tab" aria-selected="${selected === "damodaran"}">Damodaran DCF</button>
        <button type="button" class="research-valuation-model-btn${selected === "rim" ? " active" : ""}" data-model="rim" role="tab" aria-selected="${selected === "rim"}">R&D 资本化 RIM</button>
      </div>`;
  }

  function renderSharedRdFields(rdCap, rdYears) {
    return `
      <div class="research-valuation-form-row">
        <label class="research-valuation-checkbox">
          <input type="checkbox" id="dcfRdCapitalize"${rdCap ? " checked" : ""}> R&D 资本化
        </label>
        <label>R&D 摊销年数<input type="number" step="1" min="1" id="dcfRdAmortYears" value="${rdYears ?? 5}"></label>
      </div>`;
  }

  function renderDamodaranForm(params, survivalRate, rdMeta) {
    const terminal = params.terminal_growth || {};
    const rdCap = rdMeta?.rd_capitalize !== false;
    const rdYears = rdMeta?.rd_amort_years ?? 5;
    return `
      <form id="valuationDamodaranForm" class="research-valuation-form">
        <div class="research-valuation-form-row">
          <label>WACC %<input type="number" step="0.1" id="dcfWacc" value="${params.wacc ?? 12}"></label>
          <label>生存概率 %<input type="number" step="1" min="50" max="100" id="dcfSurvivalRate" value="${(survivalRate ?? 1) * 100}"></label>
          <label>乐观系数<input type="number" step="0.05" id="dcfOptimisticFactor" value="${params.optimistic_factor ?? 1.3}"></label>
          <label>悲观系数<input type="number" step="0.05" id="dcfPessimisticFactor" value="${params.pessimistic_factor ?? 0.6}"></label>
        </div>
        <div class="research-valuation-form-row">
          <label>永续增长(乐观)%<input type="number" step="0.1" id="dcfTerminalOpt" value="${terminal.optimistic ?? 4}"></label>
          <label>永续增长(中性)%<input type="number" step="0.1" id="dcfTerminalBase" value="${terminal.base ?? 3}"></label>
          <label>永续增长(悲观)%<input type="number" step="0.1" id="dcfTerminalPes" value="${terminal.pessimistic ?? 2}"></label>
        </div>
        ${renderSharedRdFields(rdCap, rdYears)}
        <button type="submit" class="secondary-btn">应用 Damodaran 参数</button>
      </form>`;
  }

  function renderRimForm(params, storedParams) {
    const terminal = params.terminal_growth || {};
    const rdYears = storedParams.rd_amort_years ?? 5;
    const rdCap = storedParams.rd_capitalize !== false;
    return `
      <form id="valuationRimForm" class="research-valuation-form">
        <div class="research-valuation-form-row">
          <label>股权成本 %<input type="number" step="0.1" id="rimCostOfEquity" value="${params.cost_of_equity ?? 12}"></label>
          <label>RIM 永续增长 %<input type="number" step="0.1" id="rimTerminalGrowth" value="${params.rim_terminal_growth ?? terminal.base ?? 3}"></label>
          <label>乐观系数<input type="number" step="0.05" id="rimOptimisticFactor" value="${storedParams.optimistic_factor ?? 1.3}"></label>
          <label>悲观系数<input type="number" step="0.05" id="rimPessimisticFactor" value="${storedParams.pessimistic_factor ?? 0.6}"></label>
        </div>
        <div class="research-valuation-form-row">
          <label>永续增长(乐观)%<input type="number" step="0.1" id="rimTerminalOpt" value="${terminal.optimistic ?? 4}"></label>
          <label>永续增长(中性)%<input type="number" step="0.1" id="rimTerminalBase" value="${terminal.base ?? 3}"></label>
          <label>永续增长(悲观)%<input type="number" step="0.1" id="rimTerminalPes" value="${terminal.pessimistic ?? 2}"></label>
        </div>
        ${renderSharedRdFields(rdCap, rdYears)}
        <button type="submit" class="secondary-btn">应用 RIM 参数</button>
      </form>`;
  }

  function renderAiRecommendSection() {
    const disabled = !cfg.aiConfigured || !cfg.hasAnalysis;
    const hint = !cfg.aiConfigured
      ? "未配置 DEEPSEEK_API_KEY"
      : !cfg.hasAnalysis
        ? "请先完成 AI 分析"
        : "";
    return `
      <div class="research-valuation-ai-bar">
        <button type="button" class="secondary-btn" id="valuationAiRecommendBtn"${disabled ? " disabled" : ""}>AI 推荐参数</button>
        ${hint ? `<span class="hint">${escapeHtml(hint)}</span>` : ""}
      </div>
      <div id="valuationAiPreview" class="research-valuation-ai-preview" hidden></div>`;
  }

  function readDamodaranFormPayload() {
    const survivalPct = Number($("dcfSurvivalRate")?.value);
    return {
      valuation_model: "damodaran",
      wacc: $("dcfWacc")?.value,
      survival_rate: Number.isNaN(survivalPct) ? undefined : survivalPct / 100,
      optimistic_factor: $("dcfOptimisticFactor")?.value,
      pessimistic_factor: $("dcfPessimisticFactor")?.value,
      terminal_growth_optimistic: $("dcfTerminalOpt")?.value,
      terminal_growth_base: $("dcfTerminalBase")?.value,
      terminal_growth_pessimistic: $("dcfTerminalPes")?.value,
      rd_capitalize: $("dcfRdCapitalize")?.checked ?? true,
      rd_amort_years: $("dcfRdAmortYears")?.value,
    };
  }

  function readRimFormPayload() {
    return {
      valuation_model: "rim",
      cost_of_equity: $("rimCostOfEquity")?.value,
      rim_terminal_growth: $("rimTerminalGrowth")?.value,
      optimistic_factor: $("rimOptimisticFactor")?.value,
      pessimistic_factor: $("rimPessimisticFactor")?.value,
      terminal_growth_optimistic: $("rimTerminalOpt")?.value,
      terminal_growth_base: $("rimTerminalBase")?.value,
      terminal_growth_pessimistic: $("rimTerminalPes")?.value,
      rd_capitalize: $("dcfRdCapitalize")?.checked ?? true,
      rd_amort_years: $("dcfRdAmortYears")?.value,
    };
  }

  function fillDamodaranForm(params) {
    if (!params) return;
    const map = {
      dcfWacc: params.wacc,
      dcfOptimisticFactor: params.optimistic_factor,
      dcfPessimisticFactor: params.pessimistic_factor,
      dcfTerminalOpt: params.terminal_growth_optimistic,
      dcfTerminalBase: params.terminal_growth_base,
      dcfTerminalPes: params.terminal_growth_pessimistic,
      dcfRdAmortYears: params.rd_amort_years,
    };
    Object.entries(map).forEach(([id, value]) => {
      const el = $(id);
      if (el && value != null) el.value = value;
    });
    if (params.survival_rate != null && $("dcfSurvivalRate")) {
      $("dcfSurvivalRate").value = Number(params.survival_rate) * 100;
    }
    if ($("dcfRdCapitalize") && params.rd_capitalize != null) {
      $("dcfRdCapitalize").checked = !!params.rd_capitalize;
    }
  }

  async function saveDcfParams(payload, reload = true) {
    if (!cfg.valuationDcfParamsUrl) return { ok: false, error: "缺少保存地址" };
    const res = await fetch(cfg.valuationDcfParamsUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) {
      return { ok: false, error: data.error || "保存失败" };
    }
    if (reload && typeof window.reloadResearchCharts === "function") {
      await window.reloadResearchCharts();
    }
    return { ok: true };
  }

  function hideAiPreview() {
    pendingAiParams = null;
    const box = $("valuationAiPreview");
    if (box) {
      box.hidden = true;
      box.innerHTML = "";
    }
  }

  function renderAiPreview(result) {
    const box = $("valuationAiPreview");
    if (!box) return;
    const p = result.params || {};
    box.hidden = false;
    box.innerHTML = `
      <strong>AI 推荐估值参数</strong>
      <table>
        <thead><tr><th>参数</th><th>推荐值</th></tr></thead>
        <tbody>
          <tr><td>模型</td><td>${p.valuation_model === "rim" ? "RIM" : "Damodaran"}</td></tr>
          <tr><td>WACC</td><td>${fmtNum(p.wacc)}%</td></tr>
          <tr><td>生存概率</td><td>${p.survival_rate != null ? fmtNum(Number(p.survival_rate) * 100) + "%" : "—"}</td></tr>
          <tr><td>乐观系数</td><td>${fmtNum(p.optimistic_factor)}</td></tr>
          <tr><td>悲观系数</td><td>${fmtNum(p.pessimistic_factor)}</td></tr>
          <tr><td>R&D 摊销年数</td><td>${p.rd_amort_years ?? "—"}</td></tr>
          <tr><td>永续增长(中性)</td><td>${fmtNum(p.terminal_growth_base)}%</td></tr>
        </tbody>
      </table>
      <p class="hint">${escapeHtml(result.rationale || "")}</p>
      <div class="research-valuation-ai-actions">
        <button type="button" class="primary-btn" id="valuationAiApplyBtn">应用推荐</button>
        <button type="button" class="secondary-btn" id="valuationAiCancelBtn">取消</button>
      </div>`;

    $("valuationAiApplyBtn")?.addEventListener("click", async () => {
      if (!pendingAiParams) return;
      fillDamodaranForm(pendingAiParams);
      const save = await saveDcfParams(pendingAiParams);
      if (!save.ok) {
        alert(save.error);
        return;
      }
      hideAiPreview();
    });
    $("valuationAiCancelBtn")?.addEventListener("click", hideAiPreview);
  }

  function updateModelPanels(model) {
    activeModel = model;
    const damodaranBlock = $("valuationDamodaranBlock");
    const rimBlock = $("valuationRimBlock");
    if (damodaranBlock) damodaranBlock.hidden = model !== "damodaran";
    if (rimBlock) rimBlock.hidden = model !== "rim";
    document.querySelectorAll(".research-valuation-model-btn").forEach((btn) => {
      const isActive = btn.dataset.model === model;
      btn.classList.toggle("active", isActive);
      btn.setAttribute("aria-selected", isActive ? "true" : "false");
    });
  }

  function bindForms(valuation) {
    const overrideForm = $("valuationOverrideForm");
    if (overrideForm) {
      overrideForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (!cfg.valuationOverrideUrl) return;
        const marketCapUnit = $("valuationMarketCapUnit")?.value || "yi";
        const sharesUnit = $("valuationSharesUnit")?.value || "yi";
        const marketCap = toRawValue($("valuationMarketCap")?.value, marketCapUnit, MARKET_CAP_UNITS);
        const shares = toRawValue($("valuationShares")?.value, sharesUnit, SHARES_UNITS);
        const res = await fetch(cfg.valuationOverrideUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ market_cap: marketCap, shares_outstanding: shares }),
        });
        const data = await res.json();
        if (!res.ok) {
          alert(data.error || "保存失败");
          return;
        }
        if (typeof window.reloadResearchCharts === "function") {
          await window.reloadResearchCharts();
        }
      });
    }

    $("valuationClearOverrideBtn")?.addEventListener("click", async () => {
      if (!cfg.valuationOverrideUrl) return;
      const res = await fetch(cfg.valuationOverrideUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ clear_market_cap: true, clear_shares: true }),
      });
      if (!res.ok) {
        const data = await res.json();
        alert(data.error || "清除失败");
        return;
      }
      if (typeof window.reloadResearchCharts === "function") {
        await window.reloadResearchCharts();
      }
    });

    document.querySelectorAll(".research-valuation-model-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const model = btn.dataset.model;
        if (!model || model === activeModel) return;
        updateModelPanels(model);
        const save = await saveDcfParams({ valuation_model: model });
        if (!save.ok) alert(save.error);
      });
    });

    $("valuationDamodaranForm")?.addEventListener("submit", async (event) => {
      event.preventDefault();
      const save = await saveDcfParams(readDamodaranFormPayload());
      if (!save.ok) alert(save.error);
    });

    $("valuationRimForm")?.addEventListener("submit", async (event) => {
      event.preventDefault();
      const save = await saveDcfParams(readRimFormPayload());
      if (!save.ok) alert(save.error);
    });

    $("applyImpliedWaccBtn")?.addEventListener("click", async () => {
      const implied = valuation?.implied_wacc;
      if (!implied?.available || implied.value == null) return;
      $("dcfWacc").value = implied.value;
      const save = await saveDcfParams(readDamodaranFormPayload());
      if (!save.ok) alert(save.error);
    });

    const aiBtn = $("valuationAiRecommendBtn");
    if (aiBtn && !aiBtn.disabled) {
      aiBtn.addEventListener("click", async () => {
        if (!cfg.valuationRecommendUrl) return;
        hideAiPreview();
        aiBtn.disabled = true;
        const prevText = aiBtn.textContent;
        aiBtn.textContent = "推荐中…";
        try {
          const res = await fetch(cfg.valuationRecommendUrl, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
          });
          const data = await res.json();
          if (!res.ok) {
            alert(data.error || "推荐失败");
            return;
          }
          pendingAiParams = data.params;
          renderAiPreview(data);
        } finally {
          aiBtn.disabled = false;
          aiBtn.textContent = prevText;
        }
      });
    }
  }

  function renderValuation(valuation) {
    const panel = $("valuationPanelContent");
    const section = $("panel-valuation");
    if (!panel || !section) return;

    if (!valuation) {
      section.dataset.empty = "1";
      panel.innerHTML = `<p class="hint">完成 AI 分析后可查看估值计算。</p>`;
      return;
    }

    section.dataset.empty = "0";
    pendingAiParams = null;
    currentValuation = valuation;
    activeModel = valuation.valuation_model || "damodaran";

    const market = valuation.market || {};
    const multiples = valuation.multiples || {};
    const damodaran = valuation.damodaran || {};
    const rim = valuation.rim || {};
    const dcfParams = valuation.dcf?.params || damodaran.params || {};
    const survivalRate = damodaran.survival_rate ?? damodaran.params?.survival_rate ?? 1;
    const warnings = (valuation.warnings || []).map((w) => `<li>${escapeHtml(w)}</li>`).join("");

    const marketCapDisplay = toDisplayValue(market.market_cap, "yi", MARKET_CAP_UNITS);
    const sharesDisplay = toDisplayValue(market.shares, "yi", SHARES_UNITS);
    const marketHint = [fmtUsdYi(market.market_cap), fmtSharesYi(market.shares)].filter(Boolean).join(" · ");

    panel.innerHTML = `
      <div class="research-chart-head">
        <h3>估值分析 · ${escapeHtml(valuation.ticker || cfg.ticker || "")}</h3>
        <span class="research-valuation-stage">${valuation.stage === "profitable" ? "盈利期 · 主看 PE/PEG" : "投入期 · 主看 PS"}</span>
      </div>
      ${valuation.interpretation ? `<p class="research-valuation-summary">${escapeHtml(valuation.interpretation)}</p>` : ""}
      ${renderDataGaps(valuation.data_gaps)}
      ${warnings ? `<ul class="research-valuation-warnings">${warnings}</ul>` : ""}

      <div class="research-kpi-grid research-valuation-kpis">
        ${renderKpiCard("现价", market.price != null ? "$" + fmtNum(market.price, 2) : "—", "来源: " + (market.source || "—"))}
        ${renderKpiCard("市值", fmtUsd(market.market_cap), marketHint || "")}
        ${renderKpiCard("PS", multiples.ps != null ? multiples.ps + "x" : "—", valuation.primary_metric === "PS" ? "主指标" : "")}
        ${renderKpiCard("PE", multiples.pe != null ? multiples.pe + "x" : "—", valuation.primary_metric === "PE" ? "主指标" : "")}
        ${renderKpiCard("PEG", multiples.peg != null ? multiples.peg : "—", multiples.pe_g_label || "")}
        ${renderKpiCard("营收增速", valuation.growth_pct != null ? valuation.growth_pct + "%" : "—", valuation.ttm?.method === "annualized_single_q" ? "单季年化" : "TTM")}
      </div>

      ${renderModelToggle(activeModel)}

      <form id="valuationOverrideForm" class="research-valuation-form">
        <h4>市值 / 股本覆盖</h4>
        <p class="hint">自动从 FMP 拉取；可手动覆盖。默认单位为「亿」，保存时自动换算为美元 / 股。</p>
        <div class="research-valuation-form-row">
          <label>市值
            ${renderInputWithUnit("valuationMarketCap", "valuationMarketCapUnit", marketCapDisplay, MARKET_CAP_UNITS, "如 3000")}
          </label>
          <label>总股本
            ${renderInputWithUnit("valuationShares", "valuationSharesUnit", sharesDisplay, SHARES_UNITS, "如 150")}
          </label>
        </div>
        <div class="research-valuation-form-actions">
          <button type="submit" class="primary-btn">保存覆盖</button>
          <button type="button" class="secondary-btn" id="valuationClearOverrideBtn">清除覆盖</button>
        </div>
      </form>

      <div id="valuationDamodaranBlock" class="research-valuation-dcf"${activeModel !== "damodaran" ? " hidden" : ""}>
        <h4>Damodaran 三情景估值</h4>
        ${renderScenarioTable(damodaran)}
        ${renderImpliedWacc(valuation.implied_wacc)}
        ${renderAiRecommendSection()}
        ${renderDamodaranForm(damodaran.params || dcfParams, survivalRate, {
          rd_capitalize: valuation.rd_adjustment?.rd_capitalized !== false,
          rd_amort_years: valuation.rd_adjustment?.rd_amort_years ?? 5,
        })}
      </div>

      <div id="valuationRimBlock" class="research-valuation-dcf"${activeModel !== "rim" ? " hidden" : ""}>
        <h4>R&D 资本化 RIM</h4>
        ${renderScenarioTable(rim)}
        ${renderRimForm(rim.params || {}, {
          optimistic_factor: damodaran.params?.optimistic_factor,
          pessimistic_factor: damodaran.params?.pessimistic_factor,
          rd_amort_years: valuation.rd_adjustment?.rd_amort_years ?? 5,
          rd_capitalize: valuation.rd_adjustment?.rd_capitalized !== false,
        })}
      </div>
    `;
    bindForms(valuation);
  }

  window.renderResearchValuation = renderValuation;
})();
