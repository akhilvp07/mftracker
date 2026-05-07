/* MFTracker — Main JS */

document.addEventListener('DOMContentLoaded', function() {
  // Apply dark theme to Bootstrap form elements
  const inputs = document.querySelectorAll('input, select, textarea');
  inputs.forEach(function(el) {
    if (!el.classList.contains('mft-input')) el.classList.add('mft-input');
  });

  // Auto-dismiss success toasts after 4s
  document.querySelectorAll('.mft-toast[data-level="success"]').forEach(function(el) {
    setTimeout(function() {
      var bsAlert = bootstrap.Alert.getOrCreateInstance(el);
      if (bsAlert) bsAlert.close();
    }, 4000);
  });
});

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
