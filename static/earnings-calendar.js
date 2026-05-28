(function () {
  const cfg = window.EARNINGS_PAGE || {};
  const loadingEl = document.getElementById("earningsLoading");
  const emptyEl = document.getElementById("earningsEmpty");
  const emptyTextEl = document.getElementById("earningsEmptyText");
  const timelineEl = document.getElementById("earningsTimeline");
  const countEl = document.getElementById("earningsCount");
  const metaEl = document.getElementById("earningsMeta");
  const settingsForm = document.getElementById("earningsSettingsForm");
  const settingsStatus = document.getElementById("settingsStatus");
  const refreshBtn = document.getElementById("refreshEarningsBtn");

  function providerLabel(provider) {
    const map = {
      eodhd: "EODHD",
      fmp: "FMP",
      cache: "缓存",
      none: "无",
    };
    return map[provider] || provider;
  }

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text == null ? "" : String(text);
    return div.innerHTML;
  }

  function cardClass(daysUntil) {
    if (daysUntil === 0) return "is-today";
    if (daysUntil <= 3) return "is-soon";
    return "";
  }

  function badgeClass(daysUntil) {
    if (daysUntil === 0) return "today";
    if (daysUntil <= 3) return "soon";
    return "";
  }

  function renderTimeline(events) {
    if (!events.length) {
      timelineEl.hidden = true;
      emptyEl.hidden = false;
      countEl.textContent = "0 场财报";
      return;
    }

    const byDate = {};
    events.forEach((ev) => {
      const d = ev.report_date;
      if (!byDate[d]) byDate[d] = [];
      byDate[d].push(ev);
    });
    const dates = Object.keys(byDate).sort();

    let html = "";
    dates.forEach((dateKey) => {
      html += `<div class="earnings-date-group">`;
      html += `<p class="earnings-date-group-title">${escapeHtml(dateKey)}</p>`;
      byDate[dateKey].forEach((ev) => {
        const daysUntil = ev.days_until ?? 0;
        const itemCls = cardClass(daysUntil);
        const badgeCls = badgeClass(daysUntil);
        const timePart = ev.report_time ? ` · ${escapeHtml(ev.report_time)}` : "";
        const fiscal = ev.fiscal_period
          ? `<span><span class="label">财季</span>${escapeHtml(ev.fiscal_period)}</span>`
          : "";
        const epsEst =
          ev.eps_estimate != null
            ? `<span><span class="label">EPS 预估</span>${ev.eps_estimate.toFixed(2)}</span>`
            : "";
        const epsAct =
          ev.eps_actual != null
            ? `<span><span class="label">EPS 实际</span>${ev.eps_actual.toFixed(2)}</span>`
            : "";

        html += `
          <article class="earnings-timeline-item ${itemCls}">
            <span class="earnings-timeline-dot" aria-hidden="true"></span>
            <div class="earnings-card">
              <div class="earnings-card-header">
                <span class="earnings-ticker">${escapeHtml(ev.ticker)}</span>
                <span class="earnings-badge ${badgeCls}">${escapeHtml(ev.days_label || "")}</span>
              </div>
              <p class="earnings-card-date">发布日 ${escapeHtml(ev.report_date)}${timePart}</p>
              <div class="earnings-card-details">
                ${fiscal}
                ${epsEst}
                ${epsAct}
              </div>
            </div>
          </article>
        `;
      });
      html += `</div>`;
    });

    timelineEl.innerHTML = html;
    timelineEl.hidden = false;
    emptyEl.hidden = true;
    countEl.textContent = `${events.length} 场财报`;
  }

  async function loadCalendar(refresh) {
    loadingEl.hidden = false;
    timelineEl.hidden = true;
    emptyEl.hidden = true;

    const horizon = document.getElementById("horizonDays")?.value || cfg.initialSettings?.horizon_days || 30;
    const url = new URL(cfg.calendarUrl, window.location.origin);
    url.searchParams.set("horizon_days", horizon);
    if (refresh) url.searchParams.set("refresh", "1");

    try {
      const res = await fetch(url);
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || "加载失败");
      }

      const provider = providerLabel(data.provider);
      const tickers = data.ticker_count ?? 0;
      metaEl.textContent = `数据源：${provider} · 跟踪 ${tickers} 只美股 · ${data.from_date} ~ ${data.to_date}`;

      if (data.message && !data.events?.length) {
        emptyTextEl.textContent = data.message;
        emptyEl.hidden = false;
        timelineEl.hidden = true;
        countEl.textContent = "0 场财报";
      } else {
        renderTimeline(data.events || []);
      }
    } catch (err) {
      emptyTextEl.textContent = err.message || "加载财报日历失败";
      emptyEl.hidden = false;
      timelineEl.hidden = true;
      countEl.textContent = "";
    } finally {
      loadingEl.hidden = true;
    }
  }

  settingsForm?.addEventListener("submit", async (e) => {
    e.preventDefault();
    settingsStatus.textContent = "正在保存…";
    settingsStatus.className = "earnings-settings-status";

    const body = {
      horizon_days: Number(document.getElementById("horizonDays").value),
      remind_days_before: Number(document.getElementById("remindDaysBefore").value),
      remind_enabled: document.getElementById("remindEnabled").checked,
    };

    try {
      const res = await fetch(cfg.settingsUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "保存失败");

      if (data.settings) {
        document.getElementById("horizonDays").value = data.settings.horizon_days;
        document.getElementById("remindDaysBefore").value = data.settings.remind_days_before;
        document.getElementById("remindEnabled").checked = data.settings.remind_enabled;
      }

      settingsStatus.textContent = "设置已保存";
      settingsStatus.className = "earnings-settings-status ok";
      await loadCalendar(false);
    } catch (err) {
      settingsStatus.textContent = err.message || "保存失败";
      settingsStatus.className = "earnings-settings-status err";
    }
  });

  refreshBtn?.addEventListener("click", () => loadCalendar(true));

  if (!cfg.apiConfigured) {
    metaEl.textContent = "未配置 EODHD 或 FMP API Key，请在 .env 中配置后重启应用。";
    loadingEl.hidden = true;
    emptyTextEl.textContent = "未配置行情/财报 API Key";
    emptyEl.hidden = false;
  } else {
    loadCalendar(false);
  }
})();
