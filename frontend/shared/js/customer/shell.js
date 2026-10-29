import { getMe, goToLogin, requestJson } from './api.js';
import { createAccountChip } from './account-chip.js';

const NAV = [
  { page: 'overview', label: 'Overview', href: (id) => `/users/${id}` },
  { page: 'orders', label: 'My orders', href: (id) => `/users/${id}/orders` },
  { page: 'request', label: 'New request', href: (id) => `/users/${id}/request` },
  { page: 'track', label: 'Track an order', href: () => '/track' },
];

export async function mountCustomerShell({ page, title, action, render }) {
  let user;
  try {
    user = await getMe({ redirectOnFailure: false });
  } catch {
    const root = document.querySelector('#app');
    root.className = 'customer-shell-error';
    const error = document.createElement('main');
    error.className = 'customer-error';
    const heading = document.createElement('h1');
    heading.textContent = 'Your account could not be loaded';
    const retry = document.createElement('button');
    retry.type = 'button';
    retry.className = 'button';
    retry.textContent = 'Try again';
    retry.addEventListener('click', () => location.reload());
    error.append(heading, retry);
    root.replaceChildren(error);
    return null;
  }
  if (!user) {
    goToLogin(`${location.pathname}${location.search}`);
    return null;
  }
  const userId = user.user_id;
  const root = document.querySelector('#app');
  root.replaceChildren();
  root.className = 'customer-shell';

  const sidebar = document.createElement('aside');
  sidebar.className = 'customer-sidebar';
  const brand = document.createElement('a');
  brand.className = 'customer-brand';
  brand.href = '/';
  brand.textContent = 'Lastmile';
  const nav = document.createElement('nav');
  nav.className = 'customer-nav';
  nav.setAttribute('aria-label', 'Customer menu');
  const menuLabel = document.createElement('p');
  menuLabel.className = 'customer-menu-label';
  menuLabel.textContent = 'MENU';
  nav.append(menuLabel);
  const links = new Map();
  for (const item of NAV) {
    const link = document.createElement('a');
    link.href = item.href(encodeURIComponent(userId));
    link.textContent = item.label;
    if (item.page === page) link.setAttribute('aria-current', 'page');
    links.set(item.page, link);
    nav.append(link);
  }
  const accountSlot = document.createElement('div');
  accountSlot.className = 'customer-account-slot';
  accountSlot.append(createAccountChip(user));
  sidebar.append(brand, nav, accountSlot);

  const area = document.createElement('div');
  area.className = 'customer-area';
  const mobileBar = document.createElement('header');
  mobileBar.className = 'customer-mobile-bar';
  const menuButton = document.createElement('button');
  menuButton.type = 'button';
  menuButton.className = 'menu-button';
  menuButton.setAttribute('aria-label', 'Open menu');
  menuButton.setAttribute('aria-expanded', 'false');
  menuButton.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16"/></svg>';
  const mobileBrand = brand.cloneNode(true);
  mobileBar.append(menuButton, mobileBrand);
  const backdrop = document.createElement('button');
  backdrop.type = 'button';
  backdrop.className = 'customer-backdrop';
  backdrop.setAttribute('aria-label', 'Close menu');
  const content = document.createElement('main');
  content.className = 'customer-content';
  const pageHeader = document.createElement('header');
  pageHeader.className = 'customer-page-header';
  const breadcrumb = document.createElement('p');
  breadcrumb.className = 'customer-breadcrumb';
  breadcrumb.textContent = page === 'overview' ? 'Account' : `Account / ${page === 'orders' ? 'My orders' : title}`;
  const headingRow = document.createElement('div');
  headingRow.className = 'customer-heading-row';
  const heading = document.createElement('h1');
  heading.textContent = title;
  headingRow.append(heading);
  if (action) {
    headingRow.insertAdjacentHTML('beforeend', action);
    const requestLink = headingRow.querySelector('[data-request-link]');
    if (requestLink) requestLink.href = `/users/${encodeURIComponent(userId)}/request`;
  }
  pageHeader.append(breadcrumb, headingRow);
  content.append(pageHeader);
  area.append(mobileBar, backdrop, content);
  root.append(sidebar, area);

  function closeDrawer() {
    root.classList.remove('menu-open');
    menuButton.setAttribute('aria-expanded', 'false');
  }
  menuButton.addEventListener('click', () => {
    const open = root.classList.toggle('menu-open');
    menuButton.setAttribute('aria-expanded', String(open));
  });
  backdrop.addEventListener('click', closeDrawer);
  nav.addEventListener('click', (event) => {
    if (event.target.closest('a')) closeDrawer();
  });

  try {
    const overview = await requestJson(`/api/users/${encodeURIComponent(userId)}`);
    const ordersLink = links.get('orders');
    const badge = document.createElement('span');
    badge.className = 'customer-nav-badge';
    badge.textContent = overview.counts.active;
    ordersLink.append(badge);
  } catch {
    // The page's own load state reports data errors; navigation remains available.
  }

  const pageRoot = document.createElement('div');
  pageRoot.className = 'customer-page';
  content.append(pageRoot);
  try {
    await render(pageRoot, user, userId);
  } catch {
    const error = document.createElement('section');
    error.className = 'customer-error';
    const errorHeading = document.createElement('h2');
    errorHeading.textContent = 'This page could not be loaded';
    const orders = document.createElement('a');
    orders.href = `/users/${encodeURIComponent(userId)}/orders`;
    orders.textContent = 'Go to My orders';
    error.append(errorHeading, orders);
    pageRoot.replaceChildren(error);
  }
  return { user, userId, pageRoot };
}
