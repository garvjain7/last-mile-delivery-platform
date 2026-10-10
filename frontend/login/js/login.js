const ROLE_FALLBACK_REDIRECTS = {
  admin: "/workspaces/admin/operations",
  dispatcher: "/workspaces/dispatcher/live-dispatch",
  fleet_manager: "/workspaces/fleet-manager/driver-operations",
  merchant: "/workspaces/merchant/order-intake",
  driver: "/workspaces/driver/active-route",
  customer: "/workspaces/customer/delivery-tracking",
};

let currentMode = "email";

function setIdentifierMode(mode) {
  currentMode = mode;

  document.querySelectorAll(".toggle-option").forEach((button) => {
    const isActive = button.dataset.mode === mode;
    button.classList.toggle("active", isActive);
    button.setAttribute("aria-selected", String(isActive));
  });

  document.getElementById("group-email").classList.toggle("hidden", mode !== "email");
  document.getElementById("group-phone").classList.toggle("hidden", mode !== "phone");
  document.getElementById("email").value = "";
  document.getElementById("phone").value = "";
  hideMessage("error-box");
  hideMessage("status-box");
}

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

function resolveRedirect(data) {
  if (data.redirect_to) {
    return data.redirect_to;
  }

  const roles = Array.isArray(data.roles) ? data.roles : [];
  for (const role of roles) {
    if (ROLE_FALLBACK_REDIRECTS[role]) {
      return ROLE_FALLBACK_REDIRECTS[role];
    }
  }

  return "/";
}

document.querySelectorAll(".toggle-option").forEach((button) => {
  button.addEventListener("click", () => setIdentifierMode(button.dataset.mode));
});

document.getElementById("password-reset").addEventListener("click", () => {
  hideMessage("error-box");
  hideMessage("status-box");
  document.getElementById("login-view").classList.add("hidden");
  document.getElementById("reset-view").classList.remove("hidden");
});

document.getElementById("back-to-login").addEventListener("click", () => {
  hideMessage("reset-error-box");
  hideMessage("reset-status-box");  
  document.getElementById("reset-view").classList.add("hidden");
  document.getElementById("login-view").classList.remove("hidden");
});

document.getElementById("forgot-password-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  hideMessage("reset-error-box");
  hideMessage("reset-status-box");

  const email = document.getElementById("reset-email").value.trim();
  if (!email) {
    showMessage("reset-error-box", "Enter your email address.");
    return;
  }

  const submitButton = document.getElementById("reset-submit");
  submitButton.disabled = true;
  showMessage("reset-status-box", "Sending reset link...");

  try {
    const response = await fetch("/auth/forgot-password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: email }),
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || "Unable to send reset link.");
    }

    hideMessage("reset-status-box");
    showMessage("reset-status-box", `Reset email sent to ${email}`);
    document.getElementById("forgot-password-form").reset();
  } catch (error) {
    hideMessage("reset-status-box");
    showMessage("reset-error-box", error.message);
  } finally {
    submitButton.disabled = false;
  }
});

document.getElementById("login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  hideMessage("error-box");
  hideMessage("status-box");

  const submitButton = document.getElementById("login-submit");
  const password = document.getElementById("password").value;
  const payload = { password };

  if (currentMode === "email") {
    const email = document.getElementById("email").value.trim();
    if (!email) {
      showMessage("error-box", "Enter the work email registered to your account.");
      return;
    }
    payload.email = email;
  } else {
    const phone = document.getElementById("phone").value.trim();
    if (!phone) {
      showMessage("error-box", "Enter your E.164 phone number, for example +919876543210.");
      return;
    }
    payload.phone = phone;
  }

  if (!password || password.length < 8) {
    showMessage("error-box", "Password must be at least 8 characters.");
    return;
  }

  submitButton.disabled = true;
  showMessage("status-box", "Verifying identity with Core API...");

  try {
    const response = await fetch("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify(payload),
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || "Unable to sign in with the provided credentials.");
    }

    window.location.assign(resolveRedirect(data));
  } catch (error) {
    hideMessage("status-box");
    showMessage("error-box", error.message);
    submitButton.disabled = false;
  }
});
