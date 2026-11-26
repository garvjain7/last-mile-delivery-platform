import { logout } from './api.js';

export function createAccountChip(user, { track = false } = {}) {
  const chip = document.createElement('section');
  chip.className = track ? 'account-chip account-chip-track' : 'account-chip';
  chip.setAttribute('aria-label', 'Signed-in account');
  const identity = document.createElement('div');
  identity.className = 'account-identity';
  const name = document.createElement('strong');
  name.textContent = user.full_name || 'Customer';
  const email = document.createElement('span');
  email.textContent = user.email || user.phone || '';
  identity.append(name, email);
  const button = document.createElement('button');
  button.className = 'logout-button';
  button.type = 'button';
  button.setAttribute('aria-label', 'Sign out');
  button.title = 'Sign out';
  button.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 17l5-5-5-5M15 12H3m9-7h6a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2h-6"/></svg>';
  button.addEventListener('click', async () => {
    button.disabled = true;
    try {
      await logout();
    } catch {
      // Clear the local session view even if the logout request cannot reach the server.
    } finally {
      const destination = track ? `/track${location.search}` : '/login';
      location.assign(destination);
    }
  });
  chip.append(identity, button);
  return chip;
}
