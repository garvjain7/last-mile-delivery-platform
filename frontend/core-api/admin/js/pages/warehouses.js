const STATUSES = [['all', 'All'], ['active', 'Active'], ['inactive', 'Inactive']];
const SORTS = [['code', 'Code'], ['name', 'Name'], ['open_orders', 'Open orders'], ['created_at', 'Created']];
const ORDER_STATUS_LABELS = {
  pending: 'Pending', assigned: 'Assigned', out_for_delivery: 'Out for delivery',
  attempt_failed: 'Failed attempt', delivered: 'Delivered', returned: 'Returned', cancelled: 'Cancelled'
};

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}
function number(value) { return Number(value || 0).toLocaleString(); }
function date(value) {
  if (!value) return '—';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? '—' : new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(parsed);
}
function makeUrl(id, params) {
  if (id) params.set('id', id);
  const query = params.toString();
  return `${window.location.pathname}${query ? `?${query}` : ''}`;
}

export function createWarehousesPage({ api, onToast, route }) {
  const root = el('div', 'warehouses-page');
  const intro = el('div', 'page-intro');
  const introCopy = el('div');
  introCopy.append(el('h2', '', 'Warehouse network'), el('p', '', 'Manage locations, capacity activity, and the staff assigned to each facility.'));
  const addButton = el('button', 'button button-primary', 'Add warehouse'); addButton.type = 'button';
  intro.append(introCopy, addButton);

  const tabs = el('div', 'warehouse-tabs'); tabs.setAttribute('role', 'tablist'); tabs.setAttribute('aria-label', 'Warehouse status');
  const toolbar = el('div', 'warehouse-toolbar');
  const search = document.createElement('input'); search.type = 'search'; search.maxLength = 100; search.placeholder = 'Search code, name, or address'; search.setAttribute('aria-label', 'Search warehouses');
  const sort = document.createElement('select'); sort.setAttribute('aria-label', 'Sort warehouses');
  SORTS.forEach(([value, label]) => { const option = el('option', '', label); option.value = value; sort.append(option); });
  const direction = el('button', 'button button-secondary button-small warehouse-direction'); direction.type = 'button';
  const refresh = el('button', 'button button-secondary', 'Refresh'); refresh.type = 'button';
  toolbar.append(search, sort, direction, refresh);

  const panel = el('section', 'panel warehouse-table-panel');
  const heading = el('div', 'section-label'); heading.append(el('h2', '', 'Warehouse directory'), el('p', '', 'Location, staff, orders, and active routes'));
  const tableScroll = el('div', 'warehouse-table-scroll');
  const table = el('table', 'warehouse-table');
  const thead = document.createElement('thead'); const headRow = document.createElement('tr');
  ['Code', 'Name', 'Address', 'Status', 'Staff', 'Open orders', 'Active routes', ''].forEach((label) => {
    const th = el('th', '', label); if (!label) th.setAttribute('aria-label', 'Actions'); headRow.append(th);
  });
  thead.append(headRow); const tbody = document.createElement('tbody'); table.append(thead, tbody); tableScroll.append(table);
  const pagination = el('div', 'warehouse-pagination'); panel.append(heading, tableScroll, pagination);
  const drawerLayer = el('div', 'drawer-layer'); drawerLayer.hidden = true;
  root.append(intro, tabs, toolbar, panel, drawerLayer);

  const initialQuery = route?.query || new URLSearchParams();
  const state = {
    status: STATUSES.some(([key]) => key === initialQuery.get('status')) ? (initialQuery.get('status') || 'all') : 'all',
    q: (initialQuery.get('q') || '').slice(0, 100),
    sort: SORTS.some(([key]) => key === initialQuery.get('sort')) ? (initialQuery.get('sort') || 'code') : 'code',
    dir: ['asc', 'desc'].includes(initialQuery.get('dir')) ? initialQuery.get('dir') : 'asc',
    page: Math.max(1, Number.isSafeInteger(Number(initialQuery.get('page'))) ? Number(initialQuery.get('page')) : 1),
    pageSize: 25, total: 0, counts: {}, rows: [], selectedId: route?.itemId || null,
    detail: null, sequence: 0, detailSequence: 0, disposed: false, listController: null, detailController: null
  };
  search.value = state.q; sort.value = state.sort;
  let searchTimer;

  function updateUrl() {
    const params = new URLSearchParams();
    params.set('status', state.status);
    if (state.q.trim()) params.set('q', state.q.trim());
    if (state.sort !== 'code') params.set('sort', state.sort);
    if (state.dir !== 'asc') params.set('dir', state.dir);
    if (state.page > 1) params.set('page', String(state.page));
    const target = makeUrl(state.selectedId, params);
    if (`${window.location.pathname}${window.location.search}` !== target) window.history.replaceState(null, '', target);
  }
  function showMessage(title, message, retry = true) {
    tbody.replaceChildren();
    const row = document.createElement('tr'); const cell = document.createElement('td'); cell.colSpan = 8;
    const box = el('div', 'warehouse-message'); box.setAttribute('role', title.includes('could not') ? 'alert' : 'status');
    box.append(el('strong', '', title), el('span', '', message));
    if (retry) { const button = el('button', 'button button-secondary button-small', 'Try again'); button.type = 'button'; button.addEventListener('click', load); box.append(button); }
    cell.append(box); row.append(cell); tbody.append(row);
  }
  function renderTabs() {
    tabs.replaceChildren();
    STATUSES.forEach(([key, label]) => {
      const button = el('button', `warehouse-tab${state.status === key ? ' is-active' : ''}`);
      button.type = 'button'; button.setAttribute('role', 'tab'); button.setAttribute('aria-selected', String(state.status === key));
      button.append(document.createTextNode(label), el('span', 'warehouse-tab-count', state.counts[key] ?? '—'));
      button.addEventListener('click', () => { if (state.status === key) return; state.status = key; state.page = 1; updateUrl(); load(); });
      tabs.append(button);
    });
  }
  function updateDirection() { direction.textContent = state.dir === 'asc' ? 'Ascending ↑' : 'Descending ↓'; }
  function renderPagination() {
    pagination.replaceChildren();
    const start = state.total ? (state.page - 1) * state.pageSize + 1 : 0;
    const end = Math.min(state.page * state.pageSize, state.total);
    pagination.append(el('span', 'warehouse-result-count', `Showing ${number(start)}–${number(end)} of ${number(state.total)} warehouses`));
    const controls = el('div', 'warehouse-page-controls');
    const prev = el('button', 'button button-secondary button-small', 'Previous'); prev.type = 'button'; prev.disabled = state.page <= 1;
    prev.addEventListener('click', () => { state.page -= 1; updateUrl(); load(); });
    const next = el('button', 'button button-secondary button-small', 'Next'); next.type = 'button'; next.disabled = state.page * state.pageSize >= state.total;
    next.addEventListener('click', () => { state.page += 1; updateUrl(); load(); });
    controls.append(prev, el('span', 'warehouse-page-number', `Page ${state.page}`), next); pagination.append(controls);
  }
  function renderTable() {
    tbody.replaceChildren();
    if (!state.rows.length) {
      showMessage(state.q ? 'No warehouses match this search.' : 'No warehouses yet.',
        state.q ? 'Try another code, name, or address.' : 'Add the first warehouse so staff and orders can be assigned.', false);
      renderPagination(); return;
    }
    state.rows.forEach((warehouse) => {
      const row = document.createElement('tr');
      const codeCell = document.createElement('td'); codeCell.append(el('strong', 'warehouse-code', warehouse.code));
      const nameCell = document.createElement('td'); const open = el('button', 'warehouse-open-button', warehouse.name); open.type = 'button'; open.addEventListener('click', () => openDetail(warehouse.id)); nameCell.append(open);
      const address = el('td', 'warehouse-address', warehouse.address);
      const statusCell = document.createElement('td'); statusCell.append(el('span', `warehouse-state ${warehouse.is_active ? 'is-active' : 'is-inactive'}`, warehouse.is_active ? 'Active' : 'Inactive'));
      const staff = el('td', 'warehouse-number', number(warehouse.staff_count)); const orders = el('td', 'warehouse-number', number(warehouse.open_orders)); const routes = el('td', 'warehouse-number', number(warehouse.active_routes));
      const actions = document.createElement('td'); actions.className = 'warehouse-row-actions';
      const view = el('button', 'button button-secondary button-small', 'View'); view.type = 'button'; view.addEventListener('click', () => openDetail(warehouse.id)); actions.append(view);
      row.append(codeCell, nameCell, address, statusCell, staff, orders, routes, actions); tbody.append(row);
    });
    renderPagination();
  }
  async function load() {
    const sequence = ++state.sequence;
    state.listController?.abort(); state.listController = new AbortController();
    showMessage('Loading warehouses…', 'Retrieving the warehouse directory.', false);
    const params = new URLSearchParams({ status: state.status, sort: state.sort, dir: state.dir, page: String(state.page), page_size: String(state.pageSize) });
    if (state.q.trim()) params.set('q', state.q.trim());
    updateUrl();
    try {
      const data = await api.get(`/api/admin/warehouses?${params}`, { signal: state.listController.signal });
      if (state.disposed || sequence !== state.sequence) return;
      state.rows = data.items; state.total = data.total; state.counts = data.counts; state.page = data.page; state.pageSize = data.page_size;
      renderTabs(); renderTable();
      if (state.selectedId && !state.detail) openDetail(state.selectedId);
      window.dispatchEvent(new CustomEvent('admin:data-refreshed', { detail: { at: new Date() } }));
    } catch (error) {
      if (state.disposed || sequence !== state.sequence || error.name === 'AbortError') return;
      showMessage('Warehouses could not be loaded', error.message || 'Try again in a moment.');
    } finally { if (sequence === state.sequence) renderPagination(); }
  }
  function drawerFrame(title) {
    drawerLayer.hidden = false; drawerLayer.replaceChildren();
    const backdrop = el('button', 'drawer-backdrop'); backdrop.type = 'button'; backdrop.setAttribute('aria-label', 'Close warehouse details'); backdrop.addEventListener('click', closeDetail);
    const drawer = el('aside', 'detail-drawer warehouse-drawer'); drawer.setAttribute('role', 'dialog'); drawer.setAttribute('aria-modal', 'true'); drawer.setAttribute('aria-label', 'Warehouse details');
    const header = el('div', 'drawer-header'); const copy = el('div'); copy.append(el('h2', '', title), el('p', 'drawer-subtitle', 'Warehouse details'));
    const close = el('button', 'drawer-close', 'Close'); close.type = 'button'; close.addEventListener('click', closeDetail); header.append(copy, close);
    drawer.append(header); drawerLayer.append(backdrop, drawer); close.focus(); return drawer;
  }
  function section(title, content) { const node = el('section', 'drawer-section'); node.append(el('h3', '', title), content); return node; }
  function closeDetail() { state.selectedId = null; state.detail = null; state.detailSequence += 1; state.detailController?.abort(); drawerLayer.hidden = true; drawerLayer.replaceChildren(); updateUrl(); }
  async function openDetail(id) {
    state.selectedId = id; state.detail = null; updateUrl();
    const sequence = ++state.detailSequence;
    state.detailController?.abort(); state.detailController = new AbortController();
    const drawer = drawerFrame('Warehouse details'); drawer.append(el('div', 'drawer-loading', 'Loading warehouse record…'));
    try {
      const data = await api.get(`/api/admin/warehouses/${encodeURIComponent(id)}`, { signal: state.detailController.signal });
      if (state.disposed || sequence !== state.detailSequence) return;
      state.detail = data; renderDetail(data);
    } catch (error) {
      if (state.disposed || sequence !== state.detailSequence || error.name === 'AbortError') return;
      const target = drawerFrame('Warehouse details'); target.append(el('div', 'page-message', error.message || 'Could not load this warehouse.'));
      const retry = el('button', 'button button-secondary', 'Try again'); retry.type = 'button'; retry.addEventListener('click', () => openDetail(id)); target.append(retry);
    }
  }
  function field(label, value) { const node = el('div', 'warehouse-detail-field'); node.append(el('span', '', label), el('strong', '', value)); return node; }
  function renderDetail(data) {
    const drawer = drawerFrame(data.code);
    const identity = el('div', 'warehouse-detail-grid');
    identity.append(field('Name', data.name), field('Status', data.is_active ? 'Active' : 'Inactive'), field('Staff', number(data.staff_count)), field('Created', date(data.created_at)), field('Open orders', number(data.open_orders)), field('Active routes', number(data.active_routes)));
    drawer.append(section('Warehouse', identity));

    const location = el('div', 'warehouse-detail-grid'); location.append(field('Code', data.code), field('Address', data.address), field('Latitude', data.latitude), field('Longitude', data.longitude));
    const map = el('a', 'text-link', 'Open in OpenStreetMap');
    map.href = `https://www.openstreetmap.org/?mlat=${encodeURIComponent(data.latitude)}&mlon=${encodeURIComponent(data.longitude)}#map=15/${encodeURIComponent(data.latitude)}/${encodeURIComponent(data.longitude)}`;
    map.target = '_blank'; map.rel = 'noopener noreferrer'; location.append(map);
    drawer.append(section('Location', location));

    const editForm = document.createElement('form'); editForm.className = 'warehouse-edit-form';
    editForm.append(el('h3', '', 'Edit details'));
    const name = inputField('Name', data.name, 'text'); name.input.maxLength = 120;
    const address = inputField('Address', data.address, 'text'); address.input.maxLength = 300;
    const coordinates = el('div', 'warehouse-coordinate-grid');
    const latitude = inputField('Latitude', data.latitude, 'number'); latitude.input.step = 'any'; latitude.input.min = '-90'; latitude.input.max = '90';
    const longitude = inputField('Longitude', data.longitude, 'number'); longitude.input.step = 'any'; longitude.input.min = '-180'; longitude.input.max = '180';
    coordinates.append(latitude.wrap, longitude.wrap);
    const error = el('p', 'warehouse-form-error'); error.hidden = true;
    const save = el('button', 'button button-primary', 'Save changes'); save.type = 'submit';
    editForm.append(name.wrap, address.wrap, coordinates, el('p', 'warehouse-form-hint', 'Warehouse code cannot be changed.'), error, save);
    editForm.addEventListener('submit', async (event) => {
      event.preventDefault(); error.hidden = true; save.disabled = true;
      const lat = Number(latitude.input.value); const lon = Number(longitude.input.value);
      if (!name.input.value.trim() || !address.input.value.trim() || !Number.isFinite(lat) || !Number.isFinite(lon) || lat < -90 || lat > 90 || lon < -180 || lon > 180) {
        error.textContent = 'Enter a name, address, and valid latitude/longitude.'; error.hidden = false; save.disabled = false; return;
      }
      try {
        const patch = {};
        if (name.input.value.trim() !== data.name) patch.name = name.input.value.trim();
        if (address.input.value.trim() !== data.address) patch.address = address.input.value.trim();
        if (lat !== Number(data.latitude) || lon !== Number(data.longitude)) { patch.latitude = lat; patch.longitude = lon; }
        if (!Object.keys(patch).length) { error.textContent = 'There are no changes to save.'; error.hidden = false; save.disabled = false; return; }
        await api.patch(`/api/admin/warehouses/${encodeURIComponent(data.id)}`, patch);
        onToast('Warehouse updated.'); await load(); await openDetail(data.id);
      } catch (requestError) { error.textContent = requestError.message || 'Warehouse could not be updated.'; error.hidden = false; save.disabled = false; }
    });
    drawer.append(section('Edit warehouse', editForm));

    const staffContent = el('div', 'warehouse-staff-section');
    const assigned = el('div', 'warehouse-staff-list');
    if (!data.staff.length) assigned.append(el('p', 'warehouse-muted', 'No staff assigned yet.'));
    data.staff.forEach((member) => {
      const row = el('div', 'warehouse-staff-row'); const person = el('div', 'warehouse-staff-person');
      person.append(el('strong', '', member.full_name), el('span', '', member.email || 'No email'), el('small', '', member.roles.join(' · ')));
      const remove = el('button', 'button button-secondary button-small', 'Remove'); remove.type = 'button';
      remove.addEventListener('click', async () => {
        if (!window.confirm(`Remove ${member.full_name} from ${data.code}?`)) return;
        remove.disabled = true;
        try { await api.delete(`/api/admin/warehouses/${encodeURIComponent(data.id)}/staff/${encodeURIComponent(member.user_id)}`); onToast('Staff assignment removed.'); await load(); await openDetail(data.id); }
        catch (requestError) { remove.disabled = false; onToast(requestError.message || 'Staff assignment could not be removed.', 'error'); }
      });
      row.append(person, remove); assigned.append(row);
    });
    const picker = el('div', 'warehouse-staff-picker');
    const pickerControls = el('div', 'warehouse-picker-controls');
    const staffSearch = document.createElement('input'); staffSearch.type = 'search'; staffSearch.placeholder = 'Search active dispatcher or fleet manager'; staffSearch.maxLength = 100; staffSearch.setAttribute('aria-label', 'Search eligible staff');
    const addStaff = el('button', 'button button-secondary button-small', 'Add'); addStaff.type = 'button'; addStaff.disabled = true; pickerControls.append(staffSearch, addStaff);
    const candidateSelect = document.createElement('select'); candidateSelect.setAttribute('aria-label', 'Choose staff member'); candidateSelect.append(new Option('Search for an active staff member', ''));
    const pickerMessage = el('p', 'warehouse-muted'); picker.append(pickerControls, candidateSelect, pickerMessage);
    let pickerSequence = 0;
    async function findStaff() {
      const sequence = ++pickerSequence; const term = staffSearch.value.trim(); addStaff.disabled = true;
      candidateSelect.replaceChildren(new Option(term ? 'Searching…' : 'Type a name or email to search', ''));
      if (!term) return;
      try {
        const query = new URLSearchParams({ status: 'active', q: term, sort: 'full_name', dir: 'asc', page: '1', page_size: '100' });
        const [dispatchers, fleetManagers] = await Promise.all([
          api.get(`/api/admin/users?${new URLSearchParams({ ...Object.fromEntries(query), role: 'dispatcher' })}`),
          api.get(`/api/admin/users?${new URLSearchParams({ ...Object.fromEntries(query), role: 'fleet_manager' })}`)
        ]);
        if (sequence !== pickerSequence || !candidateSelect.isConnected) return;
        const assignedIds = new Set(data.staff.map((person) => person.user_id));
        const candidates = new Map([...dispatchers.items, ...fleetManagers.items].filter((person) => !assignedIds.has(person.id)).map((person) => [person.id, person]));
        candidateSelect.replaceChildren(new Option(candidates.size ? 'Choose a staff member' : 'No unassigned matches', ''));
        [...candidates.values()].sort((a, b) => a.full_name.localeCompare(b.full_name)).forEach((person) => candidateSelect.add(new Option(`${person.full_name} · ${person.roles.join(', ')}`, person.id)));
        pickerMessage.textContent = candidates.size ? '' : 'No active, eligible staff matched that search.';
      } catch (requestError) {
        if (sequence === pickerSequence) pickerMessage.textContent = requestError.message || 'Staff could not be searched.';
      }
    }
    let pickerTimer;
    staffSearch.addEventListener('input', () => { window.clearTimeout(pickerTimer); pickerTimer = window.setTimeout(findStaff, 250); });
    candidateSelect.addEventListener('change', () => { addStaff.disabled = !candidateSelect.value; });
    addStaff.addEventListener('click', async () => {
      if (!candidateSelect.value) return;
      addStaff.disabled = true;
      try { await api.post(`/api/admin/warehouses/${encodeURIComponent(data.id)}/staff`, { user_id: candidateSelect.value }); onToast('Staff assigned to warehouse.'); await load(); await openDetail(data.id); }
      catch (requestError) { addStaff.disabled = false; onToast(requestError.message || 'Staff could not be assigned.', 'error'); }
    });
    staffContent.append(assigned, picker); drawer.append(section('Staff', staffContent));

    const orderContent = el('div', 'warehouse-order-statuses');
    Object.entries(data.orders_by_status).forEach(([status, count]) => { const item = el('div', 'warehouse-order-status'); item.append(el('span', '', ORDER_STATUS_LABELS[status] || status), el('strong', '', number(count))); orderContent.append(item); });
    drawer.append(section('Orders by status', orderContent));

    const routes = el('div', 'warehouse-route-list');
    if (!data.active_route_list.length) routes.append(el('p', 'warehouse-muted', 'No active routes.'));
    data.active_route_list.forEach((routeItem) => { const row = el('div', 'warehouse-route-row'); row.append(el('strong', '', routeItem.driver_name), el('span', '', routeItem.status.replaceAll('_', ' ')), el('small', '', `${number(routeItem.stops_done)} of ${number(routeItem.stops_total)} stops complete`)); routes.append(row); });
    drawer.append(section('Active routes', routes));

    const actions = el('div', 'drawer-actions'); const toggle = el('button', `button ${data.is_active ? 'button-secondary' : 'button-primary'}`, data.is_active ? 'Deactivate warehouse' : 'Reactivate warehouse'); toggle.type = 'button';
    toggle.addEventListener('click', async () => {
      const action = data.is_active ? 'deactivate' : 'reactivate';
      if (data.is_active && !window.confirm(`Deactivate ${data.code}? New orders should no longer be assigned to this warehouse.`)) return;
      toggle.disabled = true;
      try { await api.post(`/api/admin/warehouses/${encodeURIComponent(data.id)}/${action}`, {}); onToast(`Warehouse ${action}d.`); await load(); await openDetail(data.id); }
      catch (requestError) { toggle.disabled = false; onToast(requestError.message || `Warehouse could not be ${action}d.`, 'error'); }
    });
    actions.append(toggle); drawer.append(actions);
  }
  function inputField(labelText, value, type) {
    const wrap = document.createElement('label'); wrap.className = 'warehouse-dialog-field'; wrap.append(el('span', '', labelText));
    const input = document.createElement('input'); input.type = type; input.value = value ?? ''; wrap.append(input); return { wrap, input };
  }
  function openCreateDialog() {
    const dialog = document.createElement('dialog'); dialog.className = 'admin-dialog warehouse-dialog';
    const form = document.createElement('form'); form.method = 'dialog'; form.noValidate = true;
    form.append(el('h2', '', 'Add warehouse'), el('p', '', 'Add a facility to the network so staff and orders can be assigned.'));
    const code = inputField('Code', '', 'text'); code.input.maxLength = 12; code.input.autocomplete = 'off'; code.input.placeholder = 'e.g. WH-DEL-01';
    const name = inputField('Name', '', 'text'); name.input.maxLength = 120;
    const address = inputField('Address', '', 'text'); address.input.maxLength = 300;
    const coordinates = el('div', 'warehouse-coordinate-grid');
    const latitude = inputField('Latitude', '', 'number'); latitude.input.step = 'any'; latitude.input.min = '-90'; latitude.input.max = '90';
    const longitude = inputField('Longitude', '', 'number'); longitude.input.step = 'any'; longitude.input.min = '-180'; longitude.input.max = '180';
    coordinates.append(latitude.wrap, longitude.wrap);
    form.append(code.wrap, name.wrap, address.wrap, coordinates, el('small', 'warehouse-form-hint', 'Right-click a point in Google Maps or OpenStreetMap to copy coordinates. Code is 2–12 letters, numbers, or hyphens and is unique.'));
    const error = el('p', 'warehouse-form-error'); error.hidden = true;
    const actions = el('div', 'dialog-actions'); const cancel = el('button', 'button button-secondary', 'Cancel'); cancel.type = 'button'; cancel.addEventListener('click', () => dialog.close());
    const submit = el('button', 'button button-primary', 'Create warehouse'); submit.type = 'submit'; actions.append(cancel, submit); form.append(error, actions); dialog.append(form); root.append(dialog);
    form.addEventListener('submit', async (event) => {
      event.preventDefault(); error.hidden = true;
      const normalizedCode = code.input.value.trim().toUpperCase(); const lat = Number(latitude.input.value); const lon = Number(longitude.input.value);
      if (!/^[A-Z0-9-]{2,12}$/.test(normalizedCode) || !name.input.value.trim() || !address.input.value.trim() || !Number.isFinite(lat) || lat < -90 || lat > 90 || !Number.isFinite(lon) || lon < -180 || lon > 180) {
        error.textContent = 'Enter a unique-looking code, name, address, and coordinates within the valid ranges.'; error.hidden = false; return;
      }
      submit.disabled = true;
      try { const created = await api.post('/api/admin/warehouses', { code: normalizedCode, name: name.input.value.trim(), address: address.input.value.trim(), latitude: lat, longitude: lon }); dialog.close(); onToast(`Warehouse ${created.code} created.`); state.status = 'all'; state.page = 1; updateUrl(); await load(); openDetail(created.id); }
      catch (requestError) { error.textContent = requestError.message || 'Warehouse could not be created.'; error.hidden = false; submit.disabled = false; }
    });
    dialog.addEventListener('close', () => dialog.remove(), { once: true }); dialog.showModal(); code.input.focus();
  }

  addButton.addEventListener('click', openCreateDialog);
  search.addEventListener('input', () => { window.clearTimeout(searchTimer); searchTimer = window.setTimeout(() => { state.q = search.value; state.page = 1; updateUrl(); load(); }, 250); });
  sort.addEventListener('change', () => { state.sort = sort.value; state.page = 1; updateUrl(); load(); });
  direction.addEventListener('click', () => { state.dir = state.dir === 'asc' ? 'desc' : 'asc'; updateDirection(); state.page = 1; updateUrl(); load(); });
  refresh.addEventListener('click', () => { load(); if (state.selectedId) openDetail(state.selectedId); });
  updateDirection(); renderTabs(); updateUrl(); load();
  return {
    element: root, refresh: load,
    destroy() { state.disposed = true; window.clearTimeout(searchTimer); state.sequence += 1; state.detailSequence += 1; state.listController?.abort(); state.detailController?.abort(); drawerLayer.hidden = true; drawerLayer.replaceChildren(); }
  };
}
