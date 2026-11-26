import { mountCustomerShell } from '/static/shared/js/customer/shell.js';
import { requestJson } from '/static/shared/js/customer/api.js';
import { createOrderCard } from '/static/shared/js/customer/order-card.js';
import { mountClaimDialog } from '/static/shared/js/customer/claim-dialog.js';

await mountCustomerShell({
  page: 'orders',
  title: 'My orders',
  action: '<a class="button" data-request-link>New request</a>',
  render: async (root, _user, userId) => {
    const controls = document.createElement('section');
    controls.className = 'orders-filter-panel';
    const tabs = document.createElement('nav');
    tabs.className = 'order-tabs';
    tabs.setAttribute('aria-label', 'Order status group');
    const filters = document.createElement('div');
    filters.className = 'customer-filters';
    filters.innerHTML = `
      <label class="customer-field">Status
        <select name="status"><option value="">Any status</option>
          <option value="placed">Seller preparing</option><option value="sent">Sent to hub</option>
          <option value="pending">At our hub</option><option value="assigned">Scheduled</option>
          <option value="out_for_delivery">Out for delivery</option><option value="attempt_failed">Delivery attempt unsuccessful</option>
          <option value="delivered">Delivered</option><option value="returned">Returned</option><option value="cancelled">Cancelled</option>
        </select>
      </label>
      <label class="customer-field">Seller<select name="seller"><option value="">All sellers</option></select></label>
      <label class="customer-field">From<input name="from" type="date"></label>
      <label class="customer-field">To<input name="to" type="date"></label>
      <label class="customer-field customer-search-field">Search<input name="q" type="search" minlength="2" placeholder="Order, seller or address"></label>
      <button class="secondary-button clear-filters" type="button">Clear filters</button>`;
    const results = document.createElement('section');
    results.className = 'customer-orders-list';
    results.setAttribute('aria-label', 'Orders');
    const status = document.createElement('p');
    status.className = 'message';
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');
    const retry = document.createElement('button');
    retry.type = 'button';
    retry.className = 'secondary-button';
    retry.textContent = 'Try again';
    retry.hidden = true;
    const loadMore = document.createElement('button');
    loadMore.type = 'button';
    loadMore.className = 'secondary-button load-more-button';
    loadMore.textContent = 'Load more';
    loadMore.hidden = true;
    controls.append(tabs, filters);
    root.append(controls, status, retry, results, loadMore);

    const form = filters;
    const fields = Object.fromEntries([...form.querySelectorAll('[name]')].map((input) => [input.name, input]));
    const query = new URLSearchParams(location.search);
    const allowedTabs = new Set(['active', 'past', 'all']);
    let tab = allowedTabs.has(query.get('tab')) ? query.get('tab') : 'all';
    let cursor = null;
    let busy = false;
    let timer;
    const requestedSeller = query.get('seller') || '';
    for (const name of ['status', 'seller', 'from', 'to', 'q']) {
      if (query.has(name)) fields[name].value = query.get(name);
    }

    const tabCounts = {};
    for (const [value, label] of [['active', 'Active'], ['past', 'Past'], ['all', 'All']]) {
      const button = document.createElement('button');
      button.type = 'button';
      button.dataset.tab = value;
      button.setAttribute('aria-pressed', String(tab === value));
      const text = document.createElement('span');
      text.textContent = label;
      const count = document.createElement('strong');
      count.textContent = '—';
      tabCounts[value] = count;
      button.append(text, count);
      button.addEventListener('click', () => {
        tab = value;
        tabs.querySelectorAll('button').forEach((item) => item.setAttribute('aria-pressed', String(item === button)));
        load(true);
      });
      tabs.append(button);
    }

    function updateAddress() {
      const params = new URLSearchParams();
      params.set('tab', tab);
      for (const name of ['status', 'seller', 'from', 'to', 'q']) {
        const value = fields[name].value.trim();
        if (value) params.set(name, value);
      }
      history.replaceState(null, '', `${location.pathname}?${params.toString()}`);
    }

    async function load(reset = false) {
      if (busy) return;
      busy = true;
      if (reset) {
        cursor = null;
        results.replaceChildren();
      }
      const requestControls = [
        ...tabs.querySelectorAll('button'),
        ...form.querySelectorAll('input, select, button'),
        retry,
        loadMore,
      ];
      requestControls.forEach((control) => { control.disabled = true; });
      retry.hidden = true;
      status.textContent = 'Loading orders…';
      loadMore.disabled = true;
      updateAddress();
      const params = new URLSearchParams({ tab, limit: '20' });
      for (const name of ['status', 'seller']) if (fields[name].value) params.set(name, fields[name].value);
      if (fields.from.value) params.set('from', `${fields.from.value}T00:00:00`);
      if (fields.to.value) params.set('to', `${fields.to.value}T23:59:59.999`);
      if (fields.q.value.trim().length >= 2) params.set('q', fields.q.value.trim());
      if (cursor) params.set('cursor', cursor);
      try {
        const data = await requestJson(`/api/users/${encodeURIComponent(userId)}/orders?${params}`);
        for (const key of ['active', 'past', 'all']) {
          if (data.counts) tabCounts[key].textContent = data.counts[key];
        }
        if (data.sellers) {
          const selected = fields.seller.value || requestedSeller;
          fields.seller.replaceChildren(new Option('All sellers', ''));
          for (const seller of data.sellers) fields.seller.add(new Option(seller.name, seller.id));
          fields.seller.value = selected;
        }
        results.append(...data.items.map((order) => createOrderCard(order, userId)));
        cursor = data.next_cursor;
        loadMore.hidden = !cursor;
        if (!results.childElementCount) {
          const filtered = ['status', 'seller', 'from', 'to', 'q'].some((name) => fields[name].value);
          status.textContent = filtered ? 'No orders match these filters.' : 'No orders found in this section.';
        } else {
          status.textContent = '';
        }
      } catch (error) {
        status.textContent = error.status === 404
          ? 'We could not find this order list.'
          : error.message || 'Orders could not be loaded.';
        if (error.status === 404) {
          const myOrders = document.createElement('a');
          myOrders.href = `/users/${encodeURIComponent(userId)}/orders`;
          myOrders.textContent = 'My orders';
          status.append(' ', myOrders);
        }
        retry.hidden = false;
      } finally {
        busy = false;
        requestControls.forEach((control) => { control.disabled = false; });
        loadMore.disabled = !cursor;
      }
    }

    const scheduleFilter = () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        if (fields.q.value.trim().length === 1) {
          status.textContent = 'Enter at least two characters to search.';
          return;
        }
        load(true);
      }, fields.q === document.activeElement ? 300 : 0);
    };
    for (const name of ['status', 'seller', 'from', 'to']) fields[name].addEventListener('change', scheduleFilter);
    fields.q.addEventListener('input', scheduleFilter);
    form.querySelector('.clear-filters').addEventListener('click', () => {
      for (const name of ['status', 'seller', 'from', 'to', 'q']) fields[name].value = '';
      load(true);
    });
    retry.addEventListener('click', () => load(true));
    loadMore.addEventListener('click', () => load());
    const claimButton = document.createElement('button');
    claimButton.type = 'button';
    claimButton.className = 'secondary-button claim-orders-button';
    claimButton.textContent = 'Claim a guest order';
    form.append(claimButton);
    const claim = mountClaimDialog({ userId, onClaimed: () => load(true) });
    claimButton.addEventListener('click', () => claim.open());
    window.addEventListener('focus', () => load(true));
    window.addEventListener('pageshow', (event) => { if (event.persisted) load(true); });
    await load(true);
  },
});
