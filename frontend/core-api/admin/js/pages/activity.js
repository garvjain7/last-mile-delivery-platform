const ACTION_LABELS = {
  'driver.verify': 'Verified driver',
  'driver.reject': 'Rejected driver',
  'user.invite': 'Invited user',
  'user.deactivate': 'Deactivated user',
  'user.reactivate': 'Reactivated user',
  'user.unlock': 'Unlocked user',
  'user.revoke_sessions': 'Revoked user sessions',
  'user.send_reset': 'Sent password reset',
  'user.resend_invite': 'Resent invitation',
  'user.role_grant': 'Granted user role',
  'user.role_revoke': 'Revoked user role',
  'merchant.create': 'Created merchant',
  'merchant.update': 'Updated merchant',
  'merchant.deactivate': 'Deactivated merchant',
  'merchant.reactivate': 'Reactivated merchant',
  'warehouse.create': 'Created warehouse',
  'warehouse.update': 'Updated warehouse',
  'warehouse.deactivate': 'Deactivated warehouse',
  'warehouse.reactivate': 'Reactivated warehouse',
  'warehouse.staff_add': 'Added warehouse staff',
  'warehouse.staff_remove': 'Removed warehouse staff'
};
const TARGET_LABELS = {
  user: 'Users', driver: 'Drivers', merchant: 'Merchants', warehouse: 'Warehouses'
};
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function actionLabel(action) {
  return ACTION_LABELS[action] || String(action || '').split('.').at(-1).replaceAll('_', ' ');
}

function titleCase(value) {
  return String(value || '').replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function date(value) {
  if (!value) return '—';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? '—' : new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(parsed);
}

function localDateTime(value) {
  if (!value) return '';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return '';
  return new Date(parsed.getTime() - parsed.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

function toIso(value) {
  if (!value) return '';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? '' : parsed.toISOString();
}

function safeValue(value) {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'string' && UUID.test(value)) return 'Internal ID hidden';
  if (Array.isArray(value)) return `${value.length} item${value.length === 1 ? '' : 's'}`;
  if (typeof value === 'object') return `${Object.keys(value).length} field${Object.keys(value).length === 1 ? '' : 's'}`;
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  return String(value);
}

function detailEntries(details = {}) {
  const entries = [];
  if (details.reason !== undefined) entries.push(['Reason', safeValue(details.reason)]);
  if (details.role !== undefined) entries.push(['Role', titleCase(details.role)]);
  if (details.warehouse_ids !== undefined) entries.push(['Warehouse assignments', `${Array.isArray(details.warehouse_ids) ? details.warehouse_ids.length : 0} warehouse(s)`]);

  if (details.before && details.after && typeof details.before === 'object' && typeof details.after === 'object') {
    const keys = new Set([...Object.keys(details.before), ...Object.keys(details.after)]);
    keys.forEach((key) => {
      const before = details.before[key];
      const after = details.after[key];
      if (JSON.stringify(before) !== JSON.stringify(after)) {
        entries.push([titleCase(key), `${safeValue(before)} → ${safeValue(after)}`]);
      }
    });
  }

  Object.entries(details).forEach(([key, value]) => {
    if (['reason', 'role', 'warehouse_ids', 'before', 'after'].includes(key)) return;
    entries.push([titleCase(key), safeValue(value)]);
  });
  return entries;
}

function makeQuery(state) {
  const params = new URLSearchParams();
  if (state.action) params.set('action', state.action);
  if (state.actorId) params.set('actor_id', state.actorId);
  if (state.targetType) params.set('target_type', state.targetType);
  if (state.from) params.set('from', state.from);
  if (state.to) params.set('to', state.to);
  return params;
}

function targetHref(item) {
  const paths = {
    user: '/admin/users', driver: '/admin/drivers',
    merchant: '/admin/merchants', warehouse: '/admin/warehouses'
  };
  const path = paths[item.target_type];
  return path ? `${path}?id=${encodeURIComponent(item.target_id)}` : null;
}

export function createActivityPage({ api, onToast, route }) {
  const root = el('div', 'activity-page');
  const intro = el('div', 'page-intro');
  const introCopy = el('div');
  introCopy.append(
    el('h2', '', 'Admin activity'),
    el('p', '', 'Review the recorded actions taken in the admin console.')
  );
  const refresh = el('button', 'button button-secondary', 'Refresh');
  refresh.type = 'button';
  intro.append(introCopy, refresh);

  const filters = el('section', 'activity-filters panel');
  const action = document.createElement('select');
  action.setAttribute('aria-label', 'Filter by action');
  const actor = document.createElement('select');
  actor.setAttribute('aria-label', 'Filter by actor');
  const targetType = document.createElement('select');
  targetType.setAttribute('aria-label', 'Filter by target type');
  const from = document.createElement('input');
  from.type = 'datetime-local';
  from.setAttribute('aria-label', 'Activity from');
  const to = document.createElement('input');
  to.type = 'datetime-local';
  to.setAttribute('aria-label', 'Activity to');
  const reset = el('button', 'button button-quiet', 'Reset filters');
  reset.type = 'button';
  const field = (label, input) => {
    const wrapper = el('label', 'activity-filter-field', label);
    wrapper.append(input);
    return wrapper;
  };
  filters.append(
    field('Action', action), field('Actor', actor), field('Target type', targetType),
    field('From', from), field('To', to), reset
  );

  const panel = el('section', 'panel activity-table-panel');
  const panelHeader = el('div', 'activity-table-heading');
  panelHeader.append(el('h3', '', 'Recorded actions'));
  const summary = el('p', 'activity-result-summary', 'Loading activity…');
  panelHeader.append(summary);
  const scroll = el('div', 'activity-table-scroll');
  const table = document.createElement('table');
  table.className = 'activity-table';
  const thead = document.createElement('thead');
  const headerRow = document.createElement('tr');
  ['Time', 'Actor', 'Action', 'Target', 'Details'].forEach((label) => headerRow.append(el('th', '', label)));
  thead.append(headerRow);
  const tbody = document.createElement('tbody');
  table.append(thead, tbody);
  scroll.append(table);
  const footer = el('div', 'activity-table-footer');
  const loadMore = el('button', 'button button-secondary', 'Load more');
  loadMore.type = 'button';
  loadMore.hidden = true;
  footer.append(loadMore);
  panel.append(panelHeader, scroll, footer);
  root.append(intro, filters, panel);

  const query = route?.query || new URLSearchParams(window.location.search);
  const state = {
    action: query.get('action') || '',
    actorId: query.get('actor_id') || '',
    targetType: query.get('target_type') || '',
    from: query.get('from') || '',
    to: query.get('to') || '',
    rows: [],
    nextCursor: null,
    loading: false,
    loadingMore: false,
    sequence: 0,
    controller: null,
    disposed: false
  };
  action.value = state.action;
  actor.value = state.actorId;
  targetType.value = state.targetType;
  from.value = localDateTime(state.from);
  to.value = localDateTime(state.to);

  function updateUrl() {
    const params = makeQuery(state);
    const search = params.toString();
    const next = `${window.location.pathname}${search ? `?${search}` : ''}`;
    if (`${window.location.pathname}${window.location.search}` !== next) window.history.replaceState(null, '', next);
  }

  function fillSelect(select, values, defaultLabel, valueOf, labelOf) {
    select.replaceChildren();
    const empty = el('option', '', defaultLabel);
    empty.value = '';
    select.append(empty);
    values.forEach((value) => {
      const option = el('option', '', labelOf(value));
      option.value = valueOf(value);
      select.append(option);
    });
  }

  function fillActions(actions) {
    action.replaceChildren();
    const all = el('option', '', 'All actions'); all.value = '';
    action.append(all);
    const groups = new Map();
    actions.forEach((value) => {
      const groupName = TARGET_LABELS[value.split('.')[0]] || 'Other';
      if (!groups.has(groupName)) {
        const group = document.createElement('optgroup');
        group.label = groupName;
        groups.set(groupName, group);
        action.append(group);
      }
      const option = el('option', '', actionLabel(value));
      option.value = value;
      groups.get(groupName).append(option);
    });
    action.value = state.action;
  }

  async function loadFilters() {
    const data = await api.get('/api/admin/activity/filters');
    if (state.disposed) return;
    fillActions(data.actions);
    fillSelect(actor, data.actors, 'All actors', (item) => item.id, (item) => item.full_name);
    fillSelect(targetType, data.target_types, 'All target types', (value) => value, titleCase);
    action.value = state.action;
    actor.value = state.actorId;
    targetType.value = state.targetType;
  }

  function renderLoading(message = 'Loading activity…') {
    tbody.replaceChildren();
    const row = document.createElement('tr');
    const cell = el('td', 'activity-table-message', message);
    cell.colSpan = 5;
    row.append(cell);
    tbody.append(row);
    summary.textContent = message;
  }

  function renderError(error, retryAction = loadActivity) {
    tbody.replaceChildren();
    const row = document.createElement('tr');
    const cell = document.createElement('td'); cell.colSpan = 5;
    const message = el('div', 'activity-empty');
    message.append(el('strong', '', 'Activity could not be loaded.'), el('span', '', error.message || 'Try again.'));
    const retry = el('button', 'button button-secondary button-small', 'Retry'); retry.type = 'button'; retry.addEventListener('click', retryAction);
    message.append(retry); cell.append(message); row.append(cell); tbody.append(row);
    summary.textContent = 'Unable to load activity';
  }

  function targetCell(item) {
    const cell = el('div', 'activity-target');
    const href = targetHref(item);
    if (href) {
      const link = el('a', 'activity-target-link', item.target_label);
      link.href = href;
      cell.append(link);
    } else cell.append(el('span', '', item.target_label));
    cell.append(el('small', '', titleCase(item.target_type)));
    return cell;
  }

  function renderDetails(details) {
    const entries = detailEntries(details);
    if (!entries.length) return el('span', 'activity-no-details', '—');
    const disclosure = document.createElement('details');
    disclosure.className = 'activity-details';
    const summaryLine = document.createElement('summary');
    summaryLine.textContent = entries.slice(0, 2).map(([key, value]) => `${key}: ${value}`).join(' · ');
    disclosure.append(summaryLine);
    const list = el('dl', 'activity-detail-list');
    entries.forEach(([key, value]) => list.append(el('dt', '', key), el('dd', '', value)));
    disclosure.append(list);
    return disclosure;
  }

  function renderRows(append = false) {
    if (!append) tbody.replaceChildren();
    if (!state.rows.length && !append) {
      const row = document.createElement('tr');
      const cell = document.createElement('td'); cell.colSpan = 5;
      const noFilters = !state.action && !state.actorId && !state.targetType && !state.from && !state.to;
      const empty = el('div', 'activity-empty');
      empty.append(el('strong', '', noFilters ? 'No admin activity recorded yet.' : 'No activity matches these filters.'));
      if (!noFilters) {
        const clear = el('button', 'button button-quiet', 'Reset filters'); clear.type = 'button'; clear.addEventListener('click', resetFilters);
        empty.append(clear);
      }
      cell.append(empty); row.append(cell); tbody.append(row);
    }

    const start = append ? tbody.querySelectorAll('tr.activity-row').length : 0;
    state.rows.slice(start).forEach((item) => {
      const row = el('tr', 'activity-row');
      const timestampCell = document.createElement('td');
      const timestamp = el('time', 'activity-time', date(item.occurred_at));
      timestamp.dateTime = item.occurred_at;
      timestamp.title = new Date(item.occurred_at).toISOString();
      timestampCell.append(timestamp);
      const actorCell = el('td', 'activity-actor', item.actor?.full_name || 'System / deleted admin');
      const actionCell = el('td', 'activity-action');
      actionCell.append(el('span', 'activity-action-label', actionLabel(item.action)), el('small', '', item.action));
      const target = document.createElement('td'); target.append(targetCell(item));
      const details = document.createElement('td'); details.className = 'activity-details-cell'; details.append(renderDetails(item.details));
      row.append(timestampCell, actorCell, actionCell, target, details);
      tbody.append(row);
    });
    const count = tbody.querySelectorAll('tr.activity-row').length;
    summary.textContent = `${count.toLocaleString()} entr${count === 1 ? 'y' : 'ies'} shown${state.nextCursor ? ' · more available' : ''}`;
    loadMore.hidden = !state.nextCursor;
  }

  async function loadActivity() {
    state.controller?.abort();
    const controller = new AbortController();
    state.controller = controller;
    const sequence = ++state.sequence;
    state.loading = true;
    state.rows = [];
    state.nextCursor = null;
    loadMore.hidden = true;
    renderLoading();
    updateUrl();
    const params = makeQuery(state);
    params.set('limit', '25');
    try {
      const response = await api.get(`/api/admin/activity?${params}`, { signal: controller.signal });
      if (state.disposed || sequence !== state.sequence) return;
      state.rows = response.items;
      state.nextCursor = response.next_cursor;
      state.loading = false;
      renderRows();
    } catch (error) {
      if (error.name === 'AbortError' || state.disposed || sequence !== state.sequence) return;
      state.loading = false;
      renderError(error);
    }
  }

  async function loadMoreActivity() {
    if (!state.nextCursor || state.loadingMore || state.loading) return;
    const sequence = state.sequence;
    state.loadingMore = true;
    loadMore.disabled = true;
    loadMore.textContent = 'Loading…';
    const params = makeQuery(state);
    params.set('limit', '25');
    params.set('cursor', state.nextCursor);
    try {
      const response = await api.get(`/api/admin/activity?${params}`);
      if (state.disposed || sequence !== state.sequence) return;
      const previousCount = state.rows.length;
      state.rows.push(...response.items);
      state.nextCursor = response.next_cursor;
      renderRows(true);
      if (state.rows.length === previousCount) loadMore.hidden = true;
    } catch (error) {
      if (!state.disposed) onToast(error.message || 'Could not load more activity.', 'error');
    } finally {
      state.loadingMore = false;
      loadMore.disabled = false;
      loadMore.textContent = 'Load more';
    }
  }

  function applyFilters() {
    state.action = action.value;
    state.actorId = actor.value;
    state.targetType = targetType.value;
    state.from = toIso(from.value);
    state.to = toIso(to.value);
    loadActivity();
  }

  function resetFilters() {
    state.action = '';
    state.actorId = '';
    state.targetType = '';
    state.from = '';
    state.to = '';
    action.value = '';
    actor.value = '';
    targetType.value = '';
    from.value = '';
    to.value = '';
    loadActivity();
  }

  [action, actor, targetType, from, to].forEach((control) => control.addEventListener('change', applyFilters));
  reset.addEventListener('click', resetFilters);
  refresh.addEventListener('click', loadActivity);
  loadMore.addEventListener('click', loadMoreActivity);

  async function initialize() {
    renderLoading();
    try {
      await loadFilters();
      if (!state.disposed) loadActivity();
    } catch (error) {
      if (!state.disposed) renderError(error, initialize);
    }
  }

  initialize();
  return {
    element: root,
    refresh: loadActivity,
    dispose() {
      state.disposed = true;
      state.controller?.abort();
    }
  };
}
