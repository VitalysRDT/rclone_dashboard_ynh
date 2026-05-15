/* rclone Dashboard - Alpine component */
function dashboard() {
  return {
    snap: null,
    health: {},
    active: localStorage.getItem('rcd-active-tab') || 'overview',
    tabs: [
      { id: 'overview', label: 'Overview' },
      { id: 'transfers', label: 'Transfers' },
      { id: 'cache', label: 'Cache' },
      { id: 'health', label: 'Health' },
    ],
    theme: localStorage.getItem('rcd-theme') || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'),
    connected: false,
    backoff: 0,
    pollHandle: null,
    chart: null,
    histHours: parseInt(localStorage.getItem('rcd-hist-hours') || '24', 10),
    _pollIntervalBase: parseInt(document.documentElement.dataset.pollInterval || '2000', 10),

    init() {
      this.applyTheme();
      this.$watch('active', v => localStorage.setItem('rcd-active-tab', v));
      this.fetchHealth();
      this.pollSnap();
      this.fetchHistory();
      setInterval(() => this.fetchHealth(), 30_000);
      setInterval(() => this.fetchHistory(), 60_000);
    },

    applyTheme() {
      document.documentElement.dataset.theme = this.theme;
    },
    toggleTheme() {
      this.theme = this.theme === 'dark' ? 'light' : 'dark';
      localStorage.setItem('rcd-theme', this.theme);
      this.applyTheme();
    },

    async pollSnap() {
      try {
        const r = await fetch('api/snapshot');
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        this.snap = await r.json();
        this.connected = true;
        this.backoff = 0;
      } catch (e) {
        this.connected = false;
        this.backoff = Math.min((this.backoff || this._pollIntervalBase) * 1.8, 30_000);
      }
      const next = this.connected ? this._pollIntervalBase : this.backoff + Math.random() * 500;
      clearTimeout(this.pollHandle);
      this.pollHandle = setTimeout(() => this.pollSnap(), next);
    },

    async fetchHealth() {
      try {
        const r = await fetch('api/health');
        this.health = await r.json();
      } catch (e) {}
    },

    setHist(h) {
      this.histHours = h;
      localStorage.setItem('rcd-hist-hours', h);
      this.fetchHistory();
    },

    async fetchHistory() {
      try {
        const r = await fetch(`api/history.json?hours=${this.histHours}`);
        const j = await r.json();
        this.renderChart(j.points);
      } catch (e) {}
    },

    renderChart(points) {
      const ctx = document.getElementById('history-chart');
      if (!ctx) return;
      const labels = points.map(p => new Date(p.ts * 1000).toLocaleTimeString());
      const speeds = points.map(p => p.speed_bps / 1024 / 1024);
      const cache = points.map(p => p.cache_used_bytes / 1024 / 1024 / 1024);
      const data = {
        labels,
        datasets: [
          {
            label: 'Speed (MB/s)',
            data: speeds,
            borderColor: 'rgb(99, 102, 241)',
            backgroundColor: 'rgba(99, 102, 241, 0.1)',
            yAxisID: 'y',
            tension: 0.25,
            fill: true,
            pointRadius: 0,
            borderWidth: 2,
          },
          {
            label: 'Cache (GB)',
            data: cache,
            borderColor: 'rgb(244, 114, 182)',
            backgroundColor: 'transparent',
            yAxisID: 'y1',
            tension: 0.25,
            fill: false,
            pointRadius: 0,
            borderWidth: 1.5,
            borderDash: [4, 4],
          }
        ]
      };
      const opts = {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { labels: { color: 'rgb(160, 160, 180)', boxWidth: 12 } },
          tooltip: { backgroundColor: 'rgba(0,0,0,0.85)', titleColor: '#fff', bodyColor: '#ddd' }
        },
        scales: {
          x: { ticks: { color: 'rgb(120, 120, 140)', maxRotation: 0, autoSkipPadding: 30 }, grid: { color: 'rgba(120,120,140,0.08)' } },
          y: { type: 'linear', position: 'left', ticks: { color: 'rgb(99,102,241)' }, grid: { color: 'rgba(120,120,140,0.08)' }, title: { display: true, text: 'MB/s', color: 'rgb(99,102,241)' } },
          y1: { type: 'linear', position: 'right', ticks: { color: 'rgb(244,114,182)' }, grid: { drawOnChartArea: false }, title: { display: true, text: 'GB', color: 'rgb(244,114,182)' } }
        }
      };
      if (this.chart) {
        this.chart.data = data;
        this.chart.options = opts;
        this.chart.update('none');
      } else {
        this.chart = new Chart(ctx, { type: 'line', data, options: opts });
      }
    },

    cacheRatio() {
      const used = this.snap?.vfs?.diskCache?.bytesUsed || 0;
      const limit = this.snap?.vfs?.opt?.CacheMaxSize || 0;
      if (!limit) return 0;
      return Math.round((used / limit) * 100);
    },

    fmtSpeed(bps) {
      if (!bps || bps <= 0) return '—';
      const mb = bps / 1024 / 1024;
      if (mb >= 1) return `${mb.toFixed(1)} MB/s`;
      return `${(bps / 1024).toFixed(0)} KB/s`;
    },
    fmtBytes(n) {
      if (!n) return '0 B';
      const u = ['B','KB','MB','GB','TB','PB'];
      let i = 0;
      while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
      return `${n.toFixed(i === 0 ? 0 : 1)} ${u[i]}`;
    },
    fmtDuration(s) {
      if (!s || s <= 0) return '—';
      if (s < 60) return `${s}s`;
      if (s < 3600) return `${Math.floor(s/60)}m`;
      return `${Math.floor(s/3600)}h ${Math.floor((s%3600)/60)}m`;
    },
    fmtNs(ns) {
      if (!ns) return '—';
      const s = ns / 1e9;
      if (s < 60) return `${s.toFixed(0)}s`;
      if (s < 3600) return `${(s/60).toFixed(0)}m`;
      if (s < 86400) return `${(s/3600).toFixed(0)}h`;
      return `${(s/86400).toFixed(1)}d`;
    },
    basename(p) { return (p || '').split('/').pop() || p; },
    dirname(p) { const parts = (p || '').split('/'); parts.pop(); return parts.join('/') || '.'; },
    cacheModeName(m) { return ['off','minimal','writes','full'][m] || `mode ${m}`; },
  };
}
