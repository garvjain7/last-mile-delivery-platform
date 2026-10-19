import { mountCustomerShell } from '/static/shared/js/customer/shell.js';
import { requestJson } from '/static/shared/js/customer/api.js';
import { createOrderCard } from '/static/shared/js/customer/order-card.js';
import { mountClaimDialog } from '/static/shared/js/customer/claim-dialog.js';

await mountCustomerShell({
  page: 'overview',
  title: 'Overview',
  action: '<a class="button" data-request-link>New request</a>',
  render: async (root, user, userId) => {
    const greeting = document.createElement('section');
    greeting.className = 'overview-greeting';
    const greetingTitle = document.createElement('h2');
    greetingTitle.textContent = `Hello, ${user.full_name.split(' ')[0]}`;
    const greetingText = document.createElement('p');
    greetingText.textContent = 'Here is what is happening with your deliveries.';
    greeting.append(greetingTitle, greetingText);

    const counts = document.createElement('section');
    counts.className = 'summary';
    counts.setAttribute('aria-label', 'Order summary');
    const ordersHref = `/users/${encodeURIComponent(userId)}/orders`;
    const tiles = {};
    for (const [key, label] of [['active', 'Active'], ['past', 'Past'], ['all', 'All']]) {
      const link = document.createElement('a');
      link.href = `${ordersHref}?tab=${key}`;
      const name = document.createElement('span');
      name.textContent = key === 'all' ? 'All orders' : label;
      const count = document.createElement('strong');
      count.textContent = '—';
      tiles[key] = count;
      link.append(name, count);
      counts.append(link);
    }

    const section = document.createElement('section');
    section.className = 'recent-section';
    const heading = document.createElement('div');
    heading.className = 'section-heading';
    const headingText = document.createElement('h2');
    headingText.textContent = 'Recent active orders';
    const headingLinks = document.createElement('div');
    headingLinks.className = 'overview-actions';
    const claimButton = document.createElement('button');
    claimButton.type = 'button';
    claimButton.className = 'secondary-button';
    claimButton.textContent = 'Claim a guest order';
    const allOrders = document.createElement('a');
    allOrders.className = 'all-orders';
    allOrders.href = ordersHref;
    allOrders.textContent = 'View all orders';
    headingLinks.append(claimButton, allOrders);
    heading.append(headingText, headingLinks);
    const status = document.createElement('p');
    status.className = 'message';
    status.setAttribute('role', 'status');
    status.textContent = 'Loading your deliveries…';
    const list = document.createElement('div');
    list.className = 'customer-orders-list';
    const retry = document.createElement('button');
    retry.type = 'button';
    retry.className = 'secondary-button';
    retry.textContent = 'Try again';
    retry.hidden = true;
    section.append(heading, status, retry, list);
    root.append(greeting, counts, section);

    async function load() {
      claimButton.disabled = true;
      retry.disabled = true;
      retry.hidden = true;
      status.textContent = 'Loading your deliveries…';
      try {
        const [overview, orders] = await Promise.all([
          requestJson(`/api/users/${encodeURIComponent(userId)}`),
          requestJson(`/api/users/${encodeURIComponent(userId)}/orders?tab=active&limit=5`),
        ]);
        tiles.active.textContent = overview.counts.active;
        tiles.past.textContent = overview.counts.past;
        tiles.all.textContent = overview.counts.all;
        list.replaceChildren(...orders.items.map((order) => createOrderCard(order, userId)));
        if (overview.counts.all === 0) {
          status.textContent = 'No orders yet. Create a delivery request to get started.';
          const newRequest = document.createElement('a');
          newRequest.className = 'button';
          newRequest.href = `/users/${encodeURIComponent(userId)}/request`;
          newRequest.textContent = 'New request';
          status.append(' ', newRequest);
        } else if (!orders.items.length) {
          status.textContent = 'You have no active deliveries right now.';
        } else {
          status.textContent = '';
        }
      } catch (error) {
        status.textContent = error.status === 404
          ? 'We could not find this customer account.'
          : error.message || 'Your deliveries could not be loaded.';
        if (error.status === 404) {
          const myOrders = document.createElement('a');
          myOrders.href = ordersHref;
          myOrders.textContent = 'My orders';
          status.append(' ', myOrders);
        } else {
          retry.hidden = false;
        }
      } finally {
        claimButton.disabled = false;
        retry.disabled = false;
      }
    }

    retry.addEventListener('click', load);
    claimButton.addEventListener('click', () => claim.open());
    const claim = mountClaimDialog({ userId, onClaimed: load });
    window.addEventListener('focus', load);
    window.addEventListener('pageshow', (event) => { if (event.persisted) load(); });
    await load();
  },
});
