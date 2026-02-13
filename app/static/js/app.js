/* StockPulse — app.js
   Global keyboard shortcuts and helper functions. */

document.addEventListener('DOMContentLoaded', function () {

  // ── Ctrl/Cmd+K → Global search ──
  document.addEventListener('keydown', function (e) {
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
      e.preventDefault();
      toggleSearch();
    }
    if (e.key === 'Escape') {
      closeSearch();
      closeAllModals();
    }
  });

  // ── Ticker-page tab shortcuts (1-7) ──
  document.addEventListener('keydown', function (e) {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return;
    var tabKeys = { '1': 0, '2': 1, '3': 2, '4': 3, '5': 4, '6': 5, '7': 6 };
    if (e.key in tabKeys) {
      var tabs = document.querySelectorAll('.sp-tab[data-tab]');
      if (tabs.length > 0 && tabKeys[e.key] < tabs.length) {
        tabs[tabKeys[e.key]].click();
      }
    }
    // R → Refresh (click refresh button if present)
    if (e.key === 'r' || e.key === 'R') {
      var refreshBtn = document.querySelector('[data-action="refresh"]');
      if (refreshBtn) {
        e.preventDefault();
        refreshBtn.click();
      }
    }
    // W → Add to watchlist (click watchlist button if present)
    if (e.key === 'w' || e.key === 'W') {
      var watchBtn = document.querySelector('[data-action="add-watchlist"]');
      if (watchBtn) {
        e.preventDefault();
        watchBtn.click();
      }
    }
  });
});

// ── Search modal ──
function toggleSearch() {
  var modal = document.getElementById('search-modal');
  if (!modal) return;
  if (modal.classList.contains('hidden')) {
    openSearch();
  } else {
    closeSearch();
  }
}

function openSearch() {
  var modal = document.getElementById('search-modal');
  if (!modal) return;
  modal.classList.remove('hidden');
  var input = modal.querySelector('input');
  if (input) {
    input.value = '';
    input.focus();
  }
}

function closeSearch() {
  var modal = document.getElementById('search-modal');
  if (modal) modal.classList.add('hidden');
}

function handleSearchInput(e) {
  var query = e.target.value.trim().toUpperCase();
  if (e.key === 'Enter' && query.length > 0) {
    window.location.href = '/ticker/' + encodeURIComponent(query);
    closeSearch();
  }
}

// ── Modal helpers ──
function closeAllModals() {
  document.querySelectorAll('.modal-overlay').forEach(function (el) {
    el.classList.add('hidden');
  });
}

function openModal(id) {
  var modal = document.getElementById(id);
  if (modal) modal.classList.remove('hidden');
}

function closeModal(id) {
  var modal = document.getElementById(id);
  if (modal) modal.classList.add('hidden');
}

// ── Number formatting helpers (available globally for inline use) ──
function formatPrice(val) {
  if (val == null || isNaN(val)) return 'N/A';
  return '$' + Number(val).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatPct(val) {
  if (val == null || isNaN(val)) return 'N/A';
  var prefix = val > 0 ? '+' : '';
  return prefix + Number(val).toFixed(1) + '%';
}

function formatLargeNum(val) {
  if (val == null || isNaN(val)) return 'N/A';
  var abs = Math.abs(val);
  if (abs >= 1e12) return '$' + (val / 1e12).toFixed(2) + 'T';
  if (abs >= 1e9) return '$' + (val / 1e9).toFixed(0) + 'B';
  if (abs >= 1e6) return (val / 1e6).toFixed(1) + 'M';
  return val.toLocaleString('en-US');
}

// ── HTMX event hooks ──
document.addEventListener('htmx:afterSwap', function (e) {
  // Re-initialize any dynamic content after HTMX swaps
});

document.addEventListener('htmx:responseError', function (e) {
  console.error('HTMX error:', e.detail.xhr.status, e.detail.xhr.statusText);
});
