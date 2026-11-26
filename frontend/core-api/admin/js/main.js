import { bootstrapShell, setActivePage, showToast } from './shell.js';

const TITLES = {
  overview: 'Overview', drivers: 'Drivers', users: 'Users', merchants: 'Merchants',
  warehouses: 'Warehouses', orders: 'Orders', activity: 'Activity'
};
const PAGE_MODULES = {
  overview: () => import('./pages/overview.js').then((module) => module.createOverviewPage),
  drivers: () => import('./pages/drivers.js').then((module) => module.createDriversPage),
  users: () => import('./pages/users.js').then((module) => module.createUsersPage),
  merchants: () => import('./pages/merchants.js').then((module) => module.createMerchantsPage),
  warehouses: () => import('./pages/warehouses.js').then((module) => module.createWarehousesPage),
  orders: () => import('./pages/orders.js').then((module) => module.createOrdersPage),
  activity: () => import('./pages/activity.js').then((module) => module.createActivityPage)
};

for (const href of ['/admin/assets/css/tokens.css', '/admin/assets/css/admin.css']) {
  const stylesheet = document.createElement('link');
  stylesheet.rel = 'stylesheet';
  stylesheet.href = href;
  document.head.append(stylesheet);
}

async function start() {
  const pageName = document.body.dataset.page;
  const page = { name: pageName, title: TITLES[pageName] || TITLES.overview };
  const session = await bootstrapShell(page);
  if (!session) return;

  const pageContent = document.getElementById('page-content');
  const query = new URLSearchParams(window.location.search);
  const route = { page: pageName, itemId: query.get('id'), query };
  const loadPage = PAGE_MODULES[pageName];
  let activePage;
  if (loadPage) {
    const createPage = await loadPage();
    activePage = createPage({
      api: session.api,
      timezone: window.adminTimezone,
      onToast: showToast,
      onPageTitle: (title) => { document.getElementById('page-title').textContent = title; },
      route
    });
    pageContent.append(activePage.element);
  } else {
    const placeholder = document.createElement('section');
    placeholder.className = 'page-placeholder';
    const title = document.createElement('h2');
    title.textContent = page.title;
    const copy = document.createElement('p');
    copy.textContent = 'This section is being set up.';
    placeholder.append(title, copy);
    pageContent.append(placeholder);
    activePage = null;
  }
  setActivePage(activePage);
}

start().catch((error) => {
  const content = document.getElementById('page-content');
  if (!content) return;
  const message = document.createElement('p');
  message.className = 'page-message';
  message.setAttribute('role', 'alert');
  message.textContent = error.message || 'This page could not be loaded.';
  content.replaceChildren(message);
});
