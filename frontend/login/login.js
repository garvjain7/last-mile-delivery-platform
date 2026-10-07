let currentMode = 'email';

function switchTab(mode) {
  currentMode = mode;
  
  // Update Tabs
  document.getElementById('tab-email').classList.toggle('active', mode === 'email');
  document.getElementById('tab-phone').classList.toggle('active', mode === 'phone');
  
  // Update Inputs
  document.getElementById('group-email').classList.toggle('hidden', mode !== 'email');
  document.getElementById('group-phone').classList.toggle('hidden', mode !== 'phone');

  // Clear fields
  document.getElementById('email').value = '';
  document.getElementById('phone').value = '';
  hideError();
}

function showError(msg) {
  const errBox = document.getElementById('error-box');
  errBox.textContent = msg;
  errBox.style.display = 'block';
}

function hideError() {
  document.getElementById('error-box').style.display = 'none';
}

document.getElementById('login-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  hideError();

  const password = document.getElementById('password').value;
  const payload = { password };

  if (currentMode === 'email') {
    const email = document.getElementById('email').value.trim();
    if (!email) return showError("Email is required.");
    payload.email = email;
  } else {
    const phone = document.getElementById('phone').value.trim();
    if (!phone) return showError("Phone number is required.");
    payload.phone = phone;
  }

  try {
    const response = await fetch('/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    const data = await response.json();

    if (!response.ok) {
      // Data.detail contains the exact message from backend, e.g., "Invalid email or password. 2 attempts left."
      throw new Error(data.detail || "Login failed");
    }

    // Success! Tokens are set in httpOnly cookies.
    // The backend provides the advisory redirect path based on user role.
    if (data.redirect_to) {
      window.location.href = data.redirect_to;
    } else {
      window.location.href = "/";
    }

  } catch (err) {
    showError(err.message);
  }
});
