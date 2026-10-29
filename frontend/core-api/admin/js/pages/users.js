const SEGMENTS = [['all', 'All'], ['active', 'Active'], ['inactive', 'Inactive'], ['locked', 'Locked']];
const ROLES = ['customer', 'merchant', 'dispatcher', 'driver', 'fleet_manager', 'admin'];
const ROLE_LABELS = { customer: 'Customer', merchant: 'Merchant', dispatcher: 'Dispatcher', driver: 'Driver', fleet_manager: 'Fleet manager', admin: 'Administrator' };
const MANAGED_ROLES = ['dispatcher', 'fleet_manager', 'admin'];
const SORTS = [['created_at', 'Created'], ['full_name', 'Name'], ['last_login_at', 'Last login']];

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}
function localDate(value, withTime = false) {
  if (!value) return 'Never';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return '—';
  return new Intl.DateTimeFormat(undefined, withTime
    ? { dateStyle: 'medium', timeStyle: 'short' }
    : { dateStyle: 'medium' }).format(parsed);
}
function statusOf(user) {
  if (user.is_locked) return ['Locked', 'user-state-locked'];
  if (!user.is_active) return ['Inactive', 'user-state-inactive'];
  if (user.invited) return ['Invited', 'user-state-invited'];
  return ['Active', 'user-state-active'];
}
function makePageUrl(userId, params) {
  if (userId) params.set('id', userId);
  const query = params.toString();
  return `${window.location.pathname}${query ? `?${query}` : ''}`;
}

export function createUsersPage({ api, onToast, route }) {
  const root = el('div', 'users-page');
  const intro = el('div', 'page-intro');
  const introCopy = el('div');
  introCopy.append(el('h2', '', 'Accounts and access'), el('p', '', 'Find accounts, review their access, and invite platform staff.'));
  const inviteButton = el('button', 'button button-primary', 'Invite staff'); inviteButton.type = 'button';
  intro.append(introCopy, inviteButton);

  const state = {
    status: SEGMENTS.some(([key]) => key === route.query.get('status')) ? route.query.get('status') : 'all',
    role: ROLES.includes(route.query.get('role')) ? route.query.get('role') : '',
    q: (route.query.get('q') || '').slice(0, 100), sort: SORTS.some(([key]) => key === route.query.get('sort')) ? route.query.get('sort') : 'created_at',
    dir: ['asc', 'desc'].includes(route.query.get('dir')) ? route.query.get('dir') : 'desc',
    page: Math.max(1, Number.isSafeInteger(Number(route.query.get('page'))) ? Number(route.query.get('page')) : 1),
    pageSize: 25, total: 0, counts: {}, rows: [], selectedUserId: route.itemId || null,
    detail: null, listSequence: 0, detailSequence: 0, listController: null, detailController: null,
    loading: false, disposed: false, warehouses: null, warehouseRequest: null
  };

  const tabs = el('div', 'user-tabs'); tabs.setAttribute('role', 'tablist'); tabs.setAttribute('aria-label', 'Account status');
  const toolbar = el('div', 'user-toolbar');
  const search = document.createElement('input'); search.type = 'search'; search.maxLength = 100; search.placeholder = 'Search name, email or phone'; search.setAttribute('aria-label', 'Search users'); search.value = state.q;
  const roleSelect = document.createElement('select'); roleSelect.setAttribute('aria-label', 'Filter by role');
  [['', 'Any role'], ...ROLES.map((role) => [role, ROLE_LABELS[role]])].forEach(([value, label]) => { const option = el('option', '', label); option.value = value; roleSelect.append(option); });
  roleSelect.value = ROLES.includes(state.role) ? state.role : '';
  const sortSelect = document.createElement('select'); sortSelect.setAttribute('aria-label', 'Sort users');
  SORTS.forEach(([value, label]) => { const option = el('option', '', label); option.value = value; sortSelect.append(option); });
  sortSelect.value = SORTS.some(([key]) => key === state.sort) ? state.sort : 'created_at';
  if (sortSelect.value !== state.sort) state.sort = sortSelect.value;
  const direction = el('button', 'button button-secondary button-small'); direction.type = 'button';
  const refresh = el('button', 'button button-secondary', 'Refresh'); refresh.type = 'button';
  toolbar.append(search, roleSelect, sortSelect, direction, refresh);

  const panel = el('section', 'panel user-table-panel');
  const panelTitle = el('div', 'section-label'); panelTitle.append(el('h2', '', 'Users'), el('p', '', 'Access state and role membership'));
  const scroll = el('div', 'user-table-scroll');
  const table = el('table', 'user-table');
  const head = document.createElement('thead'); const headRow = document.createElement('tr');
  ['User', 'Roles', 'Access', 'Last login', 'Created', ''].forEach((label) => { const th = el('th', '', label); if (!label) th.setAttribute('aria-label', 'Actions'); headRow.append(th); });
  head.append(headRow);
  const tbody = document.createElement('tbody'); table.append(head, tbody); scroll.append(table);
  const pagination = el('div', 'user-pagination');
  panel.append(panelTitle, scroll, pagination);
  const drawerLayer = el('div', 'drawer-layer'); drawerLayer.hidden = true;
  root.append(intro, tabs, toolbar, panel, drawerLayer);
  let searchTimer;

  function updateUrl() {
    const params = new URLSearchParams();
    params.set('status', state.status);
    if (state.role) params.set('role', state.role);
    if (state.q.trim()) params.set('q', state.q.trim());
    if (state.sort !== 'created_at') params.set('sort', state.sort);
    if (state.dir !== 'desc') params.set('dir', state.dir);
    if (state.page > 1) params.set('page', String(state.page));
    const target = makePageUrl(state.selectedUserId, params);
    if (`${window.location.pathname}${window.location.search}` !== target) window.history.replaceState(null, '', target);
  }
  function updateDirection() { direction.textContent = state.dir === 'asc' ? 'Oldest first ↑' : 'Newest first ↓'; }
  function refreshTabs() {
    tabs.replaceChildren();
    for (const [key, label] of SEGMENTS) {
      const button = el('button', `user-tab${state.status === key ? ' is-active' : ''}`); button.type = 'button'; button.setAttribute('role', 'tab'); button.setAttribute('aria-selected', String(state.status === key));
      button.append(document.createTextNode(label), el('span', 'user-tab-count', state.counts[key] ?? '—'));
      button.addEventListener('click', () => { if (state.status === key) return; state.status = key; state.page = 1; updateUrl(); load(); });
      tabs.append(button);
    }
  }
  function renderLoading() {
    tbody.replaceChildren(); const row = document.createElement('tr'); const cell = el('td', 'user-table-message', 'Loading accounts…'); cell.colSpan = 6; row.append(cell); tbody.append(row);
  }
  function renderEmpty() {
    tbody.replaceChildren(); const row = document.createElement('tr'); const cell = document.createElement('td'); cell.colSpan = 6;
    const empty = el('div', 'user-empty');
    empty.append(el('strong', '', state.q.trim() || state.role || state.status !== 'all' ? 'No users match these filters.' : 'No user accounts found.'), el('span', '', 'Adjust the filters or clear them to see more accounts.'));
    const reset = el('button', 'text-link', 'Reset filters'); reset.type = 'button'; reset.addEventListener('click', resetFilters); empty.append(reset);
    cell.append(empty); row.append(cell); tbody.append(row);
  }
  function renderPagination() {
    pagination.replaceChildren();
    const start = state.total ? (state.page - 1) * state.pageSize + 1 : 0; const end = Math.min(state.page * state.pageSize, state.total);
    pagination.append(el('span', 'user-result-count', `Showing ${start}–${end} of ${state.total}`));
    const controls = el('div', 'user-page-controls');
    const previous = el('button', 'button button-secondary button-small', 'Previous'); previous.type = 'button'; previous.disabled = state.page <= 1 || state.loading;
    previous.addEventListener('click', () => { state.page -= 1; updateUrl(); load(); });
    const next = el('button', 'button button-secondary button-small', 'Next'); next.type = 'button'; next.disabled = state.page * state.pageSize >= state.total || state.loading;
    next.addEventListener('click', () => { state.page += 1; updateUrl(); load(); });
    controls.append(previous, el('span', 'user-page-number', `Page ${state.page}`), next); pagination.append(controls);
  }
  function renderRows() {
    tbody.replaceChildren();
    if (!state.rows.length) { renderEmpty(); return; }
    state.rows.forEach((user) => {
      const row = document.createElement('tr');
      const userCell = document.createElement('td'); userCell.className = 'user-person-cell';
      const open = el('button', 'user-name-button', user.full_name); open.type = 'button'; open.addEventListener('click', () => openUser(user.id));
      userCell.append(open, el('span', 'user-contact', [user.email, user.phone].filter(Boolean).join(' · ') || 'No contact information'));
      const rolesCell = el('td', 'user-roles-cell');
      if (user.roles.length) user.roles.forEach((role) => rolesCell.append(el('span', 'role-chip', ROLE_LABELS[role] || role)));
      else rolesCell.append(el('span', 'user-muted', 'No roles'));
      const [statusLabel, statusClass] = statusOf(user); const statusCell = document.createElement('td'); statusCell.append(el('span', `user-state ${statusClass}`, statusLabel));
      if (user.is_locked && user.locked_until) { const until = el('span', 'user-lock-until', `Until ${localDate(user.locked_until, true)}`); statusCell.append(until); }
      const last = el('td', 'user-date', localDate(user.last_login_at));
      const created = el('td', 'user-date', localDate(user.created_at));
      const actions = el('td', 'user-row-actions'); const menu = el('button', 'button button-quiet button-small', 'Open'); menu.type = 'button'; menu.addEventListener('click', () => openUser(user.id)); actions.append(menu);
      row.append(userCell, rolesCell, statusCell, last, created, actions); tbody.append(row);
    });
  }
  function renderListError(error) {
    tbody.replaceChildren(); const row = document.createElement('tr'); const cell = document.createElement('td'); cell.colSpan = 6;
    const message = el('div', 'page-message'); message.setAttribute('role', 'alert'); const copy = el('div', 'message-content');
    copy.append(el('strong', '', 'Users could not be loaded'), el('p', '', error.message || 'Try again shortly.'));
    const retry = el('button', 'button button-secondary', 'Retry'); retry.type = 'button'; retry.addEventListener('click', load); message.append(copy, retry); cell.append(message); row.append(cell); tbody.append(row);
  }
  async function load() {
    if (state.disposed) return;
    state.listController?.abort(); state.listController = new AbortController(); const seq = ++state.listSequence;
    state.loading = true; renderLoading();
    const params = new URLSearchParams({ status: state.status, sort: state.sort, dir: state.dir, page: String(state.page), page_size: String(state.pageSize) });
    if (state.q.trim()) params.set('q', state.q.trim()); if (state.role) params.set('role', state.role);
    try {
      const data = await api.get(`/api/admin/users?${params}`, { signal: state.listController.signal });
      if (state.disposed || seq !== state.listSequence) return;
      state.rows = data.items; state.total = data.total; state.page = data.page; state.pageSize = data.page_size; state.counts = data.counts;
      refreshTabs(); renderRows(); renderPagination();
      if (state.selectedUserId && !state.detail) loadDetail(state.selectedUserId);
    } catch (error) {
      if (state.disposed || seq !== state.listSequence) return;
      renderListError(error);
    } finally { if (seq === state.listSequence) { state.loading = false; renderPagination(); } }
  }
  function openUser(userId) {
    if (state.selectedUserId !== userId) { state.selectedUserId = userId; state.detail = null; updateUrl(); }
    renderDrawerLoading(); loadDetail(userId);
  }
  async function loadDetail(userId) {
    state.detailController?.abort(); state.detailController = new AbortController(); const seq = ++state.detailSequence;
    try {
      const detail = await api.get(`/api/admin/users/${encodeURIComponent(userId)}`, { signal: state.detailController.signal });
      if (state.disposed || seq !== state.detailSequence || state.selectedUserId !== userId) return;
      state.detail = detail; renderDrawer();
    } catch (error) {
      if (state.disposed || seq !== state.detailSequence) return;
      renderDrawerError(error);
    }
  }
  function renderDrawerLoading() {
    drawerLayer.hidden = false; drawerLayer.replaceChildren();
    const backdrop = el('button', 'drawer-backdrop'); backdrop.type = 'button'; backdrop.setAttribute('aria-label', 'Close user details'); backdrop.addEventListener('click', closeDrawer);
    const drawer = el('aside', 'detail-drawer'); drawer.setAttribute('role', 'dialog'); drawer.setAttribute('aria-modal', 'true'); drawer.setAttribute('aria-label', 'User details');
    const header = el('div', 'drawer-header'); header.append(el('h2', '', 'User details'));
      const close = el('button', 'drawer-close', 'Close'); close.type = 'button'; close.addEventListener('click', closeDrawer);
    header.append(close); drawer.append(header, el('div', 'drawer-loading', 'Loading account…')); drawerLayer.append(backdrop, drawer);
  }
  function drawerSection(title, content) { const section = el('section', 'drawer-section'); section.append(el('h3', '', title), content); return section; }
  function renderDrawerError(error) {
    renderDrawerLoading(); const drawer = drawerLayer.querySelector('.detail-drawer');
    const message = el('div', 'page-message'); message.setAttribute('role', 'alert'); message.textContent = error.message || 'Could not load this account.';
    drawer.append(message); const retry = el('button', 'button button-secondary', 'Retry'); retry.type = 'button'; retry.addEventListener('click', () => loadDetail(state.selectedUserId)); drawer.append(retry);
  }
  function renderDrawer() {
    const user = state.detail; if (!user) return;
    renderDrawerLoading(); const drawer = drawerLayer.querySelector('.detail-drawer'); drawer.replaceChildren();
    const header = el('div', 'drawer-header'); const title = document.createElement('div');
    title.append(el('h2', '', user.full_name), el('p', 'drawer-subtitle', 'Account profile'));
    const close = el('button', 'drawer-close', 'Close'); close.type = 'button'; close.addEventListener('click', closeDrawer); header.append(title, close); drawer.append(header); close.focus();
    const [statusLabel, statusClass] = statusOf(user); const stateRow = el('div', 'user-detail-state'); stateRow.append(el('span', `user-state ${statusClass}`, statusLabel));
    if (user.driver_status) stateRow.append(el('span', `driver-status status-${user.driver_status}`, `Driver · ${user.driver_status.replaceAll('_', ' ')}`));
    drawer.append(stateRow);

    const profile = el('div', 'user-profile-grid');
    [['Email', user.email || '—'], ['Phone', user.phone || '—'], ['Created', localDate(user.created_at, true)], ['Last login', localDate(user.last_login_at, true)]].forEach(([label, value]) => {
      const field = el('div', 'user-detail-field'); field.append(el('span', '', label), el('strong', '', value)); profile.append(field);
    });
    drawer.append(drawerSection('Profile', profile));

    const rolesSection = el('div', 'user-role-management'); const roleList = el('div', 'user-role-list');
    if (user.roles.length) user.roles.forEach((role) => {
      const item = el('div', 'user-role-item'); const info = el('div');
      info.append(el('strong', '', ROLE_LABELS[role.role] || role.role), el('span', '', `Granted ${localDate(role.granted_at)}${role.granted_by_name ? ` by ${role.granted_by_name}` : ''}`)); item.append(info);
      if (MANAGED_ROLES.includes(role.role)) { const remove = el('button', 'text-link danger-link', 'Remove'); remove.type = 'button'; remove.addEventListener('click', () => changeRole(user, role.role, false)); item.append(remove); }
      roleList.append(item);
    });
    else roleList.append(el('p', 'user-muted', 'No roles assigned.'));
    const held = new Set(user.roles.map((role) => role.role)); const availableRoles = MANAGED_ROLES.filter((role) => !held.has(role));
    if (availableRoles.length) {
      const addRow = el('div', 'user-add-role'); const select = document.createElement('select'); select.setAttribute('aria-label', 'Role to add');
      availableRoles.forEach((role) => { const option = el('option', '', ROLE_LABELS[role]); option.value = role; select.append(option); });
      const grant = el('button', 'button button-secondary button-small', 'Add role'); grant.type = 'button'; grant.addEventListener('click', () => changeRole(user, select.value, true)); addRow.append(select, grant); roleList.append(addRow);
    }
    rolesSection.append(roleList); drawer.append(drawerSection('Roles', rolesSection));

    const access = el('div', 'user-access-panel');
    const accessStats = el('div', 'user-access-stats');
    [['Locked until', user.is_locked ? localDate(user.locked_until, true) : 'Not locked'], ['Active sessions', Number(user.active_sessions).toLocaleString()]].forEach(([label, value]) => { const field = el('div', 'user-detail-field'); field.append(el('span', '', label), el('strong', '', value)); accessStats.append(field); });
    access.append(accessStats);
    const accessActions = el('div', 'user-action-grid');
    addAction(accessActions, user.is_active ? 'Deactivate account' : 'Reactivate account', user.is_active ? 'button button-secondary button-small' : 'button button-primary button-small', () => accessAction(user, user.is_active ? 'deactivate' : 'reactivate'));
    if (user.is_locked) addAction(accessActions, 'Unlock account', 'button button-secondary button-small', () => accessAction(user, 'unlock'));
    if (user.active_sessions > 0) addAction(accessActions, 'Sign out everywhere', 'button button-secondary button-small', () => accessAction(user, 'revoke-sessions'));
    if (user.invited) addAction(accessActions, 'Resend invite', 'button button-secondary button-small', () => accessAction(user, 'resend-invite'));
    else if (user.is_active) addAction(accessActions, 'Send password reset', 'button button-secondary button-small', () => accessAction(user, 'send-reset'));
    access.append(accessActions); drawer.append(drawerSection('Access', access));

    const membership = el('div', 'user-membership-lists');
    const warehouses = el('div', 'user-membership-group'); warehouses.append(el('h4', '', 'Warehouses'));
    if (user.warehouses.length) user.warehouses.forEach((warehouse) => { const link = el('a', 'user-membership-link', `${warehouse.code} · ${warehouse.name}`); link.href = `/admin/warehouses?id=${encodeURIComponent(warehouse.id)}`; warehouses.append(link); });
    else warehouses.append(el('p', 'user-muted', 'No warehouse access assigned.'));
    const merchants = el('div', 'user-membership-group'); merchants.append(el('h4', '', 'Merchants'));
    if (user.merchants.length) user.merchants.forEach((merchant) => { const link = el('a', 'user-membership-link', merchant.name); link.href = `/admin/merchants?id=${encodeURIComponent(merchant.id)}`; merchants.append(link); });
    else merchants.append(el('p', 'user-muted', 'No merchant memberships.'));
    membership.append(warehouses, merchants); drawer.append(drawerSection('Belongs to', membership));
    if (user.driver_status) {
      const driverLink = el('a', 'user-driver-link', `Open driver record · ${user.driver_status.replaceAll('_', ' ')}`); driverLink.href = `/admin/drivers?id=${encodeURIComponent(user.id)}`;
      drawer.append(drawerSection('Driver profile', driverLink));
    }
  }
  function addAction(parent, label, className, handler) { const button = el('button', className, label); button.type = 'button'; button.addEventListener('click', handler); parent.append(button); }
  async function closeDrawer() {
    state.selectedUserId = null; state.detail = null; state.detailController?.abort();
    drawerLayer.hidden = true; drawerLayer.replaceChildren(); updateUrl();
  }
  async function accessAction(user, action) {
    const copy = {
      deactivate: `Deactivate ${user.full_name}? They will lose access immediately.`,
      reactivate: `Reactivate ${user.full_name} and restore account access?`,
      unlock: `Unlock ${user.full_name} and clear the current sign-in lock?`,
      'revoke-sessions': `Sign ${user.full_name} out of all active sessions?`,
      'send-reset': `Send a password reset email to ${user.email || 'this user'}?`,
      'resend-invite': `Send a new invitation to ${user.email || 'this user'}?`
    };
    if (!await confirmAction(copy[action])) return;
    try {
      const result = await api.post(`/api/admin/users/${encodeURIComponent(user.id)}/${action}`, {});
      if (action === 'resend-invite') onToast(result.invite_sent ? `Invitation sent to ${user.email}.` : 'The invite was renewed, but email could not be sent.');
      else if (action === 'send-reset') onToast(result.sent ? `Password reset sent to ${user.email}.` : 'The reset link was created, but email could not be sent.', result.sent ? 'success' : 'error');
      else onToast(({ deactivate: 'Account deactivated.', reactivate: 'Account reactivated.', unlock: 'Account unlocked.', 'revoke-sessions': 'All active sessions revoked.' })[action]);
      await refreshCurrentUser();
    } catch (error) { onToast(error.message || 'The account action could not be completed.', 'error'); }
  }
  async function changeRole(user, role, grant) {
    let currentPassword;
    if (role === 'admin') {
      currentPassword = await passwordDialog(grant ? 'Grant administrator role' : 'Revoke administrator role', 'Enter your password to confirm this change.');
      if (currentPassword === null) return;
    } else if (!await confirmAction(`${grant ? 'Add' : 'Remove'} the ${ROLE_LABELS[role]} role ${grant ? 'to' : 'from'} ${user.full_name}?`)) return;
    try {
      const body = grant ? { role, ...(currentPassword ? { current_password: currentPassword } : {}) } : (currentPassword ? { current_password: currentPassword } : {});
      await api.post(grant ? `/api/admin/users/${encodeURIComponent(user.id)}/roles` : `/api/admin/users/${encodeURIComponent(user.id)}/roles/${encodeURIComponent(role)}/revoke`, body);
      onToast(`${ROLE_LABELS[role]} role ${grant ? 'added' : 'removed'}.`); await refreshCurrentUser();
    } catch (error) { onToast(error.message || 'The role could not be changed.', 'error'); }
  }
  async function refreshCurrentUser() {
    await load();
    if (state.selectedUserId) await loadDetail(state.selectedUserId);
  }
  function confirmAction(message) {
    return new Promise((resolve) => {
      const dialog = document.createElement('dialog'); dialog.className = 'admin-dialog'; const form = document.createElement('form'); form.method = 'dialog';
      form.append(el('h2', '', 'Confirm account change'), el('p', '', message)); const actions = el('div', 'dialog-actions');
      const cancel = el('button', 'button button-secondary', 'Cancel'); cancel.value = 'cancel'; const confirm = el('button', 'button button-primary', 'Continue'); confirm.value = 'confirm'; actions.append(cancel, confirm); form.append(actions); dialog.append(form); document.body.append(dialog);
      dialog.addEventListener('close', () => { const accepted = dialog.returnValue === 'confirm'; dialog.remove(); resolve(accepted); }, { once: true }); dialog.showModal();
    });
  }
  function passwordDialog(title, hint) {
    return new Promise((resolve) => {
      const dialog = document.createElement('dialog'); dialog.className = 'admin-dialog'; const form = document.createElement('form'); form.method = 'dialog';
      const label = document.createElement('label'); label.append(el('span', '', 'Your current password'));
      const input = document.createElement('input'); input.type = 'password'; input.autocomplete = 'current-password'; input.required = true; label.append(input, el('small', '', hint));
      const actions = el('div', 'dialog-actions'); const cancel = el('button', 'button button-secondary', 'Cancel'); cancel.value = 'cancel'; const submit = el('button', 'button button-primary', 'Confirm'); submit.value = 'submit'; actions.append(cancel, submit);
      form.append(el('h2', '', title), label, actions); dialog.append(form); document.body.append(dialog);
      form.addEventListener('submit', (event) => { event.preventDefault(); if (!input.reportValidity()) return; dialog.close('submit'); });
      dialog.addEventListener('close', () => { const password = dialog.returnValue === 'submit' ? input.value : null; dialog.remove(); resolve(password); }, { once: true });
      dialog.showModal(); input.focus();
    });
  }
  function inviteDialog() {
    const dialog = document.createElement('dialog'); dialog.className = 'admin-dialog invite-dialog';
    const form = document.createElement('form'); form.method = 'dialog';
    const name = field('Full name', 'text', 'full_name'); name.input.maxLength = 200; name.input.required = true; name.input.autocomplete = 'name';
    const email = field('Email', 'email', 'email'); email.input.required = true; email.input.autocomplete = 'email';
    const roleField = document.createElement('label'); roleField.className = 'dialog-field'; roleField.append(el('span', '', 'Role'));
    const roleInput = document.createElement('select'); [['dispatcher','Dispatcher'],['fleet_manager','Fleet manager'],['admin','Administrator']].forEach(([value,label]) => { const option = el('option', '', label); option.value = value; roleInput.append(option); }); roleField.append(roleInput);
    const warehouseField = el('fieldset', 'warehouse-picker'); const legend = document.createElement('legend'); legend.textContent = 'Warehouses'; warehouseField.append(legend, el('p', 'field-hint', 'No warehouse assignment means the staff member has no warehouse access until one is assigned.'));
    const warehouseList = el('div', 'warehouse-checkbox-list'); warehouseField.append(warehouseList);
    const password = field('Your current password', 'password', 'current_password'); password.input.autocomplete = 'current-password'; password.input.required = true; password.wrap.hidden = true;
    const inviteError = el('p', 'dialog-error'); inviteError.setAttribute('role', 'alert'); inviteError.hidden = true;
    const actions = el('div', 'dialog-actions'); const cancel = el('button', 'button button-secondary', 'Cancel'); cancel.value = 'cancel'; const submit = el('button', 'button button-primary', 'Send invite'); submit.value = 'submit'; actions.append(cancel, submit);
    form.append(el('h2', '', 'Invite staff'), el('p', 'dialog-copy', 'The user will receive a link to set their password. Admin role changes require your password.'), name.wrap, email.wrap, roleField, warehouseField, password.wrap, inviteError, actions);
    dialog.append(form); document.body.append(dialog);
    function updateRoleView() {
      const isAdmin = roleInput.value === 'admin'; const needsWarehouses = roleInput.value !== 'admin';
      password.wrap.hidden = !isAdmin; password.input.required = isAdmin;
      warehouseField.hidden = !needsWarehouses;
      warehouseList.replaceChildren();
      if (needsWarehouses) loadWarehouses(warehouseList, (message) => { inviteError.textContent = `${message} You can continue without assigning a warehouse.`; inviteError.hidden = false; submit.disabled = false; });
      else submit.disabled = false;
    }
    roleInput.addEventListener('change', updateRoleView);
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (event.submitter?.value !== 'submit') { dialog.close('cancel'); return; }
      if (!form.reportValidity()) return;
      inviteError.hidden = true; submit.disabled = true;
      const warehouseIds = roleInput.value === 'admin' ? [] : [...warehouseList.querySelectorAll('input:checked')].map((input) => input.value);
      const body = { full_name: name.input.value.trim(), email: email.input.value.trim(), role: roleInput.value };
      if (warehouseIds.length) body.warehouse_ids = warehouseIds;
      if (roleInput.value === 'admin') body.current_password = password.input.value;
      try {
        const result = await api.post('/api/admin/users', body);
        dialog.close('submitted');
        if (result.invite_sent) onToast(`Invite sent to ${result.user.email}.`);
        else onToast('Account created, but the invitation email could not be sent. Use Resend invite.', 'error');
        state.status = 'all'; state.role = ''; state.page = 1; syncFilters(); updateUrl(); await load();
        if (result.user.id) openUser(result.user.id);
      } catch (error) {
        inviteError.textContent = error.message || 'The invitation could not be created.'; inviteError.hidden = false; submit.disabled = false;
      }
    });
    dialog.addEventListener('close', () => dialog.remove(), { once: true });
    updateRoleView(); dialog.showModal(); name.input.focus();
  }
  function field(labelText, type, name) {
    const wrap = document.createElement('label'); wrap.className = 'dialog-field'; wrap.append(el('span', '', labelText));
    const input = document.createElement('input'); input.type = type; input.name = name; wrap.append(input); return { wrap, input };
  }
  async function loadWarehouses(container, onError) {
    if (!state.warehouses && !state.warehouseRequest) {
      state.warehouseRequest = api.get('/api/admin/warehouses?status=active&sort=code&dir=asc&page=1&page_size=100')
        .then((data) => { state.warehouses = data.items; return data.items; })
        .finally(() => { state.warehouseRequest = null; });
    }
    try {
      const warehouses = state.warehouses || await state.warehouseRequest;
      if (!container.isConnected) return;
      container.replaceChildren();
      if (!warehouses.length) { container.append(el('p', 'user-muted', 'No active warehouses available.')); return; }
      warehouses.forEach((warehouse) => {
        const label = document.createElement('label'); label.className = 'warehouse-checkbox'; const input = document.createElement('input'); input.type = 'checkbox'; input.value = warehouse.id;
        label.append(input, el('span', '', `${warehouse.code} · ${warehouse.name}`)); container.append(label);
      });
    } catch (error) { if (container.isConnected) onError(error.message || 'Active warehouses could not be loaded.'); }
  }
  function syncFilters() { search.value = state.q; roleSelect.value = state.role; sortSelect.value = state.sort; updateDirection(); }
  function resetFilters() {
    state.status = 'all'; state.role = ''; state.q = ''; state.sort = 'created_at'; state.dir = 'desc'; state.page = 1; syncFilters(); updateUrl(); load();
  }
  function filtersChanged() { state.status = state.status || 'all'; state.role = roleSelect.value; state.q = search.value; state.sort = sortSelect.value; state.page = 1; updateUrl(); load(); }

  inviteButton.addEventListener('click', inviteDialog);
  search.addEventListener('input', () => { window.clearTimeout(searchTimer); searchTimer = window.setTimeout(filtersChanged, 300); });
  roleSelect.addEventListener('change', filtersChanged); sortSelect.addEventListener('change', filtersChanged);
  direction.addEventListener('click', () => { state.dir = state.dir === 'asc' ? 'desc' : 'asc'; updateDirection(); state.page = 1; updateUrl(); load(); });
  refresh.addEventListener('click', () => { load(); if (state.selectedUserId) loadDetail(state.selectedUserId); });
  updateDirection(); refreshTabs(); updateUrl(); load();
  return { element: root, refresh: load, destroy() { state.disposed = true; window.clearTimeout(searchTimer); state.listController?.abort(); state.detailController?.abort(); drawerLayer.hidden = true; drawerLayer.replaceChildren(); } };
}
