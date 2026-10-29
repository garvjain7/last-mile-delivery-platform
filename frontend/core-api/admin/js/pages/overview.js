const ORDER_STATES = [
  { key: 'pending', label: 'Pending', css: 'segment-pending' },
  { key: 'assigned', label: 'Assigned', css: 'segment-assigned' },
  { key: 'out_for_delivery', label: 'Out for delivery', css: 'segment-out' },
  { key: 'attempt_failed', label: 'Failed attempt', css: 'segment-failed' }
];

const DRIVER_STATES = [
  { key: 'available', label: 'Available' },
  { key: 'on_route', label: 'On route' },
  { key: 'offline', label: 'Offline' }
];

const ROLE_LABELS = {
  customer: 'Customers', merchant: 'Merchant accounts', dispatcher: 'Dispatchers',
  driver: 'Drivers', fleet_manager: 'Fleet managers', admin: 'Administrators'
};

const ACTION_LABELS = {
  'driver.verify': 'verified driver', 'driver.reject': 'rejected driver',
  'user.invite': 'invited staff', 'user.deactivate': 'deactivated account',
  'user.reactivate': 'reactivated account', 'user.unlock': 'unlocked account',
  'user.revoke_sessions': 'signed out user sessions', 'user.send_reset': 'sent a password reset',
  'user.resend_invite': 'resent an invitation', 'user.role_grant': 'granted a role',
  'user.role_revoke': 'revoked a role', 'merchant.create': 'created merchant',
  'merchant.update': 'updated merchant', 'merchant.deactivate': 'deactivated merchant',
  'merchant.reactivate': 'reactivated merchant', 'warehouse.create': 'created warehouse',
  'warehouse.update': 'updated warehouse', 'warehouse.deactivate': 'deactivated warehouse',
  'warehouse.reactivate': 'reactivated warehouse', 'warehouse.staff_add': 'assigned warehouse staff',
  'warehouse.staff_remove': 'removed warehouse staff'
};

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function formatInteger(value) {
  return new Intl.NumberFormat().format(Number(value) || 0);
}

function formatDate(value, timezone, options = {}) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return new Intl.DateTimeFormat(undefined, {
    timeZone: timezone,
    month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', ...options
  }).format(date);
}

function timeSince(value, timezone) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  const minutes = Math.max(0, Math.floor((Date.now() - date.getTime()) / 60000));
  if (minutes < 1) return 'Just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ${minutes % 60}m ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ${hours % 24}h ago`;
}

function midnightForLocalDate(year, month, day, timezone) {
  const localMidnightAsUtc = Date.UTC(year, month - 1, day);
  const represented = new Intl.DateTimeFormat('en-US', {
    timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23'
  }).formatToParts(new Date(localMidnightAsUtc)).reduce((result, item) => {
    if (item.type !== 'literal') result[item.type] = Number(item.value);
    return result;
  }, {});
  const representedAsUtc = Date.UTC(represented.year, represented.month - 1, represented.day,
    represented.hour, represented.minute, represented.second);
  return new Date(localMidnightAsUtc - (representedAsUtc - localMidnightAsUtc));
}

function todayRange(timezone) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit'
  }).formatToParts(new Date()).reduce((result, item) => {
    if (item.type !== 'literal') result[item.type] = Number(item.value);
    return result;
  }, {});
  const nextDate = new Date(Date.UTC(parts.year, parts.month - 1, parts.day + 1));
  const start = midnightForLocalDate(parts.year, parts.month, parts.day, timezone);
  const next = midnightForLocalDate(nextDate.getUTCFullYear(), nextDate.getUTCMonth() + 1, nextDate.getUTCDate(), timezone);
  return { from: start.toISOString(), to: new Date(next.getTime() - 1).toISOString() };
}

function appendEmpty(parent, title, hint) {
  const empty = element('div', 'empty-inline');
  empty.append(element('strong', '', title), document.createTextNode(hint));
  parent.append(empty);
}

function createSectionHeading(title, actionText, href) {
  const heading = element('div', 'section-label');
  heading.append(element('h2', '', title));
  if (actionText && href) {
    const link = element('a', 'text-link', actionText);
    link.href = href;
    heading.append(link);
  }
  return heading;
}

function createPanelHeading(title, count, tone, viewAllHref) {
  const heading = element('div', 'panel-heading');
  const titleGroup = element('div', 'panel-title');
  titleGroup.append(element('h3', '', title));
  const pill = element('span', `count-pill ${tone || ''}`, formatInteger(count));
  pill.setAttribute('aria-label', `${formatInteger(count)} items`);
  titleGroup.append(pill);
  heading.append(titleGroup);
  if (viewAllHref) {
    const link = element('a', 'text-link', 'View all');
    link.href = viewAllHref;
    heading.append(link);
  }
  return heading;
}

function renderKpis(data, timezone) {
  const grid = element('section', 'kpi-grid');
  grid.setAttribute('aria-label', 'Platform performance');
  const { from: todayStart, to: todayEnd } = todayRange(timezone);
  // The Orders API filters its date range on orders.created_at. The delivered
  // and failed-today KPIs count order_events, so those cards stay non-clickable
  // until the API can filter by event time without implying a false match.
  const cards = [
    ['Orders today', data.kpis.orders_today, 'Created in platform timezone', `/admin/orders?from=${encodeURIComponent(todayStart)}&to=${encodeURIComponent(todayEnd)}`],
    ['Open orders', data.kpis.open_orders, 'Across active delivery states', '/admin/orders?status=pending&status=assigned&status=out_for_delivery&status=attempt_failed'],
    ['Delivered today', data.kpis.delivered_today, 'Delivery events recorded today', null],
    ['Failed attempts today', data.kpis.failed_attempts_today, 'Delivery events recorded today', null],
    ['Delivery success · 7 days', data.kpis.delivery_success_rate_7d === null ? '—' : `${(data.kpis.delivery_success_rate_7d * 100).toFixed(1)}%`, 'Delivered ÷ (delivered + failed)', null]
  ];
  for (const [label, value, foot, href] of cards) {
    const card = href ? element('a', 'kpi-card') : element('article', 'kpi-card');
    if (href) card.href = href;
    card.append(element('span', 'kpi-accent'));
    card.append(element('span', 'kpi-label', label));
    card.append(element('strong', 'kpi-value', typeof value === 'number' ? formatInteger(value) : value));
    card.append(element('span', 'kpi-foot', foot));
    grid.append(card);
  }
  return grid;
}

function makeAttentionPanel({ title, section, tone, href, items, count, createRow, emptyTitle, emptyHint }) {
  const panel = element('section', 'panel attention-panel');
  panel.append(createPanelHeading(title, count, tone, href));
  const list = element('div', 'attention-list');
  list.setAttribute('role', 'list');
  if (!items.length) {
    appendEmpty(list, emptyTitle, emptyHint);
  } else {
    items.forEach((item) => {
      const row = createRow(item);
      row.classList.add('attention-row');
      row.setAttribute('role', 'listitem');
      list.append(row);
    });
  }
  panel.append(list);
  panel.dataset.section = section;
  return panel;
}

function makeTextRow(primary, secondary, age, linkHref) {
  const row = element('div', 'attention-row');
  const main = element(linkHref ? 'a' : 'div', 'attention-main');
  if (linkHref) main.href = linkHref;
  main.append(element('strong', '', primary), element('span', '', secondary));
  if (age) row.append(main, element('span', 'attention-age', age));
  else row.append(main);
  return row;
}

function renderAttention(data, timezone, act) {
  const grid = element('section', 'attention-grid');
  grid.setAttribute('aria-label', 'Needs attention');
  const needs = data.needs_attention;

  grid.append(makeAttentionPanel({
    title: 'Drivers awaiting approval', section: 'pending-drivers', tone: 'warning', href: '/admin/drivers?segment=pending',
    items: needs.pending_drivers.items, count: needs.pending_drivers.count,
    emptyTitle: 'No drivers waiting for approval', emptyHint: 'New driver applications will appear here.',
    createRow: (item) => {
      const row = makeTextRow(item.full_name, `Registered ${formatDate(item.created_at, timezone)}`, timeSince(item.created_at, timezone));
      const button = element('button', 'button button-quiet', 'Verify');
      button.type = 'button';
      button.addEventListener('click', () => act({
        button, path: `/api/admin/drivers/${encodeURIComponent(item.user_id)}/verify`,
        success: `${item.full_name} is verified.`, section: 'pending-drivers'
      }));
      row.append(button);
      return row;
    }
  }));

  grid.append(makeAttentionPanel({
    title: 'Locked accounts', section: 'locked-users', tone: 'danger', href: '/admin/users?status=locked',
    items: needs.locked_users.items, count: needs.locked_users.count,
    emptyTitle: 'No locked accounts', emptyHint: 'Accounts requiring an unlock will appear here.',
    createRow: (item) => {
      const row = makeTextRow(item.full_name, `Locked until ${formatDate(item.locked_until, timezone)}`);
      const button = element('button', 'button button-quiet', 'Unlock');
      button.type = 'button';
      button.addEventListener('click', () => act({
        button, path: `/api/admin/users/${encodeURIComponent(item.id)}/unlock`,
        success: `${item.full_name} is unlocked.`, section: 'locked-users'
      }));
      row.append(button);
      return row;
    }
  }));

  grid.append(makeAttentionPanel({
    title: 'Stale pending orders', section: 'stale-orders', tone: 'warning', href: '/admin/orders?status=pending',
    items: needs.stale_pending_orders.items, count: needs.stale_pending_orders.count,
    emptyTitle: 'No stale pending orders', emptyHint: 'Pending orders over the configured age threshold appear here.',
    createRow: (item) => makeTextRow(item.merchant_order_ref, item.merchant_name, timeSince(item.created_at, timezone), `/admin/orders?q=${encodeURIComponent(item.tracking_token)}`)
  }));

  grid.append(makeAttentionPanel({
    title: 'Failed delivery attempts', section: 'failed-orders', tone: 'danger', href: '/admin/orders?status=attempt_failed',
    items: needs.failed_attempt_orders.items, count: needs.failed_attempt_orders.count,
    emptyTitle: 'No failed attempts', emptyHint: 'Orders with a failed delivery attempt appear here.',
    createRow: (item) => makeTextRow(item.merchant_order_ref, item.merchant_name, timeSince(item.updated_at, timezone), `/admin/orders?q=${encodeURIComponent(item.tracking_token)}`)
  }));
  return grid;
}

function renderOrderStatus(data) {
  const panel = element('section', 'panel insight-panel');
  panel.append(createSectionHeading('Open orders by status'));
  const values = ORDER_STATES.map((state) => ({ ...state, value: Number(data.open_orders_by_status[state.key]) || 0 }));
  const total = values.reduce((sum, state) => sum + state.value, 0);
  const bars = element('div', 'status-bars');
  const summary = element('div', 'bar-summary');
  summary.append(element('span', '', 'Current open workload'), element('strong', '', `${formatInteger(total)} orders`));
  bars.append(summary);
  const track = element('div', 'stacked-track');
  track.setAttribute('role', 'img');
  track.setAttribute('aria-label', values.map((state) => `${state.label}: ${formatInteger(state.value)}`).join(', '));
  values.forEach((state) => {
    const segment = element('span', `stacked-segment ${state.css}`);
    segment.style.width = total ? `${(state.value / total) * 100}%` : '0%';
    segment.title = `${state.label}: ${formatInteger(state.value)}`;
    track.append(segment);
  });
  bars.append(track);
  const legend = element('div', 'legend-row');
  values.forEach((state) => {
    const item = element('span', 'legend-item');
    item.append(element('i', `legend-dot ${state.key === 'out_for_delivery' ? 'out' : state.key === 'attempt_failed' ? 'failed' : state.key}`));
    const percentage = total ? Math.round((state.value / total) * 100) : 0;
    item.append(document.createTextNode(`${state.label} · ${formatInteger(state.value)} (${percentage}%)`));
    legend.append(item);
  });
  bars.append(legend);
  panel.append(bars);
  return panel;
}

function renderDriverSupply(data) {
  const panel = element('section', 'panel insight-panel');
  panel.append(createSectionHeading('Driver supply'));
  const supply = DRIVER_STATES.map((state) => ({ ...state, value: Number(data.drivers_by_status[state.key]) || 0 }));
  const max = Math.max(1, ...supply.map((item) => item.value));
  const list = element('div', 'supply-list');
  supply.forEach((state) => {
    const row = element('div', 'supply-row');
    row.append(element('span', 'supply-label', state.label));
    const track = element('div', 'supply-track');
    const fill = element('div', 'supply-fill');
    fill.style.width = `${(state.value / max) * 100}%`;
    track.append(fill);
    track.setAttribute('aria-hidden', 'true');
    row.append(track, element('strong', 'supply-value', formatInteger(state.value)));
    list.append(row);
  });
  panel.append(list);
  const secondary = element('div', 'supply-secondary');
  const pending = element('span');
  pending.append(document.createTextNode('Pending '), element('strong', '', formatInteger(data.drivers_by_status.pending)));
  const rejected = element('span');
  rejected.append(document.createTextNode('Rejected '), element('strong', '', formatInteger(data.drivers_by_status.rejected)));
  secondary.append(pending, rejected);
  panel.append(secondary);
  return panel;
}

function renderWarehouseTable(warehouses) {
  const panel = element('section', 'panel table-panel');
  panel.append(createSectionHeading('Warehouse activity', 'All warehouses', '/admin/warehouses'));
  if (!warehouses.length) {
    appendEmpty(panel, 'No active warehouses', 'Add a warehouse before assigning staff and orders.');
    return panel;
  }
  const table = element('table', 'overview-table');
  const caption = element('caption');
  caption.className = 'visually-hidden';
  caption.textContent = 'Active warehouses with open order and route counts';
  table.append(caption);
  const head = document.createElement('thead');
  const headRow = document.createElement('tr');
  [['Warehouse', 'text'], ['Open orders', 'number-cell'], ['Active routes', 'number-cell']].forEach(([label, className]) => {
    const th = element('th', className, label);
    th.scope = 'col';
    headRow.append(th);
  });
  head.append(headRow);
  const body = document.createElement('tbody');
  warehouses.forEach((warehouse) => {
    const row = document.createElement('tr');
    const nameCell = document.createElement('td');
    const code = element('a', 'warehouse-code', warehouse.code);
    code.href = `/admin/warehouses?id=${encodeURIComponent(warehouse.id)}`;
    const name = element('span', 'warehouse-name', warehouse.name);
    code.append(name);
    nameCell.append(code);
    const orders = element('td', 'number-cell', formatInteger(warehouse.open_orders));
    const routes = element('td', 'number-cell', formatInteger(warehouse.active_routes));
    row.append(nameCell, orders, routes);
    body.append(row);
  });
  table.append(head, body);
  panel.append(table);
  return panel;
}

function renderRoles(data) {
  const panel = element('section', 'panel');
  panel.append(createSectionHeading('Accounts by role', 'Manage users', '/admin/users'));
  const list = element('div', 'role-list');
  Object.entries(ROLE_LABELS).forEach(([role, label]) => {
    const row = element('div', 'role-row');
    const link = element('a', 'role-name', label);
    link.href = `/admin/users?role=${encodeURIComponent(role)}`;
    row.append(link, element('strong', 'role-count', formatInteger(data.users_by_role[role])));
    list.append(row);
  });
  panel.append(list);
  return panel;
}

function renderActivity(items, timezone) {
  const panel = element('section', 'panel activity-panel');
  panel.append(createSectionHeading('Recent admin activity', 'View activity log', '/admin/activity'));
  const list = element('div', 'activity-list');
  if (!items.length) {
    appendEmpty(list, 'No admin activity recorded yet', 'Admin actions will appear here for review.');
  } else {
    items.forEach((item) => {
      const row = element('div', 'activity-row');
      const icon = element('span', 'activity-icon');
      icon.setAttribute('aria-hidden', 'true');
      icon.innerHTML = '<svg viewBox="0 0 24 24"><path d="M5 12.5 9.2 17 19 7"/></svg>';
      const description = element('span', 'activity-description');
      const actor = item.actor_name || 'An administrator';
      const verb = ACTION_LABELS[item.action] || item.action.split(/[._]/).join(' ');
      description.append(element('strong', '', actor), document.createTextNode(` ${verb}: ${item.target_label}`));
      row.append(icon, description);
      const time = element('time', 'activity-time', timeSince(item.occurred_at, timezone));
      time.dateTime = item.occurred_at;
      time.title = formatDate(item.occurred_at, timezone, { year: 'numeric', second: '2-digit' });
      row.append(time);
      list.append(row);
    });
  }
  panel.append(list);
  return panel;
}

function createSkeleton() {
  const section = element('section', 'overview-skeleton');
  section.setAttribute('aria-label', 'Loading platform overview');
  section.setAttribute('aria-busy', 'true');
  const top = element('div', 'skeleton-layout');
  for (let i = 0; i < 5; i += 1) top.append(element('div', 'skeleton skeleton-kpi'));
  const row = element('div', 'skeleton-row');
  row.append(element('div', 'skeleton skeleton-panel'), element('div', 'skeleton skeleton-panel'));
  section.append(top, row);
  return section;
}

function renderError(message, onRetry, asAlert = true) {
  const box = element('section', `page-message${asAlert ? '' : ' page-notice'}`);
  if (asAlert) box.setAttribute('role', 'alert');
  else box.setAttribute('role', 'status');
  const content = element('div', 'message-content');
  content.append(element('strong', '', asAlert ? 'Overview could not be refreshed' : 'Updating platform data'), element('p', '', message));
  const retry = element('button', 'button button-secondary', 'Retry');
  retry.type = 'button';
  retry.addEventListener('click', onRetry);
  box.append(content, retry);
  return box;
}

export function createOverviewPage({ api, timezone, onToast, onPageTitle }) {
  let data = null;
  let isLoading = false;
  let lastError = null;
  let lastRefreshed = null;
  let requestId = 0;
  let timer = null;
  let controller = null;
  const root = element('div', 'overview-page');

  async function performAction(action) {
    action.button.disabled = true;
    action.button.textContent = 'Working…';
    try {
      await api.post(action.path, {});
      onToast(action.success);
      await load({ quiet: true });
    } catch (error) {
      action.button.disabled = false;
      action.button.textContent = action.section === 'pending-drivers' ? 'Verify' : 'Unlock';
      onToast(error.message || 'The action could not be completed.', 'error');
    }
  }

  function render() {
    root.replaceChildren();
    root.setAttribute('aria-busy', String(isLoading));
    if (!data && isLoading) {
      root.append(createSkeleton());
      return;
    }
    if (!data && lastError) {
      root.append(renderError(lastError.message, () => load()));
      return;
    }
    if (!data) return;

    if (lastError) {
      root.append(renderError(lastError.message, () => load({ quiet: true }), false));
    }
    const intro = element('div', 'page-intro');
    const copy = element('div');
    copy.append(element('h2', '', 'Platform operations at a glance'));
    copy.append(element('p', '', 'Review delivery workload, service exceptions, and administrator activity.'));
    intro.append(copy);
    root.append(intro, renderKpis(data, timezone), renderAttention(data, timezone, performAction));

    const insights = element('div', 'insight-grid');
    insights.append(renderOrderStatus(data), renderDriverSupply(data));
    root.append(insights);

    const bottom = element('div', 'bottom-grid');
    bottom.append(renderWarehouseTable(data.warehouses), renderRoles(data));
    root.append(bottom, renderActivity(data.recent_activity, timezone));
  }

  async function load({ quiet = false } = {}) {
    if (isLoading) return;
    isLoading = true;
    root.setAttribute('aria-busy', 'true');
    const thisRequest = ++requestId;
    controller = new AbortController();
    if (!quiet || !data) render();
    try {
      const response = await api.get('/api/admin/overview', { signal: controller.signal });
      if (thisRequest !== requestId) return;
      data = response;
      lastRefreshed = new Date();
      lastError = null;
      window.dispatchEvent(new CustomEvent('admin:data-refreshed', { detail: { at: lastRefreshed } }));
    } catch (error) {
      if (thisRequest !== requestId) return;
      lastError = error;
      if (!data) onPageTitle('Overview');
    } finally {
      if (thisRequest === requestId) {
        isLoading = false;
        render();
      }
    }
  }

  function startAutoRefresh() {
    if (timer) window.clearInterval(timer);
    timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') load({ quiet: true });
    }, 60000);
  }

  function destroy() {
    if (timer) window.clearInterval(timer);
    timer = null;
    requestId += 1;
    controller?.abort();
  }

  render();
  load();
  startAutoRefresh();
  return { element: root, refresh: () => load({ quiet: Boolean(data) }), destroy, get lastRefreshed() { return lastRefreshed; } };
}

export { renderError };
