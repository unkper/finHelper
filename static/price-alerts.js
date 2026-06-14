(function () {
  const cfg = window.PRICE_ALERTS_PAGE || {};
  let allAlerts = [];
  let filterTimer = null;

  function $(id) {
    return document.getElementById(id);
  }

  function formatPrice(value) {
    if (value == null || Number.isNaN(Number(value))) return "—";
    return `$${Number(value).toFixed(2)}`;
  }

  function formatTriggeredAt(value) {
    if (!value) return "从未";
    return String(value).replace("T", " ").slice(0, 16);
  }

  function directionLabel(direction) {
    return direction === "above" ? "涨至" : "跌至";
  }

  function updateSummary(summary) {
    $("summaryAlertCount").textContent = String(summary.alert_count ?? 0);
    $("summaryTickerCount").textContent = String(summary.ticker_count ?? 0);
    $("summaryThemeCount").textContent = String(summary.theme_count ?? 0);
    $("summaryTriggeredCount").textContent = String(summary.triggered_count ?? 0);
  }

  function updateBulkButton() {
    const checked = document.querySelectorAll(".alert-row-check:checked").length;
    $("deleteSelectedBtn").disabled = checked === 0;
    const selectAll = $("selectAllAlerts");
    if (selectAll) {
      const visible = document.querySelectorAll(".alert-row-check");
      selectAll.checked = visible.length > 0 && checked === visible.length;
      selectAll.indeterminate = checked > 0 && checked < visible.length;
    }
  }

  function renderTable(alerts) {
    const tbody = $("alertsTableBody");
    tbody.innerHTML = "";

    alerts.forEach((alert) => {
      const tr = document.createElement("tr");
      if (alert.is_triggered) tr.classList.add("is-triggered");

      const themeUrl = `${cfg.themeDetailPattern}${alert.theme_id}`;
      tr.innerHTML = `
        <td><input type="checkbox" class="alert-row-check" data-id="${alert.alert_id}"></td>
        <td><strong>${alert.ticker}</strong></td>
        <td><span class="alert-dir-tag ${alert.direction}">${directionLabel(alert.direction)}</span></td>
        <td>${formatPrice(alert.target_price)}</td>
        <td>${formatPrice(alert.current_price)}</td>
        <td><a class="alert-theme-link" href="${themeUrl}">${alert.theme_title}</a></td>
        <td class="alert-note" title="${(alert.note || "").replace(/"/g, "&quot;")}">${alert.note || "—"}</td>
        <td>${formatTriggeredAt(alert.last_triggered_at)}</td>
        <td>
          <div class="alert-row-actions">
            <a class="alert-btn-link" href="${themeUrl}">主题</a>
            <button type="button" class="alert-btn-link danger alert-delete-one" data-id="${alert.alert_id}">删除</button>
          </div>
        </td>
      `;
      tbody.appendChild(tr);
    });

    tbody.querySelectorAll(".alert-row-check").forEach((input) => {
      input.addEventListener("change", updateBulkButton);
    });
    tbody.querySelectorAll(".alert-delete-one").forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = Number(btn.dataset.id);
        if (Number.isFinite(id)) deleteAlerts([id]);
      });
    });
    updateBulkButton();
  }

  function setLoading(loading) {
    $("alertsLoading").hidden = !loading;
    if (loading) {
      $("alertsEmpty").hidden = true;
      $("alertsTablePanel").hidden = true;
    }
  }

  async function loadAlerts() {
    setLoading(true);
    const q = ($("alertFilter")?.value || "").trim();
    const params = new URLSearchParams();
    if (q) params.set("q", q);
    const url = params.toString() ? `${cfg.listUrl}?${params}` : cfg.listUrl;

    try {
      const response = await fetch(url);
      if (!response.ok) throw new Error("加载失败");
      const payload = await response.json();
      allAlerts = payload.alerts || [];
      updateSummary(payload.summary || {});

      setLoading(false);
      if (!allAlerts.length) {
        $("alertsEmpty").hidden = false;
        $("alertsTablePanel").hidden = true;
        return;
      }
      $("alertsEmpty").hidden = true;
      $("alertsTablePanel").hidden = false;
      renderTable(allAlerts);
    } catch (error) {
      setLoading(false);
      $("alertsEmpty").hidden = false;
      $("alertsEmpty").querySelector("p").textContent = "加载失败，请稍后重试。";
      console.error(error);
    }
  }

  async function saveSettings(event) {
    event.preventDefault();
    const status = $("settingsStatus");
    const hours = Number($("cooldownHours").value);
    status.textContent = "正在保存…";
    status.className = "price-alerts-settings-status";

    try {
      const response = await fetch(cfg.settingsUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cooldown_hours: hours }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "保存失败");
      $("cooldownHours").value = payload.settings.cooldown_hours;
      status.textContent = `已保存：触发后 ${payload.settings.cooldown_hours} 小时内不重复提醒`;
      status.className = "price-alerts-settings-status is-ok";
    } catch (error) {
      status.textContent = error.message || "保存失败";
      status.className = "price-alerts-settings-status is-error";
    }
  }

  async function deleteAlerts(ids) {
    if (!ids.length) return;
    const msg = ids.length === 1
      ? "确定删除这条价位告警？此操作不可恢复。"
      : `确定删除选中的 ${ids.length} 条价位告警？此操作不可恢复。`;
    if (!window.confirm(msg)) return;

    try {
      const response = await fetch(cfg.deleteUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ alert_ids: ids }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "删除失败");
      await loadAlerts();
    } catch (error) {
      window.alert(error.message || "删除失败");
    }
  }

  function getSelectedIds() {
    return [...document.querySelectorAll(".alert-row-check:checked")]
      .map((el) => Number(el.dataset.id))
      .filter((id) => Number.isFinite(id));
  }

  document.addEventListener("DOMContentLoaded", () => {
    if (!document.querySelector(".price-alerts-page")) return;
    if (cfg.activeTab && cfg.activeTab !== "price-alerts") return;

    $("cooldownSettingsForm")?.addEventListener("submit", saveSettings);
    $("refreshAlertsBtn")?.addEventListener("click", loadAlerts);
    $("deleteSelectedBtn")?.addEventListener("click", () => deleteAlerts(getSelectedIds()));

    $("selectAllAlerts")?.addEventListener("change", (event) => {
      const checked = event.target.checked;
      document.querySelectorAll(".alert-row-check").forEach((input) => {
        input.checked = checked;
      });
      updateBulkButton();
    });

    $("alertFilter")?.addEventListener("input", () => {
      clearTimeout(filterTimer);
      filterTimer = setTimeout(loadAlerts, 350);
    });

    loadAlerts();
  });
})();
