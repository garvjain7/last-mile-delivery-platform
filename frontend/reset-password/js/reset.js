function showMessage(id, message) {
  const element = document.getElementById(id);
  element.textContent = message;
  element.style.display = "block";
}

function hideMessage(id) {
  const element = document.getElementById(id);
  element.textContent = "";
  element.style.display = "none";
}

document.getElementById("reset-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  hideMessage("error-box");
  hideMessage("status-box");

  const urlParams = new URLSearchParams(window.location.search);
  const token = urlParams.get('token');

  if (!token) {
    showMessage("error-box", "Invalid or missing reset token.");
    return;
  }

  const password = document.getElementById("password").value;
  const confirmPassword = document.getElementById("confirm_password").value;

  if (password.length < 8) {
    showMessage("error-box", "Password must be at least 8 characters.");
    return;
  }

  if (password !== confirmPassword) {
    showMessage("error-box", "Passwords do not match.");
    return;
  }

  const submitButton = document.getElementById("reset-submit");
  submitButton.disabled = true;
  showMessage("status-box", "Updating password...");

  try {
    const response = await fetch("/auth/reset-password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: token, new_password: password }),
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || "Unable to reset password.");
    }

    hideMessage("error-box");
    showMessage("status-box", "Password updated successfully. Redirecting to login...");
    document.getElementById("reset-form").reset();
    
    setTimeout(() => {
      window.location.assign("/login");
    }, 2000);
  } catch (error) {
    hideMessage("status-box");
    showMessage("error-box", error.message);
    submitButton.disabled = false;
  }
});
