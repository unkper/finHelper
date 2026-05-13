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

// 全局保存图表实例，方便在 resize 时调用
let lineChartInstance = null;
let growthChartInstance = null;
let pieChartInstance = null;

// 你之前的 drawLineChart 稍微修改一下，保存到全局变量
function drawLineChart() {
    var chartDom = document.getElementById('trendChart');
    if (!chartDom) return;
    if (!lineChartInstance) lineChartInstance = echarts.init(chartDom);

    var cardElement = document.querySelector('.chart-card[data-line-chart]');
    var rawData = cardElement.getAttribute('data-line-chart');
    var trendData = JSON.parse(rawData);
    var currency = cardElement.getAttribute('data-currency') || '';

    const dates = trendData.map(item => item.snapshot_date);
    const amounts = trendData.map(item => item.total);

    var option = {
        tooltip: { trigger: 'axis', formatter: '{b} <br/> 总计: {c} ' + currency },
        grid: { left: '5%', right: '5%', bottom: '15%', containLabel: true },
        xAxis: { type: 'category', data: dates },
        yAxis: { type: 'value' },
        dataZoom: [ { type: 'inside', start: 0, end: 100 }, { type: 'slider', start: 0, end: 100 } ],
        series: [{ type: 'line', data: amounts, symbolSize: 8, itemStyle: { color: '#c28e5c' } }]
    };
    lineChartInstance.setOption(option);
}

// 柱状图渲染函数（替换原有逻辑）
function drawGrowthChart() {
    var chartDom = document.getElementById('growthChart');
    if (!chartDom) return;
    if (!growthChartInstance) growthChartInstance = echarts.init(chartDom);

    var cardElement = document.querySelector('.chart-card[data-bar-chart]');
    var rawData = cardElement.getAttribute('data-bar-chart');
    var growthData = JSON.parse(rawData);
    var currency = cardElement.getAttribute('data-currency') || '';

    // 截取日期的后半部分，跟原本的逻辑保持一致 (比如 2023-10-10 变成 10-10)
    const dates = growthData.map(item => item.snapshot_date.slice(5));
    const values = growthData.map(item => Number(item.growth_per_day));

    var option = {
        tooltip: {
            trigger: 'axis',
            formatter: '{b} <br/> 变化: {c} ' + currency + ' / day'
        },
        grid: { left: '5%', right: '5%', bottom: '15%', containLabel: true },
        dataZoom: [ { type: 'inside', start: 0, end: 100 }, { type: 'slider', start: 0, end: 100 } ],
        xAxis: { type: 'category', data: dates },
        yAxis: { type: 'value' },
        series: [{
            type: 'bar',
            data: values,
            itemStyle: {
                // 如果大于等于0用绿色，小于0用红色（原项目的颜色风格）
                color: function(params) {
                    return params.value >= 0 ? '#1f6f5f' : '#d76636';
                },
                borderRadius: [4, 4, 0, 0] // 让柱子顶部稍微圆润一点
            }
        }]
    };
    growthChartInstance.setOption(option);
}

// 饼图渲染函数（替换原有逻辑）
function drawPieChart(snapshotId) {
    var chartDom = document.getElementById('pieChart');
    if (!chartDom) return;
    if (!pieChartInstance) pieChartInstance = echarts.init(chartDom);

    var cardElement = document.querySelector('.chart-card[data-pie-chart]');
    var rawData = cardElement.getAttribute('data-pie-chart');
    var payloadData = JSON.parse(rawData);
    var currency = cardElement.getAttribute('data-currency') || '';

    // 找到当前选中日期的数据，找不到就默认拿第一条
    const selected = payloadData.find((item) => String(item.snapshot_id) === String(snapshotId)) || payloadData[0];

    if (!selected || !selected.values || selected.values.length === 0) {
        pieChartInstance.clear(); // 没有数据就清空
        return;
    }

    // 格式化为 ECharts 饼图需要的结构: [{name: 'xxx', value: 123}, ...]
    const pieData = selected.values.map(item => ({
        name: item.label,
        value: Number(item.value)
    }));

    var option = {
        tooltip: {
            trigger: 'item',
            // {b}: 名字, {c}: 金额, {d}: 百分比
            formatter: '{b}: {c} ' + currency + ' ({d}%)'
        },
        // ECharts 自带右侧图例，完美替代你原来手写的 HTML legend
        legend: {
            type: 'scroll', // 图例如果太多可以滚动
            orient: 'vertical',
            right: 0,
            top: 'center'
        },
        series: [
            {
                name: 'Composition',
                type: 'pie',
                radius: ['45%', '75%'], // 环形图设计（类似你原来画的中间空心的圆）
                center: ['35%', '50%'], // 整体向左偏移，给右侧的图例让出空间
                avoidLabelOverlap: false,
                label: { show: false }, // 隐藏折线引出的文字，保持卡片干净
                data: pieData,
                itemStyle: {
                    borderColor: '#fff',
                    borderWidth: 2
                }
            }
        ]
    };
    pieChartInstance.setOption(option);
}

function animateGrowthChart() {
  animateValue(700, (progress) => drawGrowthChart(progress));
}

function getPieColors(length) {
  const palette = ["#d76636", "#1d7d74", "#3957b8", "#d2a138", "#7854a1", "#5b7f28", "#bb4f74"];
  return Array.from({ length }, (_, index) => palette[index % palette.length]);
}

function animatePieChart(snapshotId) {
  animateValue(620, (progress) => drawPieChart(snapshotId, progress));
}

document.addEventListener("DOMContentLoaded", () => {
    initializeEntryEditor("entries-container", "add-entry-btn");
    initializeEntryEditor("edit-entries-container", "add-edit-entry-btn");

    // 1. 初始化所有图表
    drawLineChart();
    drawGrowthChart();

    // 2. 初始化饼图，并监听下拉框切换事件
    const pieSelector = document.getElementById("pie-date-selector");
    if (pieSelector) {
        drawPieChart(pieSelector.value); // 页面加载时画一次
        pieSelector.addEventListener("change", () => {
            // 切换日期时，ECharts 会自动生成极其丝滑的数据变形过渡动画！
            drawPieChart(pieSelector.value);
        });
    } else {
        drawPieChart();
    }

    // 3. 屏幕大小调整时，自动重绘图表，实现响应式
    window.addEventListener("resize", () => {
        if (lineChartInstance) lineChartInstance.resize();
        if (growthChartInstance) growthChartInstance.resize();
        if (pieChartInstance) pieChartInstance.resize();
    });
});
