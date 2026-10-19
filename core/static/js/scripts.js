document.addEventListener('DOMContentLoaded', function () {
  // Confirm before destructive actions (delete links)
  document.querySelectorAll('a.confirm-delete').forEach(function (el) {
    el.addEventListener('click', function (e) {
      if (!confirm('Are you sure you want to delete this item? This cannot be undone.')) {
        e.preventDefault();
      }
    });
  });

  // Mobile sidebar toggle
  var toggle = document.querySelector('.nav-toggle');
  var sidebar = document.querySelector('.sidebar');
  if (toggle && sidebar) {
    toggle.addEventListener('click', function () {
      sidebar.classList.toggle('open');
    });
    document.addEventListener('click', function (e) {
      if (sidebar.classList.contains('open') && !sidebar.contains(e.target) && !toggle.contains(e.target)) {
        sidebar.classList.remove('open');
      }
    });
  }

  // Auto-fade success/info flash messages after a few seconds
  document.querySelectorAll('.msg.success, .msg.info').forEach(function (el) {
    setTimeout(function () {
      el.style.transition = 'opacity .4s ease';
      el.style.opacity = '0';
      setTimeout(function () { el.remove(); }, 400);
    }, 4000);
  });

  // ---------------- Dark mode toggle (persisted) ----------------
  var themeBtn = document.getElementById('theme-toggle');
  var root = document.documentElement;
  var savedTheme = localStorage.getItem('ums-theme');
  if (savedTheme === 'dark') {
    root.classList.add('dark');
    if (themeBtn) themeBtn.textContent = '☀️';
  }
  if (themeBtn) {
    themeBtn.addEventListener('click', function () {
      var isDark = root.classList.toggle('dark');
      localStorage.setItem('ums-theme', isDark ? 'dark' : 'light');
      themeBtn.textContent = isDark ? '☀️' : '🌙';
    });
  }

  // ---------------- Quick client-side table filter ----------------
  // Add data-table-filter="tableSelector" to a text input to enable.
  document.querySelectorAll('[data-table-filter]').forEach(function (input) {
    var table = document.querySelector(input.getAttribute('data-table-filter'));
    if (!table) return;
    input.addEventListener('input', function () {
      var term = input.value.trim().toLowerCase();
      table.querySelectorAll('tbody tr').forEach(function (row) {
        row.style.display = row.textContent.toLowerCase().includes(term) ? '' : 'none';
      });
    });
  });

  // ---------------- Simple client-side password strength meter ----------------
  // Add class "js-password-strength" to a password <input> and a sibling
  // element with id matching input's data-meter attribute to enable.
  document.querySelectorAll('input.js-password-strength').forEach(function (input) {
    var meter = document.getElementById(input.getAttribute('data-meter'));
    if (!meter) return;
    input.addEventListener('input', function () {
      var val = input.value;
      var score = 0;
      if (val.length >= 8) score++;
      if (/[A-Z]/.test(val)) score++;
      if (/[0-9]/.test(val)) score++;
      if (/[^A-Za-z0-9]/.test(val)) score++;
      var labels = ['Too weak', 'Weak', 'Fair', 'Good', 'Strong'];
      var colors = ['#dc2626', '#dc2626', '#d97706', '#2563eb', '#16a34a'];
      meter.textContent = val ? labels[score] : '';
      meter.style.color = colors[score];
    });
  });

  // ---------------- Copy-to-clipboard buttons (payment account numbers etc) ----------------
  document.querySelectorAll('.copy-btn[data-copy]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var text = btn.getAttribute('data-copy');
      var done = function () {
        var original = btn.textContent;
        btn.textContent = 'Copied!';
        btn.classList.add('copied');
        setTimeout(function () {
          btn.textContent = original;
          btn.classList.remove('copied');
        }, 1500);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done).catch(function () {
          window.prompt('Copy this manually:', text);
        });
      } else {
        window.prompt('Copy this manually:', text);
      }
    });
  });

  // ---------------- Password visibility toggle ----------------
  document.querySelectorAll('input[type="password"]:not([data-no-toggle])').forEach(function (input) {
    if (input.closest('.password-field-wrap')) return;
    var wrap = document.createElement('div');
    wrap.className = 'password-field-wrap';
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);

    var toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'password-toggle-btn';
    toggle.setAttribute('aria-label', 'Show password');
    toggle.textContent = '👁️';
    wrap.appendChild(toggle);

    toggle.addEventListener('click', function () {
      var showing = input.type === 'text';
      input.type = showing ? 'password' : 'text';
      toggle.textContent = showing ? '👁️' : '🙈';
      toggle.setAttribute('aria-label', showing ? 'Show password' : 'Hide password');
    });
  });

  // ---------------- Toast helper for JS-triggered notifications ----------------
  window.umsToast = function (message, type) {
    var container = document.querySelector('.msgs') || (function () {
      var el = document.createElement('div');
      el.className = 'msgs';
      var main = document.querySelector('main.main');
      if (main) main.prepend(el);
      return el;
    })();
    var div = document.createElement('div');
    div.className = 'msg ' + (type || 'info');
    div.textContent = message;
    container.appendChild(div);
    setTimeout(function () {
      div.style.transition = 'opacity .4s ease';
      div.style.opacity = '0';
      setTimeout(function () { div.remove(); }, 400);
    }, 4000);
  };
});
