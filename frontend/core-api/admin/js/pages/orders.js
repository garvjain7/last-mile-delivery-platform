const STATUSES = [
  ['pending', 'Pending'],
  ['assigned', 'Assigned'],
  ['out_for_delivery', 'Out for delivery'],
  ['delivered', 'Delivered'],
  ['attempt_failed', 'Failed attempt'],
  ['returned', 'Returned'],
  ['cancelled', 'Cancelled']
];
const OPEN_STATUSES = new Set(['pending', 'assigned', 'out_for_delivery', 'attempt_failed']);
const PAGE_SIZES = [25, 50, 100];

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function date(value, withTime = false, timeZone) {
  if (!value) return '—';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return '—';
  const options = withTime
    ? { dateStyle: 'medium', timeStyle: 'medium' }
    : { dateStyle: 'medium' };
  if (timeZone) options.timeZone = timeZone;
  return new Intl.DateTimeFormat(undefined, options).format(parsed);
}

function localDateTime(value) {
  if (!value) return '';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return '';
  const local = new Date(parsed.getTime() - parsed.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 16);
}

function toIso(value) {
  if (!value) return '';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? '' : parsed.toISOString();
}

function humanDuration(milliseconds) {
  const minutes = Math.max(0, Math.floor(Math.abs(milliseconds) / 60000));
  const days = Math.floor(minutes / 1440);
  const hours = Math.floor((minutes % 1440) / 60);
  const rest = minutes % 60;
  if (days) return `${days}d ${hours}h`;
  if (hours) return `${hours}h ${String(rest).padStart(2, '0')}m`;
  return `${rest}m`;
}

function relativeTime(value) {
  const elapsed = Date.now() - new Date(value).getTime();
  const minutes = Math.floor(Math.abs(elapsed) / 60000);
  const amount = minutes < 60 ? `${Math.max(1, minutes)}m`
    : minutes < 1440 ? `${Math.floor(minutes / 60)}h`
      : `${Math.floor(minutes / 1440)}d`;
  return elapsed >= 0 ? `${amount} ago` : `in ${amount}`;
}

function statusLabel(status) {
  return STATUSES.find(([key]) => key === status)?.[1] || String(status || '').replaceAll('_', ' ');
}

function makeQuery(state, includeStatuses = true) {
  const params = new URLSearchParams();
  if (state.q.trim()) params.set('q', state.q.trim());
  if (includeStatuses) state.statuses.forEach((status) => params.append('status', status));
  if (state.merchantId) params.set('merchant_id', state.merchantId);
  if (state.warehouseId) params.set('warehouse_id', state.warehouseId);
  if (state.from) params.set('from', state.from);
  if (state.to) params.set('to', state.to);
  if (state.overdue) params.set('overdue', 'true');
  return params;
}

async function fetchAllOptions(api, endpoint) {
  const items = [];
  let page = 1;
  let total = Infinity;
  while (items.length < total) {
    const result = await api.get(`${endpoint}?page=${page}&page_size=100`);
    items.push(...result.items);
    total = result.total;
    page += 1;
  }
  return items;
}

export function createOrdersPage({ api, onToast, route }) {
  const root = el('div', 'orders-page');
  const intro = el('div', 'page-intro');
  const introCopy = el('div');
  introCopy.append(
    el('h2', '', 'Order ledger'),
    el('p', '', 'Search orders and inspect their status history, delivery attempts, and location.')
  );
  const refreshButton = el('button', 'button button-secondary', 'Refresh');
  refreshButton.type = 'button';
  intro.append(introCopy, refreshButton);

  const filters = el('section', 'orders-filters panel');
  const search = document.createElement('input');
  search.type = 'search';
  search.maxLength = 100;
  search.placeholder = 'Tracking code, order ref, recipient, or phone';
  search.setAttribute('aria-label', 'Search orders');
  const searchLabel = el('label', 'orders-search-label', 'Search');
  searchLabel.append(search);

  const chips = el('div', 'orders-status-chips');
  chips.setAttribute('role', 'group');
  chips.setAttribute('aria-label', 'Filter by order status');
  const merchant = document.createElement('select');
  merchant.setAttribute('aria-label', 'Filter by merchant');
  const warehouse = document.createElement('select');
  warehouse.setAttribute('aria-label', 'Filter by warehouse');
  const from = document.createElement('input');
  from.type = 'datetime-local';
  from.setAttribute('aria-label', 'Created from');
  const to = document.createElement('input');
  to.type = 'datetime-local';
  to.setAttribute('aria-label', 'Created to');
  const overdue = document.createElement('input');
  overdue.type = 'checkbox';
  const overdueLabel = el('label', 'orders-overdue-label', 'Overdue only');
  overdueLabel.append(overdue);
  const pageSize = document.createElement('select');
  pageSize.setAttribute('aria-label', 'Orders per load');
  PAGE_SIZES.forEach((size) => {
    const option = el('option', '', `${size} rows`);
    option.value = String(size);
    pageSize.append(option);
  });
  const reset = el('button', 'button button-quiet', 'Reset filters');
  reset.type = 'button';

  const filterControls = el('div', 'orders-filter-controls');
  const merchantLabel = el('label', 'orders-filter-field', 'Merchant'); merchantLabel.append(merchant);
  const warehouseLabel = el('label', 'orders-filter-field', 'Warehouse'); warehouseLabel.append(warehouse);
  const fromLabel = el('label', 'orders-filter-field', 'Created from'); fromLabel.append(from);
  const toLabel = el('label', 'orders-filter-field', 'Created to'); toLabel.append(to);
  const sizeLabel = el('label', 'orders-filter-field orders-page-size', 'Rows per load'); sizeLabel.append(pageSize);
  filterControls.append(merchantLabel, warehouseLabel, fromLabel, toLabel, overdueLabel, sizeLabel, reset);
  filters.append(searchLabel, chips, filterControls);

  const panel = el('section', 'panel orders-table-panel');
  const panelHeader = el('div', 'orders-table-heading');
  const resultSummary = el('p', 'orders-result-summary', 'Loading orders…');
  panelHeader.append(el('h3', '', 'Orders'), resultSummary);
  const tableScroll = el('div', 'orders-table-scroll');
  const table = document.createElement('table');
  table.className = 'orders-table';
  const thead = document.createElement('thead');
  const headerRow = document.createElement('tr');
  ['Order', 'Merchant', 'Recipient', 'Warehouse', 'Status', 'Delivery window', 'Driver', 'Created', ''].forEach((title) => {
    const th = el('th', '', title);
    if (!title) th.setAttribute('aria-label', 'Inspect order');
    headerRow.append(th);
  });
  thead.append(headerRow);
  const tbody = document.createElement('tbody');
  table.append(thead, tbody);
  tableScroll.append(table);
  const tableFooter = el('div', 'orders-table-footer');
  const loadMore = el('button', 'button button-secondary', 'Load more');
  loadMore.type = 'button';
  loadMore.hidden = true;
  tableFooter.append(loadMore);
  panel.append(panelHeader, tableScroll, tableFooter);

  const drawerLayer = el('div', 'drawer-layer');
  drawerLayer.hidden = true;
  root.append(intro, filters, panel, drawerLayer);

  const params = route?.query || new URLSearchParams(window.location.search);
  const pageSizeParam = Number(params.get('limit'));
  const state = {
    q: (params.get('q') || '').slice(0, 100),
    statuses: params.getAll('status').filter((value) => STATUSES.some(([key]) => key === value)),
    merchantId: params.get('merchant_id') || '',
    warehouseId: params.get('warehouse_id') || '',
    from: params.get('from') || '',
    to: params.get('to') || '',
    overdue: params.get('overdue') === 'true',
    limit: PAGE_SIZES.includes(pageSizeParam) ? pageSizeParam : 25,
    rows: [],
    counts: {},
    nextCursor: null,
    detailToken: route?.itemId || params.get('id') || null,
    listController: null,
    detailController: null,
    sequence: 0,
    detailSequence: 0,
    loading: false,
    loadingMore: false,
    disposed: false
  };
  let searchTimer;
  let countController;
  let timer;
  search.value = state.q;
  merchant.value = state.merchantId;
  warehouse.value = state.warehouseId;
  from.value = localDateTime(state.from);
  to.value = localDateTime(state.to);
  overdue.checked = state.overdue;
  pageSize.value = String(state.limit);

  function updateUrl() {
    const next = makeQuery(state);
    if (state.limit !== 25) next.set('limit', String(state.limit));
    if (state.detailToken) next.set('id', state.detailToken);
    const query = next.toString();
    const target = `${window.location.pathname}${query ? `?${query}` : ''}`;
    if (`${window.location.pathname}${window.location.search}` !== target) window.history.replaceState(null, '', target);
  }

  function renderChips() {
    chips.replaceChildren();
    STATUSES.forEach(([key, label]) => {
      const button = el('button', `orders-status-chip${state.statuses.includes(key) ? ' is-active' : ''}`);
      button.type = 'button';
      button.setAttribute('aria-pressed', String(state.statuses.includes(key)));
      button.append(el('span', '', label), el('span', 'orders-chip-count', state.counts[key] ?? '—'));
      button.addEventListener('click', () => {
        state.statuses = state.statuses.includes(key)
          ? state.statuses.filter((status) => status !== key)
          : [...state.statuses, key];
        updateUrl();
        loadOrders();
      });
      chips.append(button);
    });
  }

  function option(label, value = '') {
    const node = el('option', '', label);
    node.value = value;
    return node;
  }

  async function loadFilterOptions() {
    const [merchants, warehouses] = await Promise.all([
      fetchAllOptions(api, '/api/admin/merchants'),
      fetchAllOptions(api, '/api/admin/warehouses')
    ]);
    merchant.replaceChildren(option('All merchants'));
    merchants.forEach((item) => merchant.append(option(item.name, item.id)));
    warehouse.replaceChildren(option('All warehouses'));
    warehouses.forEach((item) => warehouse.append(option(`${item.code} · ${item.name}`, item.id)));
    merchant.value = state.merchantId;
    warehouse.value = state.warehouseId;
  }

  function renderLoading(message = 'Loading orders…') {
    tbody.replaceChildren();
    const row = document.createElement('tr');
    const cell = el('td', 'orders-table-message', message);
    cell.colSpan = 9;
    row.append(cell);
    tbody.append(row);
    resultSummary.textContent = message;
  }

  function renderError(error, retryAction = loadOrders) {
    tbody.replaceChildren();
    const row = document.createElement('tr');
    const cell = document.createElement('td');
    cell.colSpan = 9;
    const message = el('div', 'orders-empty');
    message.append(el('strong', '', 'Orders could not be loaded.'), el('span', '', error.message || 'Try again.'));
    const retry = el('button', 'button button-secondary button-small', 'Retry');
    retry.type = 'button';
    retry.addEventListener('click', retryAction);
    message.append(retry);
    cell.append(message);
    row.append(cell);
    tbody.append(row);
    resultSummary.textContent = 'Unable to load orders';
  }

  async function loadOrders() {
    state.listController?.abort();
    countController?.abort();
    const controller = new AbortController();
    const countsRequest = new AbortController();
    state.listController = controller;
    countController = countsRequest;
    const sequence = ++state.sequence;
    state.loading = true;
    state.rows = [];
    state.nextCursor = null;
    loadMore.hidden = true;
    renderLoading();
    updateUrl();

    const filtersQuery = makeQuery(state);
    const listQuery = new URLSearchParams(filtersQuery);
    listQuery.set('limit', String(state.limit));
    const countsQuery = makeQuery(state, false);
    renderChips();
    try {
      const [list, counts] = await Promise.all([
        api.get(`/api/admin/orders?${listQuery}`, { signal: controller.signal }),
        api.get(`/api/admin/orders/counts?${countsQuery}`, { signal: countsRequest.signal })
      ]);
      if (state.disposed || sequence !== state.sequence) return;
      state.rows = list.items;
      state.nextCursor = list.next_cursor;
      state.counts = counts;
      state.loading = false;
      renderChips();
      renderRows();
      if (state.detailToken) openOrder(state.detailToken);
    } catch (error) {
      if (error.name === 'AbortError' || state.disposed || sequence !== state.sequence) return;
      state.loading = false;
      renderError(error);
    }
  }

  async function loadMoreOrders() {
    if (!state.nextCursor || state.loadingMore || state.loading) return;
    const cursor = state.nextCursor;
    const sequence = state.sequence;
    state.loadingMore = true;
    loadMore.disabled = true;
    loadMore.textContent = 'Loading…';
    const query = makeQuery(state);
    query.set('limit', String(state.limit));
    query.set('cursor', cursor);
    try {
      const list = await api.get(`/api/admin/orders?${query}`);
      if (state.disposed || sequence !== state.sequence) return;
      state.rows.push(...list.items);
      state.nextCursor = list.next_cursor;
      renderRows();
    } catch (error) {
      if (!state.disposed) onToast(error.message || 'Could not load more orders.', 'error');
    } finally {
      state.loadingMore = false;
      loadMore.disabled = false;
      loadMore.textContent = 'Load more';
    }
  }

  function statusBadge(status) {
    return el('span', `orders-status orders-status-${status}`, statusLabel(status));
  }

  async function copyText(value, label) {
    try {
      await navigator.clipboard.writeText(value);
      onToast(`${label} copied.`);
    } catch {
      onToast(`Could not copy ${label.toLowerCase()}.`, 'error');
    }
  }

  function copyButton(value, label) {
    const button = el('button', 'orders-copy', 'Copy');
    button.type = 'button';
    button.setAttribute('aria-label', `Copy ${label}`);
    button.addEventListener('click', (event) => {
      event.stopPropagation();
      copyText(value, label);
    });
    return button;
  }

  function deliveryWindow(order, node) {
    node.className = 'orders-delivery-window';
    if (!order.window_latest) {
      node.textContent = 'No window';
      return;
    }
    const latest = new Date(order.window_latest);
    if (!OPEN_STATUSES.has(order.status)) {
      node.textContent = order.window_earliest
        ? `${date(order.window_earliest, true, window.adminTimezone)} – ${date(order.window_latest, true, window.adminTimezone)}`
        : date(order.window_latest, true, window.adminTimezone);
      return;
    }
    const difference = latest.getTime() - Date.now();
    node.className = `orders-delivery-window${difference < 0 ? ' is-overdue' : ''}`;
    node.textContent = difference < 0 ? `Overdue ${humanDuration(difference)}` : `Due in ${humanDuration(difference)}`;
    node.title = date(order.window_latest, true, window.adminTimezone);
  }

  function renderRows() {
    tbody.replaceChildren();
    if (!state.rows.length) {
      const row = document.createElement('tr');
      const cell = document.createElement('td');
      cell.colSpan = 9;
      const noOrders = Object.values(state.counts).reduce((sum, value) => sum + Number(value || 0), 0) === 0
        && !state.q && !state.statuses.length && !state.merchantId && !state.warehouseId && !state.from && !state.to && !state.overdue;
      const empty = el('div', 'orders-empty');
      empty.append(el('strong', '', noOrders ? 'No orders yet.' : 'No orders match these filters.'));
      if (!noOrders) {
        const clear = el('button', 'button button-quiet', 'Reset filters');
        clear.type = 'button';
        clear.addEventListener('click', resetFilters);
        empty.append(clear);
      }
      cell.append(empty);
      row.append(cell);
      tbody.append(row);
    } else {
      state.rows.forEach((order) => {
        const row = document.createElement('tr');
        row.className = 'orders-row';
        row.tabIndex = 0;
        row.setAttribute('aria-label', `Inspect order ${order.merchant_order_ref}`);
        row.addEventListener('click', () => openOrder(order.tracking_token));
        row.addEventListener('keydown', (event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            openOrder(order.tracking_token);
          }
        });

        const orderCell = document.createElement('td');
        const reference = el('div', 'orders-ref-line');
        reference.append(el('strong', 'orders-reference', order.merchant_order_ref), copyButton(order.merchant_order_ref, 'order reference'));
        const tracking = el('div', 'orders-tracking-line');
        tracking.append(el('span', 'orders-tracking-code', order.tracking_token), copyButton(order.tracking_token, 'tracking code'));
        orderCell.append(reference, tracking);

        const merchantCell = el('td', 'orders-merchant-cell', order.merchant.name);
        const recipientCell = document.createElement('td');
        recipientCell.append(el('span', 'orders-recipient', order.recipient_name));
        if (order.is_guest) recipientCell.append(el('span', 'orders-guest-tag', 'Guest order'));
        const warehouseCell = el('td', 'orders-warehouse-code', order.warehouse.code);
        const statusCell = document.createElement('td'); statusCell.append(statusBadge(order.status));
        const windowCell = document.createElement('td'); deliveryWindow(order, windowCell); windowCell.dataset.orderWindow = JSON.stringify(order);
        const driverCell = document.createElement('td');
        if (order.driver) {
          const link = el('a', 'orders-driver-link', order.driver.full_name);
          link.href = `/admin/drivers?id=${encodeURIComponent(order.driver.id)}`;
          link.addEventListener('click', (event) => event.stopPropagation());
          driverCell.append(link);
        } else driverCell.textContent = '—';
        const createdCell = document.createElement('td');
        const created = el('time', 'orders-created', relativeTime(order.created_at));
        created.dateTime = order.created_at;
        created.title = date(order.created_at, true);
        createdCell.append(created);
        const inspectCell = document.createElement('td');
        const inspect = el('button', 'button button-quiet button-small', 'Inspect');
        inspect.type = 'button';
        inspect.addEventListener('click', (event) => { event.stopPropagation(); openOrder(order.tracking_token); });
        inspectCell.append(inspect);
        row.append(orderCell, merchantCell, recipientCell, warehouseCell, statusCell, windowCell, driverCell, createdCell, inspectCell);
        tbody.append(row);
      });
    }
    const shown = state.rows.length;
    resultSummary.textContent = `${shown.toLocaleString()} order${shown === 1 ? '' : 's'} shown${state.nextCursor ? ' · more available' : ''}`;
    loadMore.hidden = !state.nextCursor;
  }

  function section(title, content) {
    const block = el('section', 'drawer-section orders-drawer-section');
    block.append(el('h3', '', title), content);
    return block;
  }

  function field(label, value) {
    const node = el('div', 'orders-detail-field');
    node.append(el('span', '', label), el('strong', '', value ?? '—'));
    return node;
  }

  function externalLink(label, href, className = 'text-link') {
    const link = el('a', className, label);
    link.href = href;
    link.target = '_blank';
    link.rel = 'noreferrer';
    return link;
  }

  function entityLink(label, href) {
    const link = el('a', 'orders-entity-link', label);
    link.href = href;
    return link;
  }

  function renderDetail(data) {
    drawerLayer.replaceChildren();
    const backdrop = el('button', 'drawer-backdrop');
    backdrop.type = 'button';
    backdrop.setAttribute('aria-label', 'Close order details');
    backdrop.addEventListener('click', closeOrder);
    const drawer = el('aside', 'detail-drawer orders-detail-drawer');
    drawer.setAttribute('role', 'dialog');
    drawer.setAttribute('aria-modal', 'true');
    drawer.setAttribute('aria-label', `Order ${data.merchant_order_ref}`);

    const header = el('div', 'drawer-header');
    const heading = el('div');
    heading.append(el('h2', '', data.merchant_order_ref), el('p', 'drawer-subtitle', data.tracking_token));
    const close = el('button', 'drawer-close', 'Close');
    close.type = 'button'; close.addEventListener('click', closeOrder);
    header.append(heading, close);
    drawer.append(header);

    const caseSummary = el('div', 'orders-case-summary');
    caseSummary.append(statusBadge(data.status));
    caseSummary.append(field('Warehouse', `${data.warehouse.code} · ${data.warehouse.name}`));
    caseSummary.append(field('Latest driver', data.stops[0]?.driver?.full_name || '—'));
    caseSummary.append(field('Latest event', data.events[0] ? date(data.events[0].occurred_at, true) : date(data.created_at, true)));
    const copies = el('div', 'orders-case-copies');
    copies.append(copyButton(data.merchant_order_ref, 'order reference'), copyButton(data.tracking_token, 'tracking code'));
    const trackingPage = el('a', 'orders-entity-link', 'Open customer tracking page');
    trackingPage.href = `/track?code=${encodeURIComponent(data.tracking_token)}`;
    copies.append(trackingPage);
    caseSummary.append(copies);
    drawer.append(caseSummary);

    const events = el('ol', 'orders-timeline');
    if (!data.events.length) {
      events.append(el('li', 'orders-empty-inline', 'No status events recorded.'));
    } else {
      data.events.forEach((event, index) => {
        const item = el('li', `orders-timeline-item${event.to_status === 'attempt_failed' ? ' is-warning' : ''}${event.to_status === 'cancelled' ? ' is-neutral' : ''}`);
        const eventHeading = el('div', 'orders-timeline-heading');
        eventHeading.append(el('strong', '', event.from_status ? statusLabel(event.to_status) : 'Order created'));
        const timestamp = el('time', '', date(event.occurred_at, true));
        timestamp.dateTime = event.occurred_at;
        timestamp.title = new Date(event.occurred_at).toISOString();
        eventHeading.append(timestamp);
        item.append(eventHeading, el('p', '', event.actor?.full_name || 'System'));
        if (index < data.events.length - 1 && event.seconds_since_previous !== null) {
          item.append(el('small', '', `+${humanDuration(event.seconds_since_previous * 1000)} since previous event`));
        }
        events.append(item);
      });
    }
    if (OPEN_STATUSES.has(data.status) && data.events[0]) {
      drawer.append(el('p', 'orders-current-status-duration', `In current status for ${humanDuration(Date.now() - new Date(data.events[0].occurred_at).getTime())}`));
    }
    drawer.append(section('Status timeline', events));

    const attempts = el('div', 'orders-attempt-list');
    if (!data.stops.length) attempts.append(el('p', 'orders-muted', 'Not assigned to a route yet.'));
    data.stops.forEach((stop, index) => {
      const card = el('article', 'orders-attempt-card');
      const attemptHeading = el('div', 'orders-attempt-heading');
      attemptHeading.append(el('strong', '', `Attempt ${index + 1}`), el('span', `orders-stop-status orders-stop-${stop.status}`, statusLabel(stop.status)));
      card.append(attemptHeading);
      const driver = stop.driver
        ? entityLink(stop.driver.full_name, `/admin/drivers?id=${encodeURIComponent(stop.driver.id)}`)
        : el('span', '', '—');
      const vehicle = stop.vehicle
        ? `${statusLabel(stop.vehicle.type)} · ${stop.vehicle.registration_number}`
        : '—';
      const attemptFields = el('div', 'orders-detail-grid');
      attemptFields.append(field('Driver', ''), field('Vehicle', vehicle), field('Stop sequence', stop.sequence), field('Planned arrival', date(stop.planned_arrival_at, true)), field('Arrived', date(stop.arrived_at, true)), field('Completed', date(stop.completed_at, true)));
      attemptFields.querySelector('.orders-detail-field strong').replaceWith(driver);
      if (stop.failure_reason) attemptFields.append(field('Failure reason', statusLabel(stop.failure_reason)));
      card.append(attemptFields);
      if (stop.vehicle) {
        card.append(el('p', 'orders-route-load', `Route load: ${Number(stop.route_load.weight_kg).toFixed(1)} / ${Number(stop.vehicle.max_weight_kg).toFixed(1)} kg · ${Number(stop.route_load.volume_m3).toFixed(1)} / ${Number(stop.vehicle.max_volume_m3).toFixed(1)} m³`));
        if (stop.parcel_exceeds_vehicle) card.append(el('span', 'orders-capacity-warning', 'Parcel exceeds vehicle capacity'));
      }
      attempts.append(card);
    });
    drawer.append(section('Delivery attempts', attempts));

    const location = el('div', 'orders-detail-grid');
    location.append(field('Delivery address', data.delivery_address), field('Coordinates', `${Number(data.latitude).toFixed(6)}, ${Number(data.longitude).toFixed(6)}`));
    location.append(externalLink('Open drop-off in OpenStreetMap', `https://www.openstreetmap.org/?mlat=${encodeURIComponent(data.latitude)}&mlon=${encodeURIComponent(data.longitude)}#map=15/${encodeURIComponent(data.latitude)}/${encodeURIComponent(data.longitude)}`));
    const warehouseLink = entityLink(`${data.warehouse.code} · ${data.warehouse.name}`, `/admin/warehouses?id=${encodeURIComponent(data.warehouse.id)}`);
    location.append(field('Origin warehouse', ''), field('Straight-line distance', data.distance_km_straight == null ? '—' : `${Number(data.distance_km_straight).toFixed(1)} km`));
    location.querySelector('.orders-detail-field strong').replaceWith(warehouseLink);
    drawer.append(section('Location', location));

    const parties = el('div', 'orders-detail-grid');
    parties.append(
      field('Weight', `${Number(data.weight_kg).toFixed(3)} kg`),
      field('Volume', `${Number(data.volume_m3).toFixed(4)} m³`),
      field('Delivery window', data.window_earliest ? `${date(data.window_earliest, true, window.adminTimezone)} – ${date(data.window_latest, true, window.adminTimezone)}` : 'No window'),
      field('Recipient', data.recipient_name),
      field('Recipient phone', data.recipient_phone),
      field('Customer', data.customer?.full_name || 'Guest order')
    );
    const merchantLink = entityLink(data.merchant.name, `/admin/merchants?id=${encodeURIComponent(data.merchant.id)}`);
    parties.append(field('Merchant', ''));
    parties.lastElementChild.querySelector('strong').replaceWith(merchantLink);
    parties.append(field('Created', date(data.created_at, true)), field('Updated', date(data.updated_at, true)));
    drawer.append(section('Parcel and parties', parties));

    drawerLayer.append(backdrop, drawer);
    drawerLayer.hidden = false;
    close.focus();
  }

  async function openOrder(trackingToken) {
    state.detailToken = trackingToken;
    state.detailController?.abort();
    const controller = new AbortController();
    state.detailController = controller;
    const sequence = ++state.detailSequence;
    updateUrl();
    drawerLayer.replaceChildren();
    const backdrop = el('button', 'drawer-backdrop'); backdrop.type = 'button'; backdrop.setAttribute('aria-label', 'Close order details'); backdrop.addEventListener('click', closeOrder);
    const drawer = el('aside', 'detail-drawer orders-detail-drawer');
    drawer.setAttribute('role', 'dialog'); drawer.setAttribute('aria-modal', 'true'); drawer.setAttribute('aria-label', 'Loading order details');
    const close = el('button', 'drawer-close', 'Close'); close.type = 'button'; close.addEventListener('click', closeOrder);
    const header = el('div', 'drawer-header');
    header.append(el('h2', '', 'Order details'), close);
    drawer.append(header, el('p', 'drawer-loading', 'Loading order timeline and delivery details…'));
    drawerLayer.append(backdrop, drawer); drawerLayer.hidden = false;
    try {
      const data = await api.get(`/api/admin/orders/${encodeURIComponent(trackingToken)}`, { signal: controller.signal });
      if (state.disposed || sequence !== state.detailSequence) return;
      renderDetail(data);
    } catch (error) {
      if (error.name === 'AbortError' || state.disposed || sequence !== state.detailSequence) return;
      drawerLayer.replaceChildren();
      const background = el('button', 'drawer-backdrop'); background.type = 'button'; background.setAttribute('aria-label', 'Close order details'); background.addEventListener('click', closeOrder);
      const errorDrawer = el('aside', 'detail-drawer orders-detail-drawer');
      errorDrawer.setAttribute('role', 'dialog'); errorDrawer.setAttribute('aria-modal', 'true');
      const heading = el('div', 'drawer-header'); heading.append(el('h2', '', 'Order unavailable'));
      const dismiss = el('button', 'drawer-close', 'Close'); dismiss.type = 'button'; dismiss.addEventListener('click', closeOrder); heading.append(dismiss);
      errorDrawer.append(heading, el('p', 'drawer-loading', error.message || 'Order details could not be loaded.'));
      const retry = el('button', 'button button-secondary', 'Retry'); retry.type = 'button'; retry.addEventListener('click', () => openOrder(trackingToken));
      errorDrawer.append(retry);
      drawerLayer.append(background, errorDrawer);
    }
  }

  function closeOrder() {
    state.detailController?.abort();
    state.detailController = null;
    state.detailSequence += 1;
    state.detailToken = null;
    drawerLayer.hidden = true;
    drawerLayer.replaceChildren();
    updateUrl();
  }

  function resetFilters() {
    state.q = '';
    state.statuses = [];
    state.merchantId = '';
    state.warehouseId = '';
    state.from = '';
    state.to = '';
    state.overdue = false;
    state.limit = 25;
    search.value = '';
    merchant.value = '';
    warehouse.value = '';
    from.value = '';
    to.value = '';
    overdue.checked = false;
    pageSize.value = '25';
    updateUrl();
    loadOrders();
  }

  function applyFilters() {
    state.q = search.value.trim();
    state.merchantId = merchant.value;
    state.warehouseId = warehouse.value;
    state.from = toIso(from.value);
    state.to = toIso(to.value);
    state.overdue = overdue.checked;
    state.limit = Number(pageSize.value);
    updateUrl();
    loadOrders();
  }

  search.addEventListener('input', () => {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(applyFilters, 300);
  });
  [merchant, warehouse, from, to, overdue, pageSize].forEach((control) => control.addEventListener('change', applyFilters));
  reset.addEventListener('click', resetFilters);
  refreshButton.addEventListener('click', loadOrders);
  loadMore.addEventListener('click', loadMoreOrders);
  function onDrawerKeydown(event) {
    if (drawerLayer.hidden) return;
    if (event.key === 'Escape') {
      closeOrder();
      return;
    }
    if (event.key !== 'Tab') return;
    const focusable = [...drawerLayer.querySelectorAll('a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])')];
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }
  window.addEventListener('keydown', onDrawerKeydown);

  async function initialize() {
    renderChips();
    renderLoading();
    try {
      await loadFilterOptions();
    } catch (error) {
      state.loading = false;
      renderError(error, initialize);
      return;
    }
    if (state.disposed) return;
    loadOrders();
    timer = window.setInterval(() => {
      if (!document.hidden) tbody.querySelectorAll('[data-order-window]').forEach((node) => deliveryWindow(JSON.parse(node.dataset.orderWindow), node));
    }, 60000);
  }

  initialize();
  return {
    element: root,
    refresh: loadOrders,
    dispose() {
      state.disposed = true;
      state.listController?.abort();
      state.detailController?.abort();
      countController?.abort();
      window.clearTimeout(searchTimer);
      window.clearInterval(timer);
      window.removeEventListener('keydown', onDrawerKeydown);
    }
  };
}
