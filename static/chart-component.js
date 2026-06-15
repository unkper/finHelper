/**
 * 轻量 ECharts 封装：挂载、更新、堆叠柱状图配置。
 */
(function (global) {
  const instances = new WeakMap();

  function resolveElement(target) {
    if (!target) return null;
    if (typeof target === "string") return document.getElementById(target);
    return target;
  }

  function mount(target, option, { replace = true } = {}) {
    const el = resolveElement(target);
    if (!el || !global.echarts) return null;
    let chart = instances.get(el);
    if (!chart) {
      chart = global.echarts.init(el);
      instances.set(el, chart);
    }
    chart.setOption(option, replace);
    return chart;
  }

  function dispose(target) {
    const el = resolveElement(target);
    if (!el) return;
    const chart = instances.get(el);
    if (chart) {
      chart.dispose();
      instances.delete(el);
    }
  }

  function resize(target) {
    const el = resolveElement(target);
    if (!el) return;
    const chart = instances.get(el);
    chart?.resize();
  }

  function resizeAll() {
    instances.forEach((chart, el) => {
      if (el.offsetParent !== null) chart.resize();
    });
  }

  /**
   * 堆叠柱状图 option。
   * @param {object} params
   * @param {string[]} params.categories x 轴类目（如日期）
   * @param {{ name: string, data: number[], color?: string }[]} params.series
   * @param {string} [params.yAxisName]
   * @param {(value: string) => string} [params.categoryLabelFormatter]
   */
  function stackedBarOption({
    categories = [],
    series = [],
    yAxisName = "",
    categoryLabelFormatter,
  } = {}) {
    const useZoom = categories.length > 45;
    const option = {
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "shadow" },
      },
      legend: { bottom: useZoom ? 28 : 0 },
      grid: {
        left: 48,
        right: 16,
        top: 24,
        bottom: useZoom ? 72 : 48,
      },
      xAxis: {
        type: "category",
        data: categories,
        axisLabel: {
          formatter: categoryLabelFormatter || ((value) => String(value || "")),
        },
      },
      yAxis: {
        type: "value",
        minInterval: 1,
        name: yAxisName,
      },
      series: series.map((item) => ({
        name: item.name,
        type: "bar",
        stack: "total",
        emphasis: { focus: "series" },
        itemStyle: item.color ? { color: item.color } : undefined,
        data: item.data || [],
      })),
    };
    if (useZoom) {
      option.dataZoom = [
        {
          type: "inside",
          start: Math.max(0, 100 - Math.round((45 / categories.length) * 100)),
          end: 100,
        },
        {
          type: "slider",
          height: 18,
          bottom: 4,
          start: Math.max(0, 100 - Math.round((45 / categories.length) * 100)),
          end: 100,
        },
      ];
    }
    return option;
  }

  global.FinChart = {
    mount,
    dispose,
    resize,
    resizeAll,
    stackedBarOption,
  };
})(window);
