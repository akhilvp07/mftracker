/* MFTracker — Main JS */

// Theme management
(function() {
  const root = document.documentElement;
  const saved = localStorage.getItem('mft-theme') || 'light';
  root.setAttribute('data-theme', saved);

  function updateIcon(theme) {
    const icon = document.getElementById('themeIcon');
    if (icon) icon.className = theme === 'dark' ? 'bi bi-sun' : 'bi bi-moon-stars';
  }

  document.addEventListener('DOMContentLoaded', function() {
    updateIcon(saved);
    const btn = document.getElementById('themeToggle');
    if (btn) {
      btn.addEventListener('click', function() {
        const current = root.getAttribute('data-theme');
        const next = current === 'dark' ? 'light' : 'dark';
        root.setAttribute('data-theme', next);
        localStorage.setItem('mft-theme', next);
        updateIcon(next);
      });
    }

    // Apply dark theme to Bootstrap form elements
    applyFormTheme(document.getAttribute ? document.documentElement.getAttribute('data-theme') : 'light');

    // Auto-dismiss success toasts after 4s
    document.querySelectorAll('.mft-toast[data-level="success"]').forEach(function(el) {
      setTimeout(function() {
        var bsAlert = bootstrap.Alert.getOrCreateInstance(el);
        if (bsAlert) bsAlert.close();
      }, 4000);
    });
  });

  function applyFormTheme(theme) {
    const inputs = document.querySelectorAll('input, select, textarea');
    inputs.forEach(function(el) {
      if (theme === 'dark') {
        if (!el.classList.contains('mft-input')) el.classList.add('mft-input');
      }
    });
  }
})();

// Format numbers with Indian comma system
function formatINR(num) {
  if (isNaN(num)) return '—';
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(num);
}

// Confirm dangerous actions
document.addEventListener('DOMContentLoaded', function() {
  // Animate stat values
  document.querySelectorAll('.stat-value').forEach(function(el, i) {
    el.style.animationDelay = (i * 0.05) + 's';
  });

  // Highlight rows based on gain/loss
  document.querySelectorAll('.holding-row').forEach(function(row) {
    const gainBadge = row.querySelector('.gain-badge');
    if (gainBadge) {
      row.style.transition = 'background 0.15s';
    }
  });
});
