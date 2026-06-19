(function () {
  const cfg = window.FINANCIAL_REPORT_PAGE || {};

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

  function renderKpiCard(label, value, hint) {
    return `
      <article class="research-kpi-card">
        <div class="research-kpi-label">${escapeHtml(label)}</div>
        <div class="research-kpi-value">${escapeHtml(value)}</div>
        ${hint ? `<div class="research-kpi-delta">${escapeHtml(hint)}</div>` : ""}
      </article>
    `;
  }

  function renderDcfTable(dcf) {
    const rows = (dcf && dcf.scenarios) || [];
    if (!rows.length) {
      return `<p class="hint">缺少 FCF 或参数无效，无法计算 DCF。</p>`;
    }
    const head = `
      <thead><tr>
        <th>情景</th><th>增长假设</th><th>永续增长</th><th>隐含股价</th><th>较现价</th>
      </tr></thead>`;
    const body = rows
      .map((row) => {
        const diff = row.vs_current_price_pct;
        const diffText =
          diff == null ? "—" : `${diff > 0 ? "+" : ""}${diff}%`;
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

  function bindForms(valuation) {
    const overrideForm = $("valuationOverrideForm");
    if (overrideForm) {
      overrideForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (!cfg.valuationOverrideUrl) return;
        const marketCap = $("valuationMarketCap")?.value;
        const shares = $("valuationShares")?.value;
        const res = await fetch(cfg.valuationOverrideUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            market_cap: marketCap === "" ? null : marketCap,
            shares_outstanding: shares === "" ? null : shares,
          }),
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

    const clearBtn = $("valuationClearOverrideBtn");
    if (clearBtn) {
      clearBtn.addEventListener("click", async () => {
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
    }

    const dcfForm = $("valuationDcfForm");
    if (dcfForm) {
      dcfForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (!cfg.valuationDcfParamsUrl) return;
        const payload = {
          wacc: $("dcfWacc")?.value,
          optimistic_factor: $("dcfOptimisticFactor")?.value,
          pessimistic_factor: $("dcfPessimisticFactor")?.value,
          terminal_growth_optimistic: $("dcfTerminalOpt")?.value,
          terminal_growth_base: $("dcfTerminalBase")?.value,
          terminal_growth_pessimistic: $("dcfTerminalPes")?.value,
        };
        const res = await fetch(cfg.valuationDcfParamsUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
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
    const market = valuation.market || {};
    const multiples = valuation.multiples || {};
    const dcf = valuation.dcf || {};
    const params = dcf.params || {};
    const warnings = (valuation.warnings || [])
      .map((w) => `<li>${escapeHtml(w)}</li>`)
      .join("");

    panel.innerHTML = `
      <div class="research-chart-head">
        <h3>估值分析 · ${escapeHtml(valuation.ticker || cfg.ticker || "")}</h3>
        <span class="research-valuation-stage">${valuation.stage === "profitable" ? "盈利期 · 主看 PE/PEG" : "投入期 · 主看 PS"}</span>
      </div>
      ${valuation.interpretation ? `<p class="research-valuation-summary">${escapeHtml(valuation.interpretation)}</p>` : ""}
      ${warnings ? `<ul class="research-valuation-warnings">${warnings}</ul>` : ""}

      <div class="research-kpi-grid research-valuation-kpis">
        ${renderKpiCard("现价", market.price != null ? "$" + fmtNum(market.price, 2) : "—", "来源: " + (market.source || "—"))}
        ${renderKpiCard("市值", fmtUsd(market.market_cap), market.shares ? fmtNum(market.shares, 0) + " 股" : "")}
        ${renderKpiCard("PS", multiples.ps != null ? multiples.ps + "x" : "—", valuation.primary_metric === "PS" ? "主指标" : "")}
        ${renderKpiCard("PE", multiples.pe != null ? multiples.pe + "x" : "—", valuation.primary_metric === "PE" ? "主指标" : "")}
        ${renderKpiCard("PEG", multiples.peg != null ? multiples.peg : "—", multiples.pe_g_label || "")}
        ${renderKpiCard("营收增速", valuation.growth_pct != null ? valuation.growth_pct + "%" : "—", valuation.ttm?.method === "annualized_single_q" ? "单季年化" : "TTM")}
      </div>

      <form id="valuationOverrideForm" class="research-valuation-form">
        <h4>市值 / 股本覆盖</h4>
        <p class="hint">自动从 FMP 拉取；可手动覆盖（美元）。</p>
        <div class="research-valuation-form-row">
          <label>市值 (USD)<input type="number" step="any" id="valuationMarketCap" placeholder="如 500000000000"></label>
          <label>股本<input type="number" step="any" id="valuationShares" placeholder="如 15000000000"></label>
        </div>
        <div class="research-valuation-form-actions">
          <button type="submit" class="primary-btn">保存覆盖</button>
          <button type="button" class="secondary-btn" id="valuationClearOverrideBtn">清除覆盖</button>
        </div>
      </form>

      <div class="research-valuation-dcf">
        <h4>三情景 DCF</h4>
        ${renderDcfTable(dcf)}
        <form id="valuationDcfForm" class="research-valuation-form">
          <div class="research-valuation-form-row">
            <label>WACC %<input type="number" step="0.1" id="dcfWacc" value="${params.wacc ?? 12}"></label>
            <label>乐观系数<input type="number" step="0.05" id="dcfOptimisticFactor" value="${params.optimistic_factor ?? 1.3}"></label>
            <label>悲观系数<input type="number" step="0.05" id="dcfPessimisticFactor" value="${params.pessimistic_factor ?? 0.6}"></label>
          </div>
          <div class="research-valuation-form-row">
            <label>永续增长(乐观)%<input type="number" step="0.1" id="dcfTerminalOpt" value="${(params.terminal_growth || {}).optimistic ?? 4}"></label>
            <label>永续增长(中性)%<input type="number" step="0.1" id="dcfTerminalBase" value="${(params.terminal_growth || {}).base ?? 3}"></label>
            <label>永续增长(悲观)%<input type="number" step="0.1" id="dcfTerminalPes" value="${(params.terminal_growth || {}).pessimistic ?? 2}"></label>
          </div>
          <button type="submit" class="secondary-btn">应用 DCF 参数</button>
        </form>
      </div>
    `;
    bindForms(valuation);
  }

  window.renderResearchValuation = renderValuation;
})();
