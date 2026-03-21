document.addEventListener('alpine:init', () => {
  Alpine.directive('sort-table', (el) => {
    let sortCol = -1, sortAsc = true;
    const headers = el.querySelectorAll('th[data-sort]');

    function parseValue(cell, type) {
      const text = cell.textContent.trim();
      if (type === 'badge') {
        const b = cell.querySelector('.badge');
        return (b ? b.textContent.trim() : text).toLowerCase();
      }
      if (type === 'string') return text.toLowerCase();
      if (type === 'number') {
        const m = text.match(/-?\d+(\.\d+)?/);
        return m ? parseFloat(m[0]) : 0;
      }
      if (type === 'date') {
        if (!text || text === '--') return 0;
        // DD/MM/YYYY HH:MM:SS
        const dmy = text.match(/(\d{2})\/(\d{2})\/(\d{4})\s+(\d{2}):(\d{2}):(\d{2})/);
        if (dmy) return new Date(dmy[3], dmy[2] - 1, dmy[1], dmy[4], dmy[5], dmy[6]).getTime();
        // YYYY-MM-DD HH:MM(:SS)
        const ymd = text.match(/(\d{4})-(\d{2})-(\d{2})[\sT]+(\d{2}):(\d{2})(?::(\d{2}))?/);
        if (ymd) return new Date(ymd[1], ymd[2] - 1, ymd[3], ymd[4], ymd[5], ymd[6] || 0).getTime();
        return 0;
      }
      if (type === 'duration') {
        if (!text || text === '--' || text.includes('in progress') || text.includes('waiting')) return -1;
        let sec = 0;
        const h = text.match(/(\d+)\s*h/), m = text.match(/(\d+)\s*m/), s = text.match(/(\d+)\s*s/);
        if (h) sec += parseInt(h[1]) * 3600;
        if (m) sec += parseInt(m[1]) * 60;
        if (s) sec += parseInt(s[1]);
        return sec;
      }
      if (type === 'size') {
        if (!text || text === '--') return 0;
        const m = text.match(/([\d.]+)\s*(B|KB|MB|GB|TB)/i);
        if (!m) return 0;
        const val = parseFloat(m[1]);
        const units = { B: 1, KB: 1024, MB: 1048576, GB: 1073741824, TB: 1099511627776 };
        return val * (units[m[2].toUpperCase()] || 1);
      }
      return text.toLowerCase();
    }

    headers.forEach((th) => {
      th.addEventListener('click', () => {
        const colIdx = Array.from(th.parentElement.children).indexOf(th);
        const type = th.dataset.sort;
        if (sortCol === colIdx) { sortAsc = !sortAsc; } else { sortCol = colIdx; sortAsc = true; }
        // Update indicators
        headers.forEach(h => {
          let ind = h.querySelector('.sort-indicator');
          if (ind) ind.remove();
        });
        const arrow = document.createElement('span');
        arrow.className = 'sort-indicator';
        arrow.textContent = sortAsc ? ' \u25B2' : ' \u25BC';
        th.appendChild(arrow);
        // Sort rows
        const tbody = el.querySelector('tbody');
        const rows = Array.from(tbody.querySelectorAll('tr'));
        rows.sort((a, b) => {
          const cellA = a.cells[colIdx], cellB = b.cells[colIdx];
          if (!cellA || !cellB) return 0;
          const va = parseValue(cellA, type), vb = parseValue(cellB, type);
          let cmp = 0;
          if (typeof va === 'number' && typeof vb === 'number') cmp = va - vb;
          else cmp = String(va).localeCompare(String(vb));
          return sortAsc ? cmp : -cmp;
        });
        rows.forEach(r => tbody.appendChild(r));
      });
    });
  });
});
