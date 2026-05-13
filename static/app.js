function refreshEntryTitles(container) {
  container.querySelectorAll(".entry-card").forEach((card, index) => {
    const title = card.querySelector(".entry-head strong");
    if (title) {
      title.textContent = `Account ${index + 1}`;
    }
  });
}

function createEntryCard() {
  const card = document.createElement("div");
  card.className = "entry-card entry-card--new";
  card.innerHTML = `
    <div class="entry-head">
      <strong>Account</strong>
      <button type="button" class="text-btn remove-entry-btn">Remove</button>
    </div>
    <div class="form-row four-col">
      <label>
        <span>Name</span>
        <input list="account-suggestions" type="text" name="account_name[]" placeholder="Bank or broker name" required>
      </label>
      <label>
        <span>Type</span>
        <select name="account_category[]">
          <option value="bank">Bank</option>
          <option value="broker">Broker</option>
        </select>
      </label>
      <label>
        <span>Currency</span>
        <select name="account_currency[]">
          <option value="CNY">CNY</option>
          <option value="HKD">HKD</option>
          <option value="USD">USD</option>
        </select>
      </label>
      <label>
        <span>Amount</span>
        <input type="number" step="0.01" name="amount[]" value="0" placeholder="0.00">
      </label>
    </div>
    <div class="tip-box">
      <span>Account memory</span>
      <p>Reuse a saved account or add a fresh one here.</p>
    </div>
  `;
  return card;
}

function initializeEntryEditor(containerId, addButtonId) {
  const container = document.getElementById(containerId);
  const addButton = document.getElementById(addButtonId);
  if (!container || !addButton) {
    return;
  }

  addButton.addEventListener("click", () => {
    const card = createEntryCard();
    container.appendChild(card);
    requestAnimationFrame(() => card.classList.remove("entry-card--new"));
    refreshEntryTitles(container);
  });

  container.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement) || !target.classList.contains("remove-entry-btn")) {
      return;
    }

    const cards = container.querySelectorAll(".entry-card");
    if (cards.length === 1) {
      cards[0].querySelectorAll("input").forEach((input) => {
        input.value = input.type === "number" ? "0" : "";
      });
      cards[0].querySelectorAll("select").forEach((select) => {
        select.selectedIndex = 0;
      });
      return;
    }

    target.closest(".entry-card")?.remove();
    refreshEntryTitles(container);
  });

  refreshEntryTitles(container);
}

function parseChartData(selector, attribute) {
  const element = document.querySelector(selector);
  if (!element) {
    return null;
  }
  const raw = element.getAttribute(attribute);
  if (!raw) {
    return null;
  }
  return {
    currency: element.getAttribute("data-currency") || "CNY",
    data: JSON.parse(raw),
  };
}

function setupCanvas(canvas) {
  const dpr = window.devicePixelRatio || 1;
  
  // 1. 从父元素获取宽度，高度固定为 280（或者从 dataset 读取一次）
  const parent = canvas.parentElement;
  const width = parent.clientWidth || 600;
  const height = 280; // 直接锁定逻辑高度，避免读取被缩放后的属性

  // 2. 计算物理像素（渲染分辨率）
  const targetWidth = Math.floor(width * dpr);
  const targetHeight = Math.floor(height * dpr);

  // 3. 只有尺寸变化时才重置，并强制锁定 CSS 样式
  if (canvas.width !== targetWidth || canvas.height !== targetHeight) {
    canvas.width = targetWidth;
    canvas.height = targetHeight;
    // 关键：锁定 CSS 尺寸，防止 Canvas 撑开父容器
    canvas.style.width = width + "px";
    canvas.style.height = height + "px";
  }

  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  
  // 4. 清除并重置缩放矩阵
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);
  
  return { ctx, width, height };
}

function animateValue(duration, drawFrame) {
  let start = null;
  function frame(now) {
    if (start === null) start = now;
    const progress = Math.min((now - start) / duration, 1);
    // 使用缓动函数让动画更自然
    const eased = 1 - Math.pow(1 - progress, 3);
    
    drawFrame(eased);
    
    if (progress < 1) {
      requestAnimationFrame(frame);
    }
  }
  requestAnimationFrame(frame);
}

function drawLineChart() {
  const payload = parseChartData(".chart-card[data-line-chart]", "data-line-chart");
  if (!payload) {
    return;
  }

  const canvas = document.getElementById("trend-chart");
  if (!(canvas instanceof HTMLCanvasElement)) {
    return;
  }

  const prepared = setupCanvas(canvas);
  if (!prepared) {
    return;
  }
  const { ctx, width, height } = prepared;
  const points = payload.data;
  if (!Array.isArray(points) || points.length === 0) {
    return;
  }

  const pad = { top: 24, right: 18, bottom: 34, left: 56 };
  const chartWidth = width - pad.left - pad.right;
  const chartHeight = height - pad.top - pad.bottom;
  const values = points.map((point) => Number(point.total));
  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const valueSpan = maxValue - minValue || Math.max(maxValue, 1);

  ctx.strokeStyle = "rgba(117, 97, 77, 0.18)";
  ctx.lineWidth = 1;
  for (let i = 0; i < 4; i += 1) {
    const y = pad.top + (chartHeight / 3) * i;
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(width - pad.right, y);
    ctx.stroke();
  }

  ctx.fillStyle = "#75614d";
  ctx.font = "12px Segoe UI";
  for (let i = 0; i < 4; i += 1) {
    const ratio = i / 3;
    const value = maxValue - valueSpan * ratio;
    const y = pad.top + chartHeight * ratio + 4;
    ctx.fillText(Number(value).toFixed(2), 10, y);
  }

  const coordinates = points.map((point, index) => {
    const x = pad.left + (chartWidth / Math.max(points.length - 1, 1)) * index;
    const y = pad.top + ((maxValue - Number(point.total)) / valueSpan) * chartHeight;
    return { x, y, label: point.snapshot_date };
  });

  const gradient = ctx.createLinearGradient(0, pad.top, 0, height - pad.bottom);
  gradient.addColorStop(0, "rgba(31, 111, 95, 0.22)");
  gradient.addColorStop(1, "rgba(31, 111, 95, 0.02)");

  ctx.beginPath();
  coordinates.forEach((point, index) => {
    if (index === 0) {
      ctx.moveTo(point.x, point.y);
    } else {
      ctx.lineTo(point.x, point.y);
    }
  });
  ctx.lineTo(coordinates[coordinates.length - 1].x, height - pad.bottom);
  ctx.lineTo(coordinates[0].x, height - pad.bottom);
  ctx.closePath();
  ctx.fillStyle = gradient;
  ctx.fill();

  ctx.beginPath();
  coordinates.forEach((point, index) => {
    if (index === 0) {
      ctx.moveTo(point.x, point.y);
    } else {
      ctx.lineTo(point.x, point.y);
    }
  });
  ctx.strokeStyle = "#1f6f5f";
  ctx.lineWidth = 3;
  ctx.stroke();

  coordinates.forEach((point) => {
    ctx.beginPath();
    ctx.arc(point.x, point.y, 4, 0, Math.PI * 2);
    ctx.fillStyle = "#ffffff";
    ctx.fill();
    ctx.strokeStyle = "#1f6f5f";
    ctx.lineWidth = 2;
    ctx.stroke();
  });

  ctx.fillStyle = "#75614d";
  ctx.font = "12px Segoe UI";
  coordinates.forEach((point) => {
    ctx.fillText(point.label.slice(5), point.x - 16, height - 10);
  });

  ctx.fillStyle = "#2f2419";
  ctx.font = "13px Segoe UI";
  ctx.fillText(`Total asset trend (${payload.currency})`, pad.left, 16);
}

function drawGrowthChart(progress = 1) {
  const payload = parseChartData(".chart-card[data-bar-chart]", "data-bar-chart");
  if (!payload) {
    return;
  }

  const canvas = document.getElementById("growth-chart");
  if (!(canvas instanceof HTMLCanvasElement)) {
    return;
  }

  const prepared = setupCanvas(canvas);
  if (!prepared) {
    return;
  }
  const { ctx, width, height } = prepared;
  const rows = payload.data;
  if (!Array.isArray(rows) || rows.length === 0) {
    return;
  }

  const pad = { top: 26, right: 18, bottom: 42, left: 64 };
  const chartWidth = width - pad.left - pad.right;
  const chartHeight = height - pad.top - pad.bottom;
  const values = rows.map((row) => Number(row.growth_per_day));
  const maxAbsValue = Math.max(...values.map((value) => Math.abs(value)), 1);
  const zeroY = pad.top + chartHeight / 2;
  const barWidth = Math.min(42, chartWidth / Math.max(rows.length * 1.8, 1));

  ctx.strokeStyle = "rgba(117, 97, 77, 0.18)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(pad.left, zeroY);
  ctx.lineTo(width - pad.right, zeroY);
  ctx.stroke();

  ctx.fillStyle = "#75614d";
  ctx.font = "12px Segoe UI";
  ctx.fillText(maxAbsValue.toFixed(2), 10, pad.top + 6);
  ctx.fillText("0.00", 18, zeroY + 4);
  ctx.fillText((-maxAbsValue).toFixed(2), 10, height - pad.bottom);

  rows.forEach((row, index) => {
    const x = pad.left + ((index + 0.5) * chartWidth) / rows.length;
    const value = Number(row.growth_per_day) * progress;
    const heightRatio = Math.abs(value) / maxAbsValue;
    const barHeight = heightRatio * (chartHeight / 2);
    const barX = x - barWidth / 2;
    const barY = value >= 0 ? zeroY - barHeight : zeroY;

    ctx.fillStyle = value >= 0 ? "rgba(31, 111, 95, 0.82)" : "rgba(215, 102, 54, 0.78)";
    ctx.fillRect(barX, barY, barWidth, Math.max(barHeight, 2));

    ctx.fillStyle = "#75614d";
    ctx.font = "11px Segoe UI";
    ctx.fillText(row.snapshot_date.slice(5), x - 16, height - 14);
  });

  ctx.fillStyle = "#2f2419";
  ctx.font = "13px Segoe UI";
  ctx.fillText(`Daily growth (${payload.currency}/day)`, pad.left, 16);
}

function animateGrowthChart() {
  animateValue(700, (progress) => drawGrowthChart(progress));
}

function getPieColors(length) {
  const palette = ["#d76636", "#1d7d74", "#3957b8", "#d2a138", "#7854a1", "#5b7f28", "#bb4f74"];
  return Array.from({ length }, (_, index) => palette[index % palette.length]);
}

function drawPieChart(snapshotId, progress = 1) {
  const payload = parseChartData(".chart-card[data-pie-chart]", "data-pie-chart");
  if (!payload) {
    return;
  }

  const canvas = document.getElementById("pie-chart");
  const legend = document.getElementById("pie-legend");
  if (!(canvas instanceof HTMLCanvasElement) || !(legend instanceof HTMLElement)) {
    return;
  }

  const selected = payload.data.find((item) => String(item.snapshot_id) === String(snapshotId)) || payload.data[0];
  if (!selected || !Array.isArray(selected.values) || selected.values.length === 0) {
    legend.innerHTML = "<p class='chart-empty'>No composition data is available for this date.</p>";
    return;
  }

  const prepared = setupCanvas(canvas);
  if (!prepared) {
    return;
  }
  const { ctx, width, height } = prepared;

  const total = selected.values.reduce((sum, item) => sum + Number(item.value), 0);
  const radius = Math.min(width, height) * 0.23;
  const centerX = width * 0.34;
  const centerY = height * 0.5;
  const colors = getPieColors(selected.values.length);
  let startAngle = -Math.PI / 2;

  selected.values.forEach((item, index) => {
    const ratio = Number(item.value) / total;
    const endAngle = startAngle + Math.PI * 2 * ratio * progress;
    ctx.beginPath();
    ctx.moveTo(centerX, centerY);
    ctx.arc(centerX, centerY, radius, startAngle, endAngle);
    ctx.closePath();
    ctx.fillStyle = colors[index];
    ctx.fill();
    startAngle += Math.PI * 2 * ratio;
  });

  ctx.beginPath();
  ctx.arc(centerX, centerY, radius * 0.58, 0, Math.PI * 2);
  ctx.fillStyle = "#fffaf2";
  ctx.fill();
  ctx.fillStyle = "#2f2419";
  ctx.font = "bold 15px Segoe UI";
  ctx.textAlign = "center";
  ctx.fillText(selected.snapshot_date, centerX, centerY - 3);
  ctx.font = "12px Segoe UI";
  ctx.fillStyle = "#75614d";
  ctx.fillText(payload.currency, centerX, centerY + 16);
  ctx.textAlign = "start";

  legend.innerHTML = "";
  selected.values.forEach((item, index) => {
    const row = document.createElement("div");
    row.className = "legend-row legend-row--fade";
    row.style.animationDelay = `${index * 45}ms`;
    const ratio = ((Number(item.value) / total) * 100).toFixed(1);
    row.innerHTML = `
      <span class="legend-dot" style="background:${colors[index]}"></span>
      <span class="legend-label">${item.label}</span>
      <span class="legend-value">${Number(item.value).toFixed(2)} ${payload.currency} (${ratio}%)</span>
    `;
    legend.appendChild(row);
  });
}

function animatePieChart(snapshotId) {
  animateValue(620, (progress) => drawPieChart(snapshotId, progress));
}

document.addEventListener("DOMContentLoaded", () => {
  initializeEntryEditor("entries-container", "add-entry-btn");
  initializeEntryEditor("edit-entries-container", "add-edit-entry-btn");

  drawLineChart();
  animateGrowthChart();

  const pieSelector = document.getElementById("pie-date-selector");
  if (pieSelector instanceof HTMLSelectElement) {
    animatePieChart(pieSelector.value);
    pieSelector.addEventListener("change", () => animatePieChart(pieSelector.value));
  } else {
    animatePieChart();
  }

  window.addEventListener("resize", () => {
    drawLineChart();
    drawGrowthChart(1);
    if (pieSelector instanceof HTMLSelectElement) {
      drawPieChart(pieSelector.value, 1);
    } else {
      drawPieChart(undefined, 1);
    }
  });
});
