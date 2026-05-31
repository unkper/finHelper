(function () {
  const cfg = window.FINANCIAL_REPORT_PAGE || {};

  const editModal = document.getElementById("editReportModal");
  const editForm = document.getElementById("editReportForm");

  function openEditModal() {
    if (editModal) editModal.hidden = false;
  }

  function closeEditModal() {
    if (editModal) editModal.hidden = true;
  }

  document.getElementById("editReportMetaBtn")?.addEventListener("click", openEditModal);
  document.getElementById("closeEditReportModal")?.addEventListener("click", closeEditModal);
  document.getElementById("cancelEditReport")?.addEventListener("click", closeEditModal);

  editForm?.querySelector('[name="fiscal_period"]')?.addEventListener("blur", (e) => {
    if (e.target?.value) e.target.value = e.target.value.trim().toUpperCase();
  });

  editForm?.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!cfg.editUrl) return;
    const periodEl = editForm.querySelector('[name="fiscal_period"]');
    if (periodEl?.value) periodEl.value = periodEl.value.trim().toUpperCase();
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
