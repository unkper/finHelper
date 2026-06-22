(function () {
  const cfg = window.FINANCIAL_REPORT_PAGE || {};

  const editModal = document.getElementById("editReportModal");
  const editForm = document.getElementById("editReportForm");
  const editCalYear = document.getElementById("editCalYear");
  const editCalQuarter = document.getElementById("editCalQuarter");
  const editFiscalPeriodHidden = document.getElementById("editFiscalPeriodHidden");

  function populateEditYearOptions() {
    if (!editCalYear) return;
    const now = new Date().getFullYear();
    editCalYear.innerHTML = "";
    for (let y = now + 1; y >= now - 7; y -= 1) {
      const opt = document.createElement("option");
      opt.value = String(y);
      opt.textContent = String(y);
      editCalYear.appendChild(opt);
    }
  }

  function parseFiscalPeriod(period) {
    const match = String(period || "").trim().toUpperCase().match(/^(\d{4})-(Q[1-4])$/);
    if (!match) return null;
    return { year: match[1], quarter: match[2] };
  }

  function syncEditFiscalPeriodHidden() {
    if (!editFiscalPeriodHidden || !editCalYear || !editCalQuarter) return;
    editFiscalPeriodHidden.value = `${editCalYear.value}-${editCalQuarter.value}`;
  }

  function initEditPeriodFromReport() {
    const parsed = parseFiscalPeriod(cfg.fiscalPeriod || editFiscalPeriodHidden?.value);
    if (!parsed) return;
    if (editCalYear) editCalYear.value = parsed.year;
    if (editCalQuarter) editCalQuarter.value = parsed.quarter;
    syncEditFiscalPeriodHidden();
  }

  function openEditModal() {
    initEditPeriodFromReport();
    if (editModal) editModal.hidden = false;
  }

  function closeEditModal() {
    if (editModal) editModal.hidden = true;
  }

  populateEditYearOptions();
  initEditPeriodFromReport();
  editCalYear?.addEventListener("change", syncEditFiscalPeriodHidden);
  editCalQuarter?.addEventListener("change", syncEditFiscalPeriodHidden);

  document.getElementById("editReportMetaBtn")?.addEventListener("click", openEditModal);
  document.getElementById("closeEditReportModal")?.addEventListener("click", closeEditModal);
  document.getElementById("cancelEditReport")?.addEventListener("click", closeEditModal);

  editForm?.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!cfg.editUrl) return;
    syncEditFiscalPeriodHidden();
    const fd = new FormData(editForm);
    const payload = {
      ticker: fd.get("ticker"),
      fiscal_period: fd.get("fiscal_period"),
      title: fd.get("title"),
      report_date: fd.get("report_date") || null,
    };
    try {
      const res = await fetch(cfg.editUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "保存失败");
      window.location.reload();
    } catch (err) {
      alert(err.message || "保存失败");
    }
  });

  document.getElementById("deleteReportBtn")?.addEventListener("click", async () => {
    if (!cfg.deleteUrl) return;
    const msg =
      cfg.parseStatus === "failed"
        ? "确定删除该报告？解析失败的记录将被永久移除（含已上传 PDF）。"
        : "确定删除该报告？将永久移除分析数据与 PDF 文件，且不可恢复。";
    if (!window.confirm(msg)) return;
    try {
      const res = await fetch(cfg.deleteUrl, { method: "POST" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "删除失败");
      window.location.href = cfg.listUrl || "/investments/research?tab=analysis";
    } catch (err) {
      alert(err.message || "删除失败");
    }
  });
})();
