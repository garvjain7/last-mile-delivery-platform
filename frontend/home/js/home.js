(function () {
  var form = document.getElementById('track-form');
  var input = document.getElementById('code');
  var error = document.getElementById('track-error');

  function showError(msg) {
    error.textContent = msg;
    error.hidden = false;
    input.classList.add('invalid');
    input.setAttribute('aria-invalid', 'true');
  }

  function clearError() {
    error.hidden = true;
    input.classList.remove('invalid');
    input.removeAttribute('aria-invalid');
  }

  input.addEventListener('input', clearError);

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var code = input.value.trim().toUpperCase();
    if (!code) {
      showError('Enter your tracking code to find your parcel.');
      return;
    }
    window.location.href = '/track?code=' + encodeURIComponent(code);
  });

  document.getElementById('cta-track').addEventListener('click', function () {
    setTimeout(function () { input.focus(); }, 0);
  });

  // The van animation needs CSS motion-path support; show it only where available.
  if (window.CSS && CSS.supports('offset-path', 'path("M0 0")')) {
    document.querySelector('.van').style.display = 'block';
  }
})();
