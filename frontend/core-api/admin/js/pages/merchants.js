const SEGMENTS = [['all', 'All merchants'], ['active', 'Active'], ['inactive', 'Inactive']];
const SORTS = [['name', 'Name'], ['created_at', 'Created'], ['orders_total', 'Orders']];
const ORDER_STATUSES = [
  ['pending', 'Pending'], ['assigned', 'Assigned'], ['out_for_delivery', 'Out for delivery'],
  ['attempt_failed', 'Attempt failed'], ['delivered', 'Delivered'], ['returned', 'Returned'], ['cancelled', 'Cancelled']
];

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}
function date(value, withTime = false) {
  if (!value) return '—';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? '—' : new Intl.DateTimeFormat(undefined, withTime
    ? { dateStyle: 'medium', timeStyle: 'short' } : { dateStyle: 'medium' }).format(parsed);
}
function count(value) { return Number(value || 0).toLocaleString(); }
function makePageUrl(id, params) {
  if (id) params.set('id', id);
  const query = params.toString();
  return `${window.location.pathname}${query ? `?${query}` : ''}`;
}

export function createMerchantsPage({ api, onToast, route }) {
  const root = el('div', 'merchants-page');
  const intro = el('div', 'page-intro');
  const copy = el('div');
  copy.append(el('h2', '', 'Merchant accounts'), el('p', '', 'Manage the companies sending parcels through the network and review their order activity.'));
  const createButton = el('button', 'button button-primary', 'Add merchant'); createButton.type = 'button';
  intro.append(copy, createButton);

  const tabs = el('div', 'merchant-tabs'); tabs.setAttribute('role', 'tablist'); tabs.setAttribute('aria-label', 'Merchant status');
  const toolbar = el('div', 'merchant-toolbar');
  const search = document.createElement('input'); search.type = 'search'; search.maxLength = 100;
  search.placeholder = 'Search merchant name or contact email'; search.setAttribute('aria-label', 'Search merchants');
  const sort = document.createElement('select'); sort.setAttribute('aria-label', 'Sort merchants');
  SORTS.forEach(([value, label]) => { const option = el('option', '', label); option.value = value; sort.append(option); });
  const direction = el('button', 'button button-secondary button-small'); direction.type = 'button';
  const refresh = el('button', 'button button-secondary', 'Refresh'); refresh.type = 'button';
  toolbar.append(search, sort, direction, refresh);

  const panel = el('section', 'panel merchant-table-panel');
  const panelHeading = el('div', 'section-label');
  panelHeading.append(el('h2', '', 'Merchant directory'), el('p', '', 'Account activity and order volume'));
  const scroll = el('div', 'merchant-table-scroll');
  const table = el('table', 'merchant-table');
  const thead = document.createElement('thead'); const headerRow = document.createElement('tr');
  ['Merchant', 'Orders', 'Last 30 days', 'Members', 'Account', 'Created', ''].forEach((label) => {
    const th = el('th', '', label); if (!label) th.setAttribute('aria-label', 'Actions'); headerRow.append(th);
  });
  thead.append(headerRow); const tbody = document.createElement('tbody'); table.append(thead, tbody); scroll.append(table);
  const pagination = el('div', 'merchant-pagination');
  panel.append(panelHeading, scroll, pagination);
  const drawerLayer = el('div', 'drawer-layer'); drawerLayer.hidden = true;
  root.append(intro, tabs, toolbar, panel, drawerLayer);

  const params = route?.query || new URLSearchParams();
  const state = {
    status: SEGMENTS.some(([key]) => key === params.get('status')) ? (params.get('status') || 'all') : 'all',
    q: (params.get('q') || '').slice(0, 100),
    sort: SORTS.some(([key]) => key === params.get('sort')) ? (params.get('sort') || 'name') : 'name',
    dir: ['asc', 'desc'].includes(params.get('dir')) ? params.get('dir') : 'asc',
    page: Math.max(1, Number.isSafeInteger(Number(params.get('page'))) ? Number(params.get('page')) : 1),
    pageSize: 25, total: 0, counts: {}, rows: [], selectedId: route?.itemId || null,
    detail: null, requestSeq: 0, detailSeq: 0, loading: false, disposed: false,
    listController: null, detailController: null
  };
  search.value = state.q; sort.value = state.sort;
  let searchTimer;

  function updateUrl() {
    const next = new URLSearchParams();
    next.set('status', state.status);
    if (state.q.trim()) next.set('q', state.q.trim());
    if (state.sort !== 'name') next.set('sort', state.sort);
    if (state.dir !== 'asc') next.set('dir', state.dir);
    if (state.page > 1) next.set('page', String(state.page));
    const target = makePageUrl(state.selectedId, next);
    if (`${window.location.pathname}${window.location.search}` !== target) window.history.replaceState(null, '', target);
  }
  function updateDirection() { direction.textContent = state.dir === 'asc' ? 'A to Z ↑' : 'Z to A ↓'; }
  function updateTabs() {
    tabs.replaceChildren();
    SEGMENTS.forEach(([key, label]) => {
      const button = el('button', `merchant-tab${state.status === key ? ' is-active' : ''}`);
      button.type = 'button'; button.setAttribute('role', 'tab'); button.setAttribute('aria-selected', String(state.status === key));
      button.append(document.createTextNode(label), el('span', 'merchant-tab-count', state.counts[key] ?? '—'));
      button.addEventListener('click', () => {
        if (state.status === key) return;
        state.status = key; state.page = 1; updateUrl(); load();
      });
      tabs.append(button);
    });
  }
  function showTableMessage(title, message, retry = true) {
    tbody.replaceChildren();
    const row = document.createElement('tr'); const cell = document.createElement('td'); cell.colSpan = 7;
    const box = el('div', 'merchant-message'); box.setAttribute('role', title.includes('could not') ? 'alert' : 'status');
    box.append(el('strong', '', title), el('span', '', message));
    if (retry) { const button = el('button', 'button button-secondary button-small', 'Try again'); button.type = 'button'; button.addEventListener('click', load); box.append(button); }
    cell.append(box); row.append(cell); tbody.append(row);
  }
  function stateBadge(active) {
    return el('span', `merchant-state ${active ? 'is-active' : 'is-inactive'}`, active ? 'Active' : 'Inactive');
  }
  function renderTable() {
    tbody.replaceChildren();
    if (!state.rows.length) {
      const searched = Boolean(search.value.trim());
      showTableMessage(searched ? 'No merchants match this search.' : 'No merchants in this view.',
        searched ? 'Try another company name or contact email.' : 'Merchant accounts will appear here when they are created.', false);
      renderPagination(); return;
    }
    state.rows.forEach((merchant) => {
      const row = document.createElement('tr');
      const identity = document.createElement('td'); identity.className = 'merchant-person-cell';
      const open = el('button', 'merchant-name-button', merchant.name); open.type = 'button'; open.addEventListener('click', () => openDetail(merchant.id));
      identity.append(open, el('span', 'merchant-contact', merchant.contact_email || merchant.contact_phone || 'No contact details'));
      const orders = el('td', 'merchant-number', count(merchant.orders_total));
      const recent = el('td', 'merchant-number', count(merchant.orders_30d));
      const members = el('td', 'merchant-number', count(merchant.member_count));
      const account = document.createElement('td'); account.append(stateBadge(merchant.is_active));
      const created = el('td', 'merchant-date', date(merchant.created_at));
      const actions = el('td', 'merchant-row-actions');
      const detail = el('button', 'button button-quiet button-small', 'View'); detail.type = 'button'; detail.addEventListener('click', () => openDetail(merchant.id));
      const edit = el('button', 'button button-secondary button-small', 'Edit'); edit.type = 'button'; edit.addEventListener('click', () => editMerchant(merchant));
      actions.append(detail, edit);
      row.append(identity, orders, recent, members, account, created, actions); tbody.append(row);
    });
    renderPagination();
  }
  function renderPagination() {
    pagination.replaceChildren();
    const start = state.total ? (state.page - 1) * state.pageSize + 1 : 0;
    const end = Math.min(state.page * state.pageSize, state.total);
    pagination.append(el('span', 'merchant-result-count', `Showing ${start}–${end} of ${count(state.total)} merchants`));
    const controls = el('div', 'merchant-page-controls');
    const prev = el('button', 'button button-secondary button-small', 'Previous'); prev.type = 'button'; prev.disabled = state.page <= 1 || state.loading;
    prev.addEventListener('click', () => { state.page -= 1; updateUrl(); load(); });
    const next = el('button', 'button button-secondary button-small', 'Next'); next.type = 'button'; next.disabled = state.page * state.pageSize >= state.total || state.loading;
    next.addEventListener('click', () => { state.page += 1; updateUrl(); load(); });
    controls.append(prev, el('span', 'merchant-page-number', `Page ${state.page}`), next); pagination.append(controls);
  }

  async function load() {
    const seq = ++state.requestSeq;
    state.listController?.abort(); state.listController = new AbortController();
    state.loading = true; showTableMessage('Loading merchants…', 'Retrieving the merchant directory.', false);
    const query = new URLSearchParams({ status: state.status, q: search.value.trim(), sort: state.sort, dir: state.dir,
      page: String(state.page), page_size: String(state.pageSize) });
    updateUrl();
    try {
      const data = await api.get(`/api/admin/merchants?${query}`, { signal: state.listController.signal });
      if (state.disposed || seq !== state.requestSeq) return;
      state.rows = data.items; state.total = data.total; state.counts = data.counts; state.page = data.page; state.pageSize = data.page_size;
      updateTabs(); renderTable();
      if (state.selectedId && !state.detail) openDetail(state.selectedId);
      window.dispatchEvent(new CustomEvent('admin:data-refreshed', { detail: { at: new Date() } }));
    } catch (error) {
      if (state.disposed || seq !== state.requestSeq || error.name === 'AbortError') return;
      showTableMessage('Merchants could not be loaded', error.message || 'Try again in a moment.');
    } finally {
      if (seq === state.requestSeq) { state.loading = false; renderPagination(); }
    }
  }
  function drawerFrame(title) {
    drawerLayer.hidden = false; drawerLayer.replaceChildren();
    const backdrop = el('button', 'drawer-backdrop'); backdrop.type = 'button'; backdrop.setAttribute('aria-label', 'Close merchant details'); backdrop.addEventListener('click', closeDetail);
    const drawer = el('aside', 'detail-drawer merchant-drawer'); drawer.setAttribute('role', 'dialog'); drawer.setAttribute('aria-modal', 'true'); drawer.setAttribute('aria-label', 'Merchant details');
    const header = el('div', 'drawer-header'); const heading = document.createElement('div'); heading.append(el('h2', '', title), el('p', 'drawer-subtitle', 'Merchant account'));
    const close = el('button', 'drawer-close', 'Close'); close.type = 'button'; close.addEventListener('click', closeDetail); header.append(heading, close);
    drawer.append(header); drawerLayer.append(backdrop, drawer); close.focus(); return drawer;
  }
  function drawerSection(title, content) { const section = el('section', 'drawer-section'); section.append(el('h3', '', title), content); return section; }
  async function openDetail(id) {
    state.selectedId = id; state.detail = null; updateUrl();
    const seq = ++state.detailSeq;
    state.detailController?.abort(); state.detailController = new AbortController();
    const drawer = drawerFrame('Merchant details'); drawer.append(el('div', 'drawer-loading', 'Loading merchant record…'));
    try {
      const data = await api.get(`/api/admin/merchants/${encodeURIComponent(id)}`, { signal: state.detailController.signal });
      if (state.disposed || seq !== state.detailSeq) return;
      state.detail = data; renderDetail(data);
    } catch (error) {
      if (state.disposed || seq !== state.detailSeq || error.name === 'AbortError') return;
      const target = drawerFrame('Merchant details');
      target.append(el('div', 'page-message', error.message || 'Could not load this merchant.'));
      const retry = el('button', 'button button-secondary', 'Try again'); retry.type = 'button'; retry.addEventListener('click', () => openDetail(id)); target.append(retry);
    }
  }
  function renderDetail(data) {
    const drawer = drawerFrame(data.name);
    const status = el('div', 'merchant-detail-state'); status.append(stateBadge(data.is_active)); drawer.append(status);
    const contact = el('div', 'merchant-detail-grid');
    [['Contact email', data.contact_email || '—'], ['Contact phone', data.contact_phone || '—'], ['Created', date(data.created_at, true)], ['Members', count(data.member_count)]].forEach(([label, value]) => {
      const item = el('div', 'merchant-detail-field'); item.append(el('span', '', label), el('strong', '', value)); contact.append(item);
    });
    drawer.append(drawerSection('Company details', contact));

    const metrics = el('div', 'merchant-stat-grid');
    [['Total orders', data.orders_total], ['Last 30 days', data.orders_30d]].forEach(([label, value]) => {
      const card = el('div', 'merchant-stat'); card.append(el('span', '', label), el('strong', '', count(value))); metrics.append(card);
    });
    drawer.append(drawerSection('Order volume', metrics));

    const statuses = el('div', 'merchant-status-grid');
    ORDER_STATUSES.forEach(([key, label]) => {
      const item = el('div', 'merchant-status-item'); item.append(el('span', '', label), el('strong', '', count(data.orders_by_status?.[key]))); statuses.append(item);
    });
    drawer.append(drawerSection('Orders by status', statuses));

    const memberList = el('div', 'merchant-member-list');
    if (!data.members.length) memberList.append(el('p', 'merchant-muted', 'No members are linked to this merchant.'));
    data.members.forEach((member) => {
      const row = el('div', 'merchant-member-row'); const identity = el('div');
      identity.append(el('strong', '', member.full_name), el('span', '', member.email || 'No email on account'));
      row.append(identity, el('span', `merchant-state ${member.account_active ? 'is-active' : 'is-inactive'}`, member.account_active ? 'Active' : 'Inactive'));
      memberList.append(row);
    });
    drawer.append(drawerSection('Merchant members', memberList));

    const orderList = el('div', 'merchant-order-list');
    if (!data.recent_orders.length) orderList.append(el('p', 'merchant-muted', 'No orders have been placed yet.'));
    data.recent_orders.forEach((order) => {
      const item = el('div', 'merchant-order-row'); const identity = el('div');
      identity.append(el('strong', '', order.merchant_order_ref), el('span', '', order.tracking_token));
      item.append(identity, el('span', `order-status order-${order.status}`, order.status.replaceAll('_', ' ')), el('time', '', date(order.created_at)));
      orderList.append(item);
    });
    drawer.append(drawerSection('Recent orders', orderList));

    const footer = el('div', 'drawer-actions');
    const edit = el('button', 'button button-secondary', 'Edit company details'); edit.type = 'button'; edit.addEventListener('click', () => editMerchant(data)); footer.append(edit);
    const toggle = el('button', `button ${data.is_active ? 'button-secondary' : 'button-primary'}`, data.is_active ? 'Deactivate merchant' : 'Reactivate merchant');
    toggle.type = 'button'; toggle.addEventListener('click', () => toggleMerchant(data)); footer.append(toggle); drawer.append(footer);
  }
  function closeDetail() {
    state.detailSeq += 1; state.detailController?.abort(); state.selectedId = null; state.detail = null;
    drawerLayer.hidden = true; drawerLayer.replaceChildren(); updateUrl();
  }

  function field(form, labelText, name, options = {}) {
    const label = el('label', 'dialog-field'); label.append(el('span', '', labelText));
    const input = document.createElement(options.multiline ? 'textarea' : 'input');
    input.name = name; input.maxLength = options.maxLength || 200; input.required = Boolean(options.required);
    if (options.type && input instanceof HTMLInputElement) input.type = options.type;
    if (options.multiline) input.rows = 3;
    if (options.autocomplete) input.autocomplete = options.autocomplete;
    if (options.value !== undefined && options.value !== null) input.value = options.value;
    if (options.placeholder) input.placeholder = options.placeholder;
    label.append(input); form.append(label); return input;
  }
  function openMerchantForm(existing = null) {
    const dialog = document.createElement('dialog'); dialog.className = 'admin-dialog merchant-dialog';
    const form = document.createElement('form'); form.method = 'dialog';
    const isEdit = Boolean(existing);
    form.append(el('h2', '', isEdit ? 'Edit merchant' : 'Create merchant'));
    form.append(el('p', 'dialog-copy', isEdit
      ? 'Update the company contact information. Leave optional contact fields blank to keep their current values.'
      : 'Create the merchant account and assign its owner. New owners receive a password setup invitation.'));
    field(form, 'Merchant name', 'name', { required: true, maxLength: 200, value: existing?.name || '' });
    field(form, 'Company contact email', 'contact_email', { type: 'email', maxLength: 254, value: existing?.contact_email || '' });
    field(form, 'Company contact phone', 'contact_phone', { type: 'tel', maxLength: 20, placeholder: '+12125551234', value: existing?.contact_phone || '' });
    if (!isEdit) {
      const divider = el('div', 'merchant-form-subhead'); divider.append(el('strong', '', 'Primary owner'), el('span', '', 'This person receives initial company access.')); form.append(divider);
      field(form, 'Owner full name', 'owner_full_name', { required: true, maxLength: 200, autocomplete: 'name' });
      field(form, 'Owner email', 'owner_email', { type: 'email', required: true, maxLength: 254, autocomplete: 'email' });
    }
    const error = el('p', 'dialog-error'); error.hidden = true; error.setAttribute('role', 'alert');
    const actions = el('div', 'dialog-actions'); const cancel = el('button', 'button button-secondary', 'Cancel'); cancel.value = 'cancel';
    const submit = el('button', 'button button-primary', isEdit ? 'Save changes' : 'Create merchant'); submit.value = 'submit'; actions.append(cancel, submit);
    form.append(error, actions); dialog.append(form); document.body.append(dialog);
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (event.submitter?.value !== 'submit') { dialog.close('cancel'); return; }
      if (!form.reportValidity()) return;
      const values = Object.fromEntries(new FormData(form).entries());
      const body = {
        name: values.name.trim(), contact_email: values.contact_email.trim() || null,
        contact_phone: values.contact_phone.trim() || null
      };
      if (!isEdit) { body.owner_full_name = values.owner_full_name.trim(); body.owner_email = values.owner_email.trim(); }
      submit.disabled = true; submit.textContent = isEdit ? 'Saving…' : 'Creating…'; error.hidden = true;
      try {
        const result = isEdit
          ? await api.patch(`/api/admin/merchants/${encodeURIComponent(existing.id)}`, body)
          : await api.post('/api/admin/merchants', body);
        dialog.close('success');
        if (isEdit) {
          onToast('Merchant details updated.');
          if (state.selectedId === existing.id) { state.detail = null; await openDetail(existing.id); }
        } else {
          const ownerMessage = result.owner.created
            ? (result.invite_sent ? 'New owner invitation sent.' : 'New owner invite email was not sent; review the owner account in Users.')
            : 'Existing user linked as merchant owner.';
          onToast(`Merchant created. ${ownerMessage}`, result.owner.created && !result.invite_sent ? 'error' : 'success');
          state.status = 'all'; state.q = ''; state.page = 1; search.value = ''; updateUrl();
        }
        await load();
      } catch (requestError) {
        error.textContent = requestError.message || 'The merchant could not be saved.'; error.hidden = false;
        submit.disabled = false; submit.textContent = isEdit ? 'Save changes' : 'Create merchant';
      }
    });
    dialog.addEventListener('close', () => dialog.remove(), { once: true });
    dialog.showModal(); form.querySelector('input')?.focus();
  }
  function editMerchant(merchant) { openMerchantForm(merchant); }
  function toggleMerchant(merchant) {
    const action = merchant.is_active ? 'deactivate' : 'reactivate';
    confirmMerchantChange(merchant, action);
  }
  function confirmMerchantChange(merchant, action) {
    const isDeactivate = action === 'deactivate';
    const dialog = document.createElement('dialog'); dialog.className = 'admin-dialog';
    const form = document.createElement('form'); form.method = 'dialog';
    form.append(el('h2', '', isDeactivate ? 'Deactivate merchant?' : 'Reactivate merchant?'));
    form.append(el('p', '', isDeactivate
      ? `New orders will be blocked for ${merchant.name}. Existing orders will continue through delivery.`
      : `Restore order intake for ${merchant.name}?`));
    const error = el('p', 'dialog-error'); error.hidden = true; error.setAttribute('role', 'alert');
    const actions = el('div', 'dialog-actions'); const cancel = el('button', 'button button-secondary', 'Cancel'); cancel.value = 'cancel';
    const confirm = el('button', `button ${isDeactivate ? 'button-danger' : 'button-primary'}`, isDeactivate ? 'Deactivate' : 'Reactivate'); confirm.value = 'confirm'; actions.append(cancel, confirm);
    form.append(error, actions); dialog.append(form); document.body.append(dialog); dialog.showModal();
    form.addEventListener('submit', async (event) => {
      event.preventDefault(); if (event.submitter?.value !== 'confirm') { dialog.close('cancel'); return; }
      confirm.disabled = true; confirm.textContent = isDeactivate ? 'Deactivating…' : 'Reactivating…'; error.hidden = true;
      try {
        await api.post(`/api/admin/merchants/${encodeURIComponent(merchant.id)}/${action}`, {});
        dialog.close('success'); onToast(isDeactivate ? 'Merchant deactivated. Existing orders remain active.' : 'Merchant reactivated.');
        state.detail = null; await load();
      } catch (requestError) {
        error.textContent = requestError.message || 'The merchant status could not be changed.'; error.hidden = false;
        confirm.disabled = false; confirm.textContent = isDeactivate ? 'Deactivate' : 'Reactivate';
      }
    });
    dialog.addEventListener('close', () => dialog.remove(), { once: true });
  }

  sort.addEventListener('change', () => { state.sort = sort.value; state.page = 1; updateUrl(); load(); });
  direction.addEventListener('click', () => { state.dir = state.dir === 'asc' ? 'desc' : 'asc'; state.page = 1; updateDirection(); updateUrl(); load(); });
  refresh.addEventListener('click', () => { load(); if (state.selectedId) openDetail(state.selectedId); });
  search.addEventListener('input', () => {
    window.clearTimeout(searchTimer); searchTimer = window.setTimeout(() => { state.q = search.value; state.page = 1; updateUrl(); load(); }, 250);
  });
  createButton.addEventListener('click', () => openMerchantForm());
  updateDirection(); updateTabs(); updateUrl(); load();
  return {
    element: root,
    refresh: load,
    destroy() {
      state.disposed = true; window.clearTimeout(searchTimer); state.requestSeq += 1; state.detailSeq += 1;
      state.listController?.abort(); state.detailController?.abort(); drawerLayer.hidden = true; drawerLayer.replaceChildren();
    }
  };
}
