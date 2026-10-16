const SEGMENTS = [
  ['pending', 'Pending'], ['active', 'Active'], ['rejected', 'Rejected'], ['all', 'All drivers']
];
const SORTS = [
  ['created_at', 'Registered'], ['full_name', 'Name'], ['last_login_at', 'Last login'], ['status', 'Status']
];

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}
function date(value) {
  if (!value) return 'Never';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? '—' : new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(parsed);
}
function badge(value) {
  const labels = { pending: 'Pending review', offline: 'Offline', available: 'Available', on_route: 'On route', rejected: 'Rejected' };
  const node = el('span', `driver-status status-${value}`, labels[value] || value);
  return node;
}
function sectionTitle(title, copy) {
  const wrap = el('div', 'section-label');
  wrap.append(el('h2', '', title), el('p', '', copy));
  return wrap;
}

export function createDriversPage({ api, onToast, route }) {
  const root = el('div', 'drivers-page');
  const intro = el('div', 'page-intro');
  const introCopy = el('div');
  introCopy.append(el('h2', '', 'Driver approvals and roster'), el('p', '', 'Review new applications, check operational status, and manage driver access.'));
  intro.append(introCopy);
  const toolbar = el('div', 'driver-toolbar');
  const search = document.createElement('input');
  search.type = 'search'; search.maxLength = 100; search.placeholder = 'Search name, email, phone or vehicle';
  search.setAttribute('aria-label', 'Search drivers');
  const sort = document.createElement('select'); sort.setAttribute('aria-label', 'Sort drivers');
  SORTS.forEach(([value, label]) => { const option = el('option', '', label); option.value = value; sort.append(option); });
  const direction = document.createElement('button'); direction.type = 'button'; direction.className = 'button button-secondary driver-direction';
  const refresh = document.createElement('button'); refresh.type = 'button'; refresh.className = 'button button-secondary'; refresh.textContent = 'Refresh';
  toolbar.append(search, sort, direction, refresh);
  const tabs = el('div', 'driver-tabs'); tabs.setAttribute('role', 'tablist'); tabs.setAttribute('aria-label', 'Driver segments');
  const tablePanel = el('section', 'panel driver-table-panel');
  const tableHeading = sectionTitle('Drivers', 'Operational status and account access are shown separately.');
  const bulkBar = el('div', 'driver-bulk-bar'); bulkBar.hidden = true;
  const selectedText = el('span', '', '0 selected');
  const bulkVerify = el('button', 'button button-primary button-small', 'Verify selected'); bulkVerify.type = 'button';
  const bulkReject = el('button', 'button button-secondary button-small', 'Reject selected'); bulkReject.type = 'button';
  const clearSelection = el('button', 'text-link', 'Clear selection'); clearSelection.type = 'button';
  bulkBar.append(selectedText, bulkVerify, bulkReject, clearSelection);
  const scroll = el('div', 'driver-table-scroll');
  const table = el('table', 'driver-table');
  const body = document.createElement('tbody');
  const head = document.createElement('thead');
  const headRow = document.createElement('tr');
  ['','Driver','Operational status','Vehicle','Registered','Last login','Account',''].forEach((label) => {
    const th = el('th', '', label); if (!label) th.setAttribute('aria-label', 'Select or open'); headRow.append(th);
  });
  head.append(headRow); table.append(head, body); scroll.append(table);
  const pagination = el('div', 'driver-pagination');
  tablePanel.append(tableHeading, bulkBar, scroll, pagination);
  const drawerLayer = el('div', 'drawer-layer'); drawerLayer.hidden = true;
  root.append(intro, tabs, toolbar, tablePanel, drawerLayer);

  const query = route?.query || new URLSearchParams();
  const state = {
    segment: SEGMENTS.some(([key]) => key === query.get('segment')) ? query.get('segment') : 'pending',
    q: (query.get('q') || '').slice(0, 100),
    page: Math.max(1, Number.isSafeInteger(Number(query.get('page'))) ? Number(query.get('page')) : 1),
    pageSize: 25, total: 0, counts: {}, rows: [], selected: new Set(), loading: false,
    drawerId: null, drawerData: null,
    sort: SORTS.some(([key]) => key === query.get('sort')) ? query.get('sort') : 'created_at',
    dir: ['asc', 'desc'].includes(query.get('dir')) ? query.get('dir') : (query.get('segment') === 'pending' ? 'asc' : 'desc'),
    disposed: false, requestSeq: 0, initialDriverId: route?.itemId || null
  };
  search.value = state.q;
  sort.value = state.sort;
  let searchTimer;

  function updateUrl() {
    const params = new URLSearchParams();
    params.set('segment', state.segment);
    if (search.value.trim()) params.set('q', search.value.trim());
    if (state.sort !== 'created_at') params.set('sort', state.sort);
    if (state.dir !== (state.segment === 'pending' ? 'asc' : 'desc')) params.set('dir', state.dir);
    if (state.page > 1) params.set('page', String(state.page));
    const drawerId = state.drawerId || state.initialDriverId;
    if (drawerId) params.set('id', drawerId);
    const queryString = params.toString();
    const target = `${window.location.pathname}${queryString ? `?${queryString}` : ''}`;
    if (`${window.location.pathname}${window.location.search}` !== target) window.history.replaceState(null, '', target);
  }

  function refreshTabs() {
    tabs.replaceChildren();
    SEGMENTS.forEach(([key, label]) => {
      const button = el('button', `driver-tab${state.segment === key ? ' is-active' : ''}`);
      button.type = 'button'; button.setAttribute('role', 'tab'); button.setAttribute('aria-selected', String(state.segment === key));
      button.append(document.createTextNode(label));
      const count = el('span', 'driver-tab-count', state.counts[key] ?? '—'); button.append(count);
      button.addEventListener('click', () => { if (state.segment === key) return; state.segment = key; state.dir = key === 'pending' ? 'asc' : 'desc'; updateDirection(); state.page = 1; state.selected.clear(); load(); });
      tabs.append(button);
    });
  }
  function renderLoading() {
    body.replaceChildren();
    const row = document.createElement('tr'); const cell = el('td', 'driver-table-message', 'Loading drivers…'); cell.colSpan = 8; row.append(cell); body.append(row);
  }
  function renderEmpty() {
    body.replaceChildren();
    const row = document.createElement('tr'); const cell = document.createElement('td'); cell.colSpan = 8;
    const box = el('div', 'driver-empty');
    const searched = search.value.trim().length >= 2;
    box.append(el('strong', '', searched ? 'No drivers match this search.' : state.segment === 'pending' ? 'No drivers waiting for approval.' : 'No drivers in this segment.'),
      el('span', '', searched ? 'Try a different name, email, phone or vehicle registration.' : 'Driver records will appear here as they register.'));
    if (searched) { const clear = el('button', 'text-link', 'Clear search'); clear.type = 'button'; clear.addEventListener('click', () => { search.value = ''; state.page = 1; load(); }); box.append(clear); }
    cell.append(box); row.append(cell); body.append(row);
  }
  function updateBulkBar() {
    const eligible = state.segment === 'pending' || state.segment === 'rejected';
    bulkBar.hidden = !eligible || state.selected.size === 0;
    selectedText.textContent = `${state.selected.size} selected`;
    bulkVerify.hidden = !eligible;
    bulkReject.hidden = !eligible || state.segment !== 'pending';
    bulkVerify.disabled = state.loading; bulkReject.disabled = state.loading;
  }
  function openDriver(id) {
    state.drawerId = id; state.drawerData = null; updateUrl(); renderDrawerLoading();
    api.get(`/api/admin/drivers/${encodeURIComponent(id)}`).then((data) => {
      if (state.disposed || state.drawerId !== id) return;
      state.drawerData = data; renderDrawer();
    }).catch((error) => { if (!state.disposed && state.drawerId === id) { renderDrawerError(error); } });
  }
  function renderTable() {
    body.replaceChildren();
    if (!state.rows.length) { renderEmpty(); return; }
    for (const driver of state.rows) {
      const row = document.createElement('tr');
      const selectCell = document.createElement('td');
      const checkbox = document.createElement('input'); checkbox.type = 'checkbox'; checkbox.className = 'driver-select'; checkbox.checked = state.selected.has(driver.user_id);
      checkbox.setAttribute('aria-label', `Select ${driver.full_name}`);
      checkbox.disabled = state.segment !== 'pending' && state.segment !== 'rejected';
      checkbox.addEventListener('change', () => { checkbox.checked ? state.selected.add(driver.user_id) : state.selected.delete(driver.user_id); updateBulkBar(); });
      selectCell.append(checkbox);
      const who = document.createElement('td'); who.className = 'driver-person-cell';
      const open = el('button', 'driver-name-button', driver.full_name); open.type = 'button'; open.addEventListener('click', () => openDriver(driver.user_id));
      who.append(open, el('span', 'driver-contact', [driver.email, driver.phone].filter(Boolean).join(' · ') || 'No contact information'));
      const status = document.createElement('td'); status.append(badge(driver.status));
      const vehicle = document.createElement('td');
      if (driver.vehicle) vehicle.append(el('strong', 'vehicle-type', driver.vehicle.type.replaceAll('_', ' ')), el('span', 'driver-contact', driver.vehicle.registration_number));
      else vehicle.textContent = 'No vehicle';
      const registered = el('td', 'driver-date', date(driver.created_at));
      const lastLogin = el('td', 'driver-date', date(driver.last_login_at));
      const account = document.createElement('td'); account.append(el('span', `account-state ${driver.account_active ? 'is-active' : 'is-blocked'}`, driver.account_active ? 'Active' : 'Blocked'));
      const menu = document.createElement('td'); menu.className = 'driver-actions-cell';
      const action = (label, fn, klass = 'button button-quiet button-small') => { const btn = el('button', klass, label); btn.type = 'button'; btn.addEventListener('click', fn); menu.append(btn); };
      if (driver.status === 'pending') {
        action('Verify', () => mutateDriver(driver, 'verify'));
        action('Reject', () => rejectOne(driver));
      } else if (driver.status === 'rejected') action('Verify', () => mutateDriver(driver, 'verify'));
      if (driver.status !== 'pending' && driver.status !== 'rejected') {
        action(driver.account_active ? 'Block' : 'Unblock', () => changeAccess(driver), 'button button-secondary button-small');
      }
      row.append(selectCell, who, status, vehicle, registered, lastLogin, account, menu); body.append(row);
    }
    renderPagination(); updateBulkBar();
  }
  function renderPagination() {
    pagination.replaceChildren();
    const start = state.total ? (state.page - 1) * state.pageSize + 1 : 0;
    const end = Math.min(state.page * state.pageSize, state.total);
    pagination.append(el('span', 'driver-result-count', `Showing ${start}–${end} of ${state.total}`));
    const controls = el('div', 'driver-page-controls');
    const previous = el('button', 'button button-secondary button-small', 'Previous'); previous.type = 'button'; previous.disabled = state.page <= 1 || state.loading;
    previous.addEventListener('click', () => { state.page -= 1; load(); });
    const next = el('button', 'button button-secondary button-small', 'Next'); next.type = 'button'; next.disabled = state.page * state.pageSize >= state.total || state.loading;
    next.addEventListener('click', () => { state.page += 1; load(); });
    controls.append(previous, el('span', 'driver-page-number', `Page ${state.page}`), next); pagination.append(controls);
  }
  function renderDrawerLoading() {
    drawerLayer.hidden = false; drawerLayer.replaceChildren();
    const backdrop = el('button', 'drawer-backdrop'); backdrop.type = 'button'; backdrop.setAttribute('aria-label', 'Close driver details'); backdrop.addEventListener('click', closeDrawer);
    const drawer = el('aside', 'detail-drawer'); drawer.setAttribute('role', 'dialog'); drawer.setAttribute('aria-modal', 'true'); drawer.setAttribute('aria-label', 'Driver details');
    const header = el('div', 'drawer-header'); header.append(el('h2', '', 'Driver details'));
    const close = el('button', 'drawer-close', 'Close'); close.type = 'button'; close.addEventListener('click', closeDrawer); header.append(close);
    drawer.append(header, el('div', 'drawer-loading', 'Loading driver record…')); drawerLayer.append(backdrop, drawer);
  }
  function detailBlock(title, content) { const block = el('section', 'drawer-section'); block.append(el('h3', '', title)); block.append(content); return block; }
  function renderDrawerError(error) {
    renderDrawerLoading(); const drawer = drawerLayer.querySelector('.detail-drawer');
    drawer.append(el('div', 'page-message', error.message || 'Could not load driver details.'));
    const retry = el('button', 'button button-secondary', 'Try again'); retry.type = 'button'; retry.addEventListener('click', () => openDriver(state.drawerId)); drawer.append(retry);
  }
  function renderDrawer() {
    const data = state.drawerData; if (!data) return;
    renderDrawerLoading(); const drawer = drawerLayer.querySelector('.detail-drawer'); drawer.replaceChildren();
    const header = el('div', 'drawer-header');
    const heading = document.createElement('div'); heading.append(el('h2', '', data.full_name), el('p', 'drawer-subtitle', 'Driver profile'));
    const close = el('button', 'drawer-close', 'Close'); close.type = 'button'; close.addEventListener('click', closeDrawer); header.append(heading, close); drawer.append(header);
    const stateRow = el('div', 'driver-detail-state'); stateRow.append(badge(data.status), el('span', `account-state ${data.account_active ? 'is-active' : 'is-blocked'}`, data.account_active ? 'Account active' : 'Account blocked')); drawer.append(stateRow);
    const identity = el('div', 'driver-identity-list');
    [['Email', data.email || '—'], ['Phone', data.phone || '—'], ['Registered', date(data.created_at)], ['Last login', date(data.last_login_at)]].forEach(([label, value]) => { const item = el('div', 'driver-detail-field'); item.append(el('span', '', label), el('strong', '', value)); identity.append(item); });
    drawer.append(detailBlock('Identity', identity));
    const vehicle = el('div', 'driver-detail-field-list');
    if (data.vehicle) {
      [['Vehicle type', data.vehicle.type.replaceAll('_', ' ')], ['Registration', data.vehicle.registration_number], ['Capacity', `${Number(data.vehicle.max_weight_kg).toLocaleString()} kg · ${Number(data.vehicle.max_volume_m3).toLocaleString()} m³`]].forEach(([label, value]) => { const item = el('div', 'driver-detail-field'); item.append(el('span', '', label), el('strong', '', value)); vehicle.append(item); });
    } else vehicle.append(el('p', 'driver-muted', 'No vehicle is assigned to this driver.'));
    drawer.append(detailBlock('Vehicle', vehicle));
    const stats = el('div', 'driver-stat-grid');
    [['Completed deliveries', data.stats.completed_deliveries], ['Failed stops', data.stats.failed_stops]].forEach(([label, value]) => { const card = el('div', 'driver-stat'); card.append(el('span', '', label), el('strong', '', Number(value).toLocaleString())); stats.append(card); });
    drawer.append(detailBlock('Delivery record', stats));
    const routeWrap = el('div', 'driver-route-list');
    if (data.active_route) {
      const active = el('div', 'driver-route-card active-route'); active.append(el('strong', '', `Current route · ${data.active_route.status.replaceAll('_', ' ')}`), el('span', '', `${data.active_route.stops_done} of ${data.active_route.stops_total} stops completed`), el('span', 'driver-muted', data.active_route.started_at ? `Started ${date(data.active_route.started_at)}` : 'Not started'));
      routeWrap.append(active);
    } else routeWrap.append(el('p', 'driver-muted', 'No active route'));
    if (data.recent_routes.length) {
      data.recent_routes.forEach((route) => { const item = el('div', 'driver-route-row'); item.append(el('strong', '', route.status.replaceAll('_', ' ')), el('span', '', date(route.created_at)), el('span', '', `${route.stops_done}/${route.stops_total} stops`)); routeWrap.append(item); });
    } else routeWrap.append(el('p', 'driver-muted', 'No completed or cancelled routes recorded.'));
    drawer.append(detailBlock('Routes', routeWrap));
    const footer = el('div', 'drawer-actions');
    if (data.status === 'pending') { const verify = el('button', 'button button-primary', 'Verify driver'); verify.type = 'button'; verify.addEventListener('click', () => mutateDriver(data, 'verify')); const reject = el('button', 'button button-secondary', 'Reject application'); reject.type = 'button'; reject.addEventListener('click', () => rejectOne(data)); footer.append(verify, reject); }
    else if (data.status === 'rejected') { const verify = el('button', 'button button-primary', 'Verify driver'); verify.type = 'button'; verify.addEventListener('click', () => mutateDriver(data, 'verify')); footer.append(verify); }
    if (data.status !== 'pending' && data.status !== 'rejected') { const access = el('button', 'button button-secondary', data.account_active ? 'Block account' : 'Unblock account'); access.type = 'button'; access.addEventListener('click', () => changeAccess(data)); footer.append(access); }
    const openUser = el('a', 'text-link', 'Open user record'); openUser.href = `/admin/users?id=${encodeURIComponent(data.user_id)}`; footer.append(openUser);
    drawer.append(footer);
  }
  function closeDrawer() {
    state.drawerId = null; state.drawerData = null; drawerLayer.hidden = true; drawerLayer.replaceChildren(); updateUrl();
  }
  async function refreshOpenDrawer() { const id = state.drawerId; if (id) openDriver(id); }
  async function load() {
    const seq = ++state.requestSeq; state.loading = true; renderLoading(); updateBulkBar();
    updateUrl();
    const params = new URLSearchParams({ segment: state.segment, q: search.value.trim(), sort: state.sort, dir: state.dir, page: String(state.page), page_size: String(state.pageSize) });
    try {
      const data = await api.get(`/api/admin/drivers?${params}`);
      if (state.disposed || seq !== state.requestSeq) return;
      state.rows = data.items; state.total = data.total; state.counts = data.counts; state.page = data.page; state.pageSize = data.page_size;
      refreshTabs(); renderTable();
      if (state.initialDriverId) { const id = state.initialDriverId; state.initialDriverId = null; openDriver(id); }
    } catch (error) {
      if (state.disposed || seq !== state.requestSeq) return;
      body.replaceChildren(); const row = document.createElement('tr'); const cell = document.createElement('td'); cell.colSpan = 8;
      const message = el('div', 'page-message'); message.setAttribute('role', 'alert');
      const copy = el('div', 'message-content'); copy.append(el('strong', '', 'Drivers could not be loaded'), el('p', '', error.message || 'Try again in a moment.'));
      const retry = el('button', 'button button-secondary', 'Retry'); retry.type = 'button'; retry.addEventListener('click', load); message.append(copy, retry); cell.append(message); row.append(cell); body.append(row);
    } finally { if (seq === state.requestSeq) { state.loading = false; updateBulkBar(); renderPagination(); } }
  }
  async function mutateDriver(driver, action) {
    try {
      await api.post(`/api/admin/drivers/${encodeURIComponent(driver.user_id)}/${action}`, {});
      onToast(action === 'verify' ? `${driver.full_name} verified and set to offline.` : `${driver.full_name} rejected.`);
      state.selected.delete(driver.user_id); await load(); await refreshOpenDrawer();
    } catch (error) { onToast(error.message || 'The driver action could not be completed.', 'error'); }
  }
  async function rejectOne(driver) {
    const reason = await reasonDialog(); if (reason === null) return;
    try {
      await api.post(`/api/admin/drivers/${encodeURIComponent(driver.user_id)}/reject`, { reason: reason || null });
      onToast(`${driver.full_name} rejected.`); state.selected.delete(driver.user_id); await load(); await refreshOpenDrawer();
    } catch (error) { onToast(error.message || 'The driver could not be rejected.', 'error'); }
  }
  async function changeAccess(driver) {
    const block = driver.account_active;
    const ok = await confirmDialog(block ? `Block ${driver.full_name}? This immediately prevents the account from signing in.` : `Unblock ${driver.full_name} and restore account access?`);
    if (!ok) return;
    try {
      await api.post(`/api/admin/users/${encodeURIComponent(driver.user_id)}/${block ? 'deactivate' : 'reactivate'}`, {});
      onToast(block ? `${driver.full_name} blocked.` : `${driver.full_name} unblocked.`); await load(); await refreshOpenDrawer();
    } catch (error) { onToast(error.message || 'Account access could not be changed.', 'error'); }
  }
  async function bulkAction(action) {
    const reason = action === 'reject' ? await reasonDialog() : '';
    if (action === 'reject' && reason === null) return;
    const ids = [...state.selected]; if (!ids.length) return;
    try {
      const result = await api.post('/api/admin/drivers/bulk', { action, user_ids: ids, ...(action === 'reject' && reason ? { reason } : {}) });
      const passed = result.results.filter((item) => item.ok).length;
      const failed = result.results.length - passed;
      onToast(failed ? `${passed} ${action === 'verify' ? 'verified' : 'rejected'}, ${failed} could not be processed.` : `${passed} drivers ${action === 'verify' ? 'verified' : 'rejected'}.`, failed ? 'error' : 'success');
      state.selected.clear(); await load();
    } catch (error) { onToast(error.message || 'The selected drivers could not be processed.', 'error'); }
  }
  function reasonDialog() { return promptDialog('Reject driver application', 'Rejection reason (optional)', 'Enter a reason to include in the audit record and email.', 'Reject'); }
  function confirmDialog(message) {
    return new Promise((resolve) => {
      const dialog = document.createElement('dialog'); dialog.className = 'admin-dialog';
      const form = document.createElement('form'); form.method = 'dialog';
      form.append(el('h2', '', 'Confirm account access change'), el('p', '', message));
      const actions = el('div', 'dialog-actions'); const cancel = el('button', 'button button-secondary', 'Cancel'); cancel.value = 'cancel';
      const confirm = el('button', 'button button-primary', 'Continue'); confirm.value = 'confirm'; actions.append(cancel, confirm); form.append(actions); dialog.append(form); document.body.append(dialog);
      dialog.addEventListener('close', () => { const yes = dialog.returnValue === 'confirm'; dialog.remove(); resolve(yes); }, { once: true }); dialog.showModal();
    });
  }
  function promptDialog(title, labelText, hint, submitText) {
    return new Promise((resolve) => {
      const dialog = document.createElement('dialog'); dialog.className = 'admin-dialog';
      const form = document.createElement('form'); form.method = 'dialog';
      const label = document.createElement('label'); label.append(el('span', '', labelText));
      const input = document.createElement('textarea'); input.maxLength = 200; input.rows = 3; label.append(input, el('small', '', hint));
      const actions = el('div', 'dialog-actions'); const cancel = el('button', 'button button-secondary', 'Cancel'); cancel.value = 'cancel';
      const submit = el('button', 'button button-primary', submitText); submit.value = 'submit'; actions.append(cancel, submit);
      form.append(el('h2', '', title), label, actions); dialog.append(form); document.body.append(dialog);
      dialog.addEventListener('close', () => { const value = dialog.returnValue === 'submit' ? input.value.trim() : null; dialog.remove(); resolve(value); }, { once: true });
      dialog.showModal(); input.focus();
    });
  }

  sort.addEventListener('change', () => { state.sort = sort.value; state.page = 1; load(); });
  direction.addEventListener('click', () => { state.dir = state.dir === 'asc' ? 'desc' : 'asc'; updateDirection(); state.page = 1; load(); });
  function updateDirection() { direction.textContent = state.dir === 'asc' ? 'Oldest first ↑' : 'Newest first ↓'; }
  refresh.addEventListener('click', load);
  search.addEventListener('input', () => { window.clearTimeout(searchTimer); searchTimer = window.setTimeout(() => { state.page = 1; state.selected.clear(); load(); }, 250); });
  bulkVerify.addEventListener('click', () => bulkAction('verify'));
  bulkReject.addEventListener('click', () => bulkAction('reject'));
  clearSelection.addEventListener('click', () => { state.selected.clear(); renderTable(); });
  updateDirection(); refreshTabs(); load();
  return { element: root, refresh: load, destroy() { state.disposed = true; window.clearTimeout(searchTimer); closeDrawer(); } };
}
