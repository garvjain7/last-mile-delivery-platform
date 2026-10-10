const ROLE_ENDPOINTS = {
  customer: "/auth/register/customer",
  driver: "/auth/register/driver",
};

let selectedRole = "customer";

function setRole(role) {
  selectedRole = role;
  document.querySelectorAll(".account-option").forEach((button) => {
    const active = button.dataset.role === role;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
}

function showRegisterMessage(id, message) {
  const element = document.getElementById(id);
  element.textContent = message;
  element.style.display = "block";
}

function hideRegisterMessage(id) {
  const element = document.getElementById(id);
  element.textContent = "";
  element.style.display = "none";
}

document.querySelectorAll(".account-option").forEach((button) => {
  button.addEventListener("click", () => setRole(button.dataset.role));
});

document.getElementById("register-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  hideRegisterMessage("register-error");
  hideRegisterMessage("register-status");

  const submitButton = document.getElementById("register-submit");
  const fullName = document.getElementById("full_name").value.trim();
  const email = document.getElementById("email").value.trim();
  const phone = document.getElementById("phone").value.trim();
  const password = document.getElementById("password").value;
  const confirmPassword = document.getElementById("confirm_password").value;

  if (!fullName) {
    showRegisterMessage("register-error", "Enter your full name.");
    return;
  }

  if (!email && !phone) {
    showRegisterMessage("register-error", "Provide either an email address or an E.164 phone number.");
    return;
  }

  if (password.length < 8) {
    showRegisterMessage("register-error", "Password must be at least 8 characters.");
    return;
  }

  if (password !== confirmPassword) {
    showRegisterMessage("register-error", "Passwords do not match.");
    return;
  }

  const payload = {
    full_name: fullName,
    password,
  };

  if (email) {
    payload.email = email;
  }

  if (phone) {
    payload.phone = phone;
  }

  submitButton.disabled = true;
  showRegisterMessage("register-status", "Creating account...");

  try {
    const response = await fetch(ROLE_ENDPOINTS[selectedRole], {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify(payload),
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || "Unable to create account.");
    }

    window.location.assign(data.redirect_to || "/");
  } catch (error) {
    hideRegisterMessage("register-status");
    showRegisterMessage("register-error", error.message);
    submitButton.disabled = false;
  }
});
