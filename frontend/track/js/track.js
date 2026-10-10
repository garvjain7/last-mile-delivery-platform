(function () {
  var API = '/api/track/';

  var form = document.getElementById('track-form');
  var input = document.getElementById('code');
  var btn = document.getElementById('track-btn');
  var loading = document.getElementById('loading');
  var message = document.getElementById('message');
  var messageText = document.getElementById('message-text');
  var retry = document.getElementById('retry');
  var result = document.getElementById('result');

  var current = null; // in-flight request, so a newer search cancels an older one
  var lastCode = '';

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function show(which) {
    loading.hidden = which !== 'loading';
    message.hidden = which !== 'message';
    result.hidden = which !== 'result';
  }

  function showMessage(text, canRetry) {
    messageText.textContent = text;
    message.className = 'notice error';
    retry.hidden = !canRetry;
    show('message');
  }

  function render(d) {
    document.getElementById('r-title').textContent = 'Parcel ' + d.code;
    var chip = document.getElementById('r-chip');
    chip.textContent = d.status || '';
    chip.className = 'chip' + (d.tone ? ' tone-' + d.tone : '');
    document.getElementById('r-eta').textContent = d.eta_text || '';

    var list = document.getElementById('r-steps');
    list.textContent = '';
    var CHECK = '<svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true"><path d="M3 7.5l2.5 2.5L11 4" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    var CROSS = '<svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true"><path d="M4 4l6 6M10 4l-6 6" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>';
    var SR = { done: 'Completed', now: 'Current step', failed: 'Problem', next: 'Upcoming' };

    (d.steps || []).forEach(function (s) {
      var state = SR[s.state] ? s.state : 'next';
      var li = el('li', state);
      var mark = el('span', 'mark');
      if (state === 'done') mark.innerHTML = CHECK; // constant markup, no API data
      else if (state === 'failed') mark.innerHTML = CROSS;
      else mark.appendChild(el('span', 'mark-dot'));
      li.appendChild(mark);
      li.appendChild(el('span', 'step-label', s.label));
      li.appendChild(el('span', 'sr', SR[state]));
      if (s.time) li.appendChild(el('span', 'step-time', s.time));
      if (s.note) li.appendChild(el('span', 'step-note', s.note));
      list.appendChild(li);
    });

    var dl = document.getElementById('r-details');
    dl.textContent = '';
    var rows = d.details || [];
    rows.forEach(function (r) {
      var row = el('div', 'kv-row');
      row.appendChild(el('dt', null, r.label));
      row.appendChild(el('dd', null, r.value));
      dl.appendChild(row);
    });
    document.getElementById('r-details-card').hidden = rows.length === 0;

    show('result');
  }

  function track(code) {
    code = (code || '').trim().toUpperCase();
    if (!code) {
      showMessage('Enter your tracking code to find your parcel.', false);
      input.focus();
      return;
    }
    input.value = code;
    lastCode = code;
    if (current) current.abort();
    current = new AbortController();
    var req = current;

    show('loading');
    btn.disabled = true;

    fetch(API + encodeURIComponent(code), {
      headers: { Accept: 'application/json' },
      signal: req.signal
    })
      .then(function (res) {
        if (res.status === 404) {
          showMessage("We couldn't find that code. Check it and try again.", false);
          return null;
        }
        if (res.status === 429) {
          showMessage('Too many attempts. Wait a minute and try again.', true);
          return null;
        }
        if (!res.ok) throw new Error('bad status');
        return res.json();
      })
      .then(function (data) {
        if (data) render(data);
      })
      .catch(function (err) {
        if (err && err.name === 'AbortError') return;
        showMessage('Something went wrong on our side. Try again in a moment.', true);
      })
      .then(function () {
        if (current === req) btn.disabled = false;
      });
  }

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var code = (input.value || '').trim().toUpperCase();
    if (code) {
      history.replaceState(null, '', '?code=' + encodeURIComponent(code));
    }
    track(code);
  });

  retry.addEventListener('click', function () { track(lastCode || input.value); });

  // Arrived from the home page: fill the input and run the same lookup.
  var initial = new URLSearchParams(window.location.search).get('code');
  if (initial) {
    initial = initial.trim().toUpperCase();
    input.value = initial;
    track(initial);
  }
})();
