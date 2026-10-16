# LOGIPULSE — Admin Console: Requirements Specification

Audience: the engineer (AI agent) implementing the admin part. You have codebase access. This document is the single source of truth for what to build. Where it is silent, choose the simplest option that satisfies §3 (Security) and note the choice in your final summary. Do not add features not listed here.

Stack (fixed): FastAPI + SQLAlchemy async, PostgreSQL 15 (Neon), Redis, plain HTML/CSS/JS frontend, cookie-session auth (already built), slowapi, SMTP via existing `SMTP_USER` / `SMTP_PASSWORD` env vars. Everything must be free to run.

---

## 1. Purpose and scope

The admin is the platform owner. Admin sets up the organisation (merchants, warehouses, staff), approves drivers, controls account access, and audits what is happening across all orders. Admin does **not** run daily dispatch, manage vehicles, or manage a merchant's own users.

### In scope (v1)
| # | Page | Purpose |
|---|------|---------|
| 1 | Overview | Health of the platform now + a queue of things needing admin action |
| 2 | Drivers | Approve / reject driver sign-ups, see the driver roster |
| 3 | Users | Find any account; invite staff; control access, roles, sessions |
| 4 | Merchants | Create and manage merchant companies |
| 5 | Warehouses | Create and manage warehouses and their staff |
| 6 | Orders | Read-only, system-wide order lookup with full status timeline |
| 7 | Activity | Read-only audit trail of every admin action |

### Out of scope (do not build)
Vehicles (fleet manager's job), merchant member management after creation (merchant's job), order creation/editing/cancelling, route planning, live map, analytics/BI, billing, geofencing, system/engine configuration, RBAC matrix editor, log streaming terminal, CSV export, notifications centre.

### Decisions already made (do not revisit)
- Admin can see all orders but cannot change them in v1 (read-only).
- Merchant deactivation is allowed at any time (it only blocks **new** orders; open orders continue). Warehouse deactivation is blocked while it has open orders or active routes.
- A driver is blocked via `users.is_active = false`; `drivers` has no `is_active`.
- Warehouse staff assignment is an admin job (admin creates warehouses). Merchant member assignment is not.
- One small new table is added: `admin_audit_log` (§4.2). No other tables.
- "Today" and date boundaries use `APP_TIMEZONE` (default `Asia/Kolkata`).

---

## 2. Roles and access model

- Roles live in `user_roles`; a user may hold several. Admin console requires the `admin` role. Nothing else grants access, ever.
- Roles admin may grant or revoke on others: `dispatcher`, `fleet_manager`, `admin` only. `customer`, `merchant`, `driver` are never granted or revoked through the console (customer/driver via self-registration, merchant via merchant creation).
- Public registration must never be able to produce `admin`, `dispatcher` or `fleet_manager` (verify and keep it that way).
- A `dispatcher` / `fleet_manager` with **zero** `warehouse_staff` rows has no warehouse access. Downstream role panels must treat empty as deny. Document this in code comments where the staff-invite is implemented.

---

## 3. Authentication, authorization and security (non-negotiable)

### 3.1 Server-side gate
- Implement one dependency `require_admin` and attach it at **router level**: `APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])`. No admin route may be declared outside that router.
- On every request `require_admin` must, from the database (never from claims cached in the cookie/token):
  1. Resolve the session → user. Missing/expired/invalid → **401** `unauthenticated`.
  2. User row `is_active = true` and (`locked_until IS NULL` or `locked_until <= now()`). Otherwise → 401.
  3. `user_roles` contains `admin` for that user. Otherwise → **403** `forbidden`.
  4. Return the user object for use in handlers (actor for audit).
- Every handler additionally validates its own business preconditions (§8). Hiding a button in the UI is never authorization.

### 3.2 Admin pages and assets
- Admin pages: `GET /admin` serves `index.html` (Overview); `/admin/drivers`, `/admin/users`, `/admin/merchants`, `/admin/warehouses`, `/admin/orders`, and `/admin/activity` each serve their matching HTML file. Shared assets use `/admin/assets/*`.
- Serve pages and assets only through the admin gate. Anonymous requests redirect to `302 /login?next=<path>`. A signed-in user without the admin role receives `403` with a plain `Access denied` response. Unknown `/admin/*` paths return `404`.
- Every page, asset, and `/api/admin/*` response receives `Cache-Control: no-store`, `X-Robots-Tag: noindex`, `Referrer-Policy: no-referrer`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, and the admin Content-Security-Policy.

### 3.3 Client-side gate
- On load the shell calls `GET /api/admin/me`. It renders **nothing else** (no nav, no page, no other API calls) until that returns 200.
  - 401 → `location = /login?next=<current path>`.
  - 403 → "Access denied" view.
- Every API call: same-origin, `credentials: 'same-origin'`. Global handler: 401 → redirect to login; 403 → toast "You don't have permission for this action."; 429 → "Too many requests, wait a moment."; ≥500 or network → fixed generic message. Never print server `detail` for 5xx; show server `detail` text only for the known 4xx codes in §5.4.

### 3.4 CSRF
Session cookie must be `HttpOnly; Secure; SameSite=Lax` (Strict if login flow allows). All non-GET admin requests must: send `Content-Type: application/json`, and pass an `Origin` (fallback `Referer`) check against `APP_BASE_URL`; mismatch → 403 `csrf`. Reject non-JSON content types on mutations with 415.

### 3.5 Step-up confirmation for admin-role changes
Granting or revoking the `admin` role (and inviting a new user as `admin`) requires `current_password` in the request body, verified against the acting admin's own hash with the existing verification function. Missing → 403 `reauth_required`. Wrong → 403 `reauth_failed`. Failures here must **not** increment `failed_login_count`; rely on the rate limit below.

### 3.6 Rate limits (slowapi, keyed on authenticated user id, not IP)
- Admin GET endpoints: 120/min/user. Mutations: 30/min/user. Invite, resend-invite, send-reset: 10/hour/user. Exceeded → 429 `rate_limited`.
- Client IP for the audit log uses the same trusted-proxy helper as the public tracking endpoint (do not read raw `X-Forwarded-For`).

### 3.7 Data handling
- **Internal UUIDs are never shown.** No UUID appears as visible text anywhere in the UI (tables, drawers, toasts, copy buttons, search hints). Orders are identified in the admin API and UI **only** by `tracking_token` (globally unique) and `merchant_order_ref`; `orders.id` must not appear in any admin response, URL or audit record. UUIDs of other entities may exist only as API path/query values and internal link targets.
- Never return `password_hash`, `token_hash`, `failed_login_count`, refresh/reset token values. Expose lock state only as `is_locked` and `locked_until`.
- Parameterized queries / ORM only. Pydantic models with `extra = "forbid"`, max lengths, and strict enums on every request body and query param. Unknown sort column or direction → 422 (whitelist, never interpolate).
- Responses return only listed fields (explicit response models).
- Emails/phones in logs: do not log request bodies; log action name, actor id, target id.

### 3.8 Transactions and audit
- Every mutation runs in one DB transaction that includes its `admin_audit_log` insert. No change without an audit row; no audit row without the change.
- Emails are sent **after** commit, best-effort; SMTP failure never rolls back or fails the request (return `invite_sent: false` where relevant, and log the error).

### 3.9 Bootstrapping the first admin
No API creates the first admin. Provide `python -m app.scripts.create_admin --email EMAIL --name "Full Name"` that creates/updates the user, grants `admin`, and prints a one-time password-set link (reset-token flow). Refuse to run if `ENV=production` and `--allow-prod` is not passed.

### 3.10 Invariants enforced server-side
- An admin cannot deactivate themselves, revoke their own `admin` role, or revoke their own sessions via the console (`self_action_blocked`).
- The system must always have ≥ 1 active admin. Before any action that could remove an active admin (deactivate, revoke admin role), lock the active-admin rows `SELECT … FOR UPDATE` in the same transaction, count, and refuse with 409 `last_admin` if the result would be zero. (Prevents the race where two admins remove each other.)
- Deactivating a user: set `is_active=false`, set `revoked_at=now()` on all their unrevoked `refresh_tokens`. Because §3.1 checks `is_active` on every request, existing access tokens die immediately.

---

## 4. Data model

### 4.1 Existing tables used
`users`, `user_roles`, `refresh_tokens`, `password_reset_tokens`, `merchants`, `merchant_members`, `warehouses`, `warehouse_staff`, `vehicles` (read-only, to show a driver's vehicle), `drivers`, `orders`, `routes`, `route_stops`, `order_events`. Do not alter existing columns.

Facts the implementation depends on:
- `users.password_hash` is `NOT NULL`. Invited users get the hash of a random 32-byte secret nobody knows (unusable); they set a real password through the reset link.
- `drivers.status` ∈ `pending | offline | available | on_route | rejected`. "Active driver" = `offline | available | on_route`.
- Open order = `status IN ('pending','assigned','out_for_delivery','attempt_failed')`. Active route = `status IN ('planned','in_progress')`.
- Warehouse coordinates are stored in `location geography(Point,4326)` as (lon, lat). API exposes `latitude`/`longitude` via `ST_Y` / `ST_X`, and writes with `ST_SetSRID(ST_MakePoint(lon, lat),4326)::geography`.

### 4.2 Migration (idempotent SQL; run on Neon)
Put in `db/migrations/2026_10_admin.sql` (or the project's migration tool if one exists):

```sql
CREATE TABLE IF NOT EXISTS admin_audit_log (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actor_user_id  uuid        REFERENCES users(id) ON DELETE SET NULL,
    action         text        NOT NULL,
    target_type    text        NOT NULL CHECK (target_type IN ('user','driver','merchant','warehouse')),
    target_id      uuid        NOT NULL,
    target_label   text        NOT NULL,          -- snapshot, e.g. driver name, so the log stays readable
    details        jsonb       NOT NULL DEFAULT '{}'::jsonb,   -- never secrets/tokens/passwords
    ip             inet,
    occurred_at    timestamptz NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION admin_audit_log_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'admin_audit_log is append-only'; END $$;

DROP TRIGGER IF EXISTS trg_admin_audit_log_immutable ON admin_audit_log;
CREATE TRIGGER trg_admin_audit_log_immutable
  BEFORE UPDATE OR DELETE ON admin_audit_log
  FOR EACH ROW EXECUTE FUNCTION admin_audit_log_immutable();

CREATE INDEX IF NOT EXISTS idx_audit_occurred ON admin_audit_log (occurred_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_audit_actor    ON admin_audit_log (actor_user_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_target   ON admin_audit_log (target_type, target_id);

CREATE UNIQUE INDEX IF NOT EXISTS uq_merchants_name_ci ON merchants (lower(btrim(name)));
CREATE INDEX IF NOT EXISTS idx_orders_created        ON orders (created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_order_events_occurred ON order_events (occurred_at, to_status);
CREATE INDEX IF NOT EXISTS idx_drivers_status        ON drivers (status);
```

Audit `action` values (exhaustive): `driver.verify`, `driver.reject`, `user.invite`, `user.deactivate`, `user.reactivate`, `user.unlock`, `user.revoke_sessions`, `user.send_reset`, `user.resend_invite`, `user.role_grant`, `user.role_revoke`, `merchant.create`, `merchant.update`, `merchant.deactivate`, `merchant.reactivate`, `warehouse.create`, `warehouse.update`, `warehouse.deactivate`, `warehouse.reactivate`, `warehouse.staff_add`, `warehouse.staff_remove`. `details` holds: reject `reason`; update actions `{before:{…}, after:{…}}` of changed fields only; role actions `{role}`; invite `{role, warehouse_ids}`; bulk actions write **one audit row per item**.

---

## 5. API conventions

### 5.1 Lists
Offset lists (drivers, users, merchants, warehouses): `page` (≥1, default 1), `page_size` (default 25, max 100), `sort`, `dir` (`asc|desc`), `q`, filters. Response: `{ items, total, page, page_size, counts }` where `counts` are segment totals ignoring `q` (for tab badges).
Cursor lists (orders, activity — large, append-heavy): `limit` (default 25, max 100), `cursor` (opaque base64 of `(created_at|occurred_at, id)`), response `{ items, next_cursor }` (null at end), no total. Fixed order newest first.
`q` = case-insensitive substring (`ILIKE`, escape `%` `_`), trimmed, max 100 chars, ignored if < 2 chars.

### 5.2 IDs and times
UUIDs as strings; malformed UUID path/query → 422. Timestamps ISO-8601 UTC with `Z`. Frontend formats in the browser's local time.

### 5.3 Idempotency
State actions are idempotent when already in the target state **and** the action is a no-op-safe one (`reactivate` on active user → 200 with unchanged body, no audit row). Actions with a precondition on prior state (`verify`, `reject`) return 409 `invalid_state` with `{current}` if the precondition fails. Implement with `UPDATE … WHERE <precondition> RETURNING`; zero rows → re-read to decide 404 vs 409.

### 5.4 Error body and codes
`{ "detail": "<human message>", "code": "<machine code>" }`; 422 adds `"errors":[{"field","message"}]`.
| HTTP | code | meaning |
|---|---|---|
| 401 | `unauthenticated` | no/invalid session or inactive/locked user |
| 403 | `forbidden` | not admin |
| 403 | `csrf` | origin check failed |
| 403 | `reauth_required` / `reauth_failed` | step-up password (§3.5) |
| 404 | `not_found` | unknown id (also for a malformed-but-valid-UUID of wrong entity) |
| 409 | `invalid_state` | wrong current state (include `current`) |
| 409 | `email_exists` | staff invite to an existing email (include `user_id`) |
| 409 | `owner_inactive` | merchant owner account is deactivated |
| 409 | `merchant_name_exists`, `warehouse_code_exists` | uniqueness |
| 409 | `last_admin`, `self_action_blocked` | §3.10 |
| 409 | `driver_has_active_route` | cannot deactivate a driver on an active route |
| 409 | `warehouse_has_open_orders`, `warehouse_has_active_routes` | cannot deactivate |
| 409 | `role_not_assignable`, `user_not_staff` | role/warehouse rules |
| 415 | `unsupported_media_type` | non-JSON mutation |
| 422 | `validation_error` | body/query invalid |
| 429 | `rate_limited` | §3.6 |

---

## 6. Pages (what each page contains)

### 6.0 Shell and shared UI
- Layout: fixed left sidebar and topbar. Each sidebar item is a normal link to its own page: `/admin`, `/admin/drivers`, `/admin/users`, `/admin/merchants`, `/admin/warehouses`, `/admin/orders`, and `/admin/activity`. Each request loads that page's HTML; the shared shell marks the active item from `body[data-page]`.
- Drawers are deep-linkable on the same page with `?id=<uuid>` (Orders uses the tracking code). Table and filter state stays in the query string, for example `/admin/drivers?segment=pending&q=ravi&page=2`; reload restores it. Search is debounced 300 ms; in-flight requests are aborted when a newer one starts; stale responses are ignored.
- Shared components (build once, reuse): `DataTable` (server-driven sort/page/search/filters, optional row selection + bulk bar), `SegmentTabs` (with count badges), `StatCard`, `StatusBadge`, `Drawer`, `ConfirmDialog` (optional reason textarea / password field), `Toast`, `EmptyState`, `ErrorState` (message + Retry), `Skeleton`.
- Every page/panel has four states: loading (skeleton), empty (explains why + the next action, shown instead of the table), error (with Retry), populated. The table and empty state are never shown together.
- Primary action per page sits in the page header (e.g. "Invite staff", "Add merchant", "Add warehouse"). Row actions in a kebab menu + the drawer. Bulk bar appears when ≥ 1 row selected.
- Destructive/consequential actions use `ConfirmDialog`: deactivate user/merchant/warehouse, reject driver, remove warehouse staff, revoke sessions, grant/revoke admin (with password field). Non-destructive actions (verify, unlock, reactivate) run directly then show a toast.
- Action buttons render only when valid for the current state (e.g. Unlock only if `is_locked`), but the server still enforces everything.
- Accessibility: keyboard reachable, visible focus ring, dialogs/drawers trap focus and close on Esc, status never conveyed by colour alone (badge has text), `aria-live` region for toasts, table headers are real `<th scope>`.
- Design tokens: green `#0E5A45` / dark `#0A3D30`, yellow `#F2C230`, blue `#1B4DB1`, bg `#F5F6F1`, white cards, 12px radii. No CSS framework.

### 6.1 Overview — `/admin`
Purpose: "Is anything wrong, and what do I need to do now?" Data: `GET /api/admin/overview` (one call; refresh button + auto-refresh every 60 s while the tab is visible).
1. **KPI row (5 StatCards):** Orders today · Open orders · Delivered today · Failed attempts today · Delivery success rate (7 days; "—" when no data). Each card links to Orders with the matching filter.
2. **Needs attention (4 lists, each with count and top-5 rows, "View all" link, hidden/replaced by a "Nothing pending" empty state at zero):**
   - Pending drivers — oldest first; inline **Verify** button per row; link → Drivers (segment pending).
   - Locked accounts — name, locked until; inline **Unlock**.
   - Stale pending orders — `pending` for more than `STALE_PENDING_HOURS` (default 4); merchant order ref, merchant, age.
   - Failed-attempt orders — `attempt_failed`; ref, merchant, age.
   - Within each queue, show the age using the existing relevant timestamp and sort oldest-first. Label the timestamp basis in the detail view where it is not obvious (for example, order created vs. last updated).
3. **Open orders by status** — horizontal segmented bar/funnel: pending → assigned → out_for_delivery, plus attempt_failed (separate, warning tone). Counts + percentages.
4. **Driver supply** — bar/stacked counts of `available`, `on_route`, `offline`, plus pending and rejected as text.
5. **Warehouses** — table (active warehouses, top 8 by open orders): code, name, open orders, active routes; row → Warehouses drawer.
6. **Users by role** — compact list with counts (links to Users filtered by role).
7. **Recent admin activity** — last 8 audit entries (time, actor, sentence like "Priya verified driver Ravi K."); link → Activity.

### 6.2 Drivers — `/admin/drivers`
Purpose: approve sign-ups and see the roster. Data: `GET /api/admin/drivers`, `GET /api/admin/drivers/{id}`.
- Segment tabs with counts: **Pending** (default) · Active · Rejected · All.
- Search (name, email, phone, vehicle registration). Sort: registered (default oldest first for Pending, newest first otherwise), name, last login, status.
- Columns: checkbox, Driver (name + email/phone sub-line), Status badge, Vehicle (type + registration, or "No vehicle"), Registered, Last login, Account (Active/Blocked), row menu.
- Keep driver operational status (`pending`, `offline`, `available`, `on_route`, `rejected`) visually separate from account access (`Active` / `Blocked`); a blocked account is not an operational driver status.
- Row actions: Pending → Verify / Reject. Rejected → Verify (reconsider). Active → Block / Unblock (calls users deactivate/reactivate).
- Bulk (selection on Pending/Rejected): **Verify selected**, **Reject selected** (shared reason). Result toast: "N verified, M failed" with failure list.
- Drawer: identity (name, email, phone), status + account state, vehicle details (type, registration, capacity), registered/last login, stats (completed deliveries, failed stops), current route (status, started, stops done/total) or "No active route", last 5 routes (status, date, stops). Actions: Verify / Reject / Block / Unblock as applicable; "Open user" link.
- Empty states: Pending → "No drivers waiting for approval." Search with no match → "No drivers match '…'" + Clear search.
- Reject dialog: optional reason (max 200 chars). Reason is audited and included in the rejection email.

### 6.3 Users — `/admin/users`
Purpose: find any account, manage staff and access. Data: `GET /api/admin/users`, `GET /api/admin/users/{id}`, user action endpoints.
- Header action: **Invite staff**. Segment tabs with counts: All · Active · Inactive · Locked. Filter: role (any / customer / merchant / dispatcher / driver / fleet_manager / admin). Search (name, email, phone).
- Columns: User (name + email/phone), Roles (chips), Status badge (Active / Inactive / Locked / Invited = never logged in with pending invite), Last login, Created, row menu.
- Drawer sections: Profile (read-only); Roles (chips; **Add role** for dispatcher/fleet_manager/admin; remove on those three, with step-up password when role is admin); Access (status, locked-until, active sessions count) with actions **Deactivate / Reactivate**, **Unlock**, **Sign out everywhere**, **Send password reset**, **Resend invite** (only for invited, never-logged-in users); Belongs to (read-only: warehouses and merchants, with links); Driver status (if driver, link to Drivers drawer).
- In Users and Drivers, show account access and driver operational status as separate labeled values whenever both apply.
- **Invite staff dialog:** Full name, Email, Role (dispatcher / fleet_manager / admin), Warehouses (multi-select of active warehouses; shown only for dispatcher/fleet_manager; hint "No warehouse = no access until assigned"), Your password (only when role = admin). On success toast: "Invite sent to x" or, if `invite_sent=false`, a warning "Account created but email failed — use Resend invite."
- Admin cannot edit another user's name/email/phone (no impersonation surface).
- Empty: "No users match these filters." + Reset filters.

### 6.4 Merchants — `/admin/merchants`
Purpose: onboard and manage merchant companies. Data: `GET /api/admin/merchants`, `GET …/{id}`, create/update/deactivate.
- Header action: **Add merchant**. Tabs: All · Active · Inactive. Search (name, contact email). Sort: name, created, orders.
- Columns: Merchant (name + contact email), Status badge, Members (count), Orders (total), Orders (30 days), Created, row menu.
- Drawer: Contact (edit inline: name, contact email, contact phone), Status (Deactivate/Reactivate), Members (**read-only** list: name, email, account active?), Orders by status (counts), Recent orders (last 10, row → Orders drawer).
- **Add merchant dialog:** Merchant name, Contact email (optional), Contact phone (optional, E.164), Owner full name, Owner email. Helper text: "The owner receives an email to set their password. If the email already has an account, it gets merchant access." Success shows whether an invite was sent.
- Deactivate confirm text: "New orders from this merchant will be rejected. Existing open orders continue to delivery." Empty state: "No merchants yet. Add your first merchant."

### 6.5 Warehouses — `/admin/warehouses`
Purpose: define the physical network. Data: `GET /api/admin/warehouses`, `GET …/{id}`, create/update/deactivate, staff add/remove.
- Header action: **Add warehouse**. Tabs: All · Active · Inactive. Search (code, name, address). Sort: code, name, open orders.
- Columns: Code (monospace), Name, Address, Status, Staff (count), Open orders, Active routes, row menu.
- Drawer: Details (edit name, address, coordinates; **code is read-only**), "Open in OpenStreetMap" link (`https://www.openstreetmap.org/?mlat=…&mlon=…#map=15/…`; no embedded map), Status (Deactivate/Reactivate; if blocked show the reason returned by the API), Staff (list of users with role chip; **Add staff** = searchable picker limited to active users holding dispatcher or fleet_manager; Remove with confirm), Orders by status, Active routes (driver, status, stops done/total).
- When deactivation is blocked, show the specific API reason and available count for open orders or active routes (or both), so the admin knows what must clear before retrying.
- **Add warehouse dialog:** Code (A–Z, 0–9, `-`, 2–12 chars; auto-uppercased; unique), Name, Address, Latitude, Longitude (validated: −90…90, −180…180; helper "Right-click a point in Google/OpenStreetMap maps to copy coordinates").
- Empty state: "No warehouses yet. Add the first one so staff and orders can be assigned."

### 6.6 Orders — `/admin/orders` (read-only diagnostic ledger)
Purpose: start from a ticket or an exception, find the order, and see exactly what the system did to it. Admin investigates; interventions (reassign, cancel, re-route) belong to the dispatcher panel and are **not** built here. Data: `GET /api/admin/orders`, `GET /api/admin/orders/counts`, `GET /api/admin/orders/{tracking_token}`. The tracking token is the page's order identifier; never use or expose `orders.id`.

**Filter bar**
- Search box: tracking code (exact, normalized) · merchant order ref (substring) · recipient name (substring) · recipient phone (exact, E.164).
- Status multi-select chips with live counts (counts respect the other filters). Exactly our 7 states, labelled: Pending, Assigned, Out for delivery, Delivered, Failed attempt, Returned, Cancelled.
- Merchant select, Warehouse select (origin warehouse).
- Created between: date + hour:minute pickers (browser local time, sent as UTC ISO).
- "Overdue only" toggle: open orders whose `window_latest` has passed.
- Reset filters. State lives in the page query string (§6.0).

**Grid** (dense rows, cursor "Load more" — no row virtualization; page size 25/50/100)
| Column | Content |
|---|---|
| Order | merchant order ref (monospace) + copy button; sub-line: tracking code (monospace) + copy button |
| Merchant | name |
| Recipient | name; small "Guest order" tag when `customer_id` is null |
| Warehouse | code |
| Status | badge |
| Delivery window | open orders with a window: "Due in 2h 10m" (neutral) / "Overdue 1h 05m" (danger); no window: "No window"; closed orders: the window range. Computed in the browser from `window_latest`, refreshed every 60 s (no per-row timers) |
| Driver | latest assigned driver name (link → Drivers drawer) or "—" |
| Created | relative time, absolute on hover |
Row click or an **Inspect** button opens the drawer. No bulk actions, no row action menu.

**Inspection drawer (wide)**
A. *Header* — merchant ref, tracking code (each with copy), status badge, created/updated, link "Open customer tracking page" (`/track?code=…`).
B. *Status timeline* — from `order_events`, **newest on top**, oldest ("Order created") at the bottom. Each entry: status label, time to the second (full timestamp on hover), actor name or "System", and the elapsed time since the previous event ("+12 min"). The actor identifies the recorded human/system attribution; do not infer a more specific source or cause that is not present in the response. Failed attempt and cancelled entries in warning/neutral tone. For open orders, a line "In current status for 3 h 20 m".
C. *Delivery attempts* — **every** route stop the order has had, newest first (an order can fail and be re-assigned): attempt number based on display order (do not show the internal route UUID), driver (link), vehicle (type + registration), stop sequence, stop status, failure reason, planned arrival, arrived, completed. Under each: "Route load: 38.2 / 60 kg · 0.9 / 2.0 m³" and a warning chip "Parcel exceeds vehicle capacity" when this single parcel is heavier or larger than the vehicle allows. Empty: "Not assigned to a route yet."
D. *Location* — delivery address text, coordinates, "Open in OpenStreetMap" link, origin warehouse (code, name, link), straight-line distance warehouse → drop-off ("6.4 km"). No embedded map in v1.
E. *Parcel and parties* — weight, volume, delivery window (earliest/latest), recipient name and phone, merchant (link to drawer), customer (name or "Guest order").

At the top of the drawer, keep a compact, copyable case summary of merchant reference and tracking code, with current status, warehouse, latest driver (when available), and latest event time. These are existing order/detail fields; do not expose internal UUIDs. Keep delivery-window display consistent with the configured platform `APP_TIMEZONE` and show the full ISO timestamp on hover; do not assume a warehouse-specific timezone.

**Deliberately not on this page (the data does not exist; do not fake it):** prices, GMV, delivery fees, COD/payment data, courier speed/battery/telemetry, GPS trail, proof-of-delivery photo/signature or drop-off geofence, hub-scan/solver events, contractual SLA countdowns, delivery zones/polygons, parcel dimensions (only volume is stored). Empty states: "No orders match these filters." / platform empty: "No orders yet."

### 6.7 Activity — `/admin/activity` (read-only)
Purpose: who did what. Data: `GET /api/admin/activity`.
- Filters: Action (grouped select), Actor (select of admins that appear in the log), Target type, Date range. Cursor "Load more".
- Columns: Time, Actor, Action (human sentence, e.g. "Verified driver"), Target (label; link to the drawer if the entity still exists), Details (collapsed one-liner; expand shows key/value pairs, e.g. reason, before → after).
- Empty: "No admin activity recorded yet."

---

## 7. API reference

All paths prefixed `/api/admin`, all behind `require_admin`, all JSON. "Audit" = writes `admin_audit_log` in the same transaction.

### 7.1 Meta and overview
| Method & path | Notes |
|---|---|
| `GET /me` | `{id, full_name, email, roles[], app_timezone}` |
| `GET /overview` | Shape below |

`GET /overview` response:
```json
{
  "generated_at": "…Z",
  "kpis": {"orders_today": 0, "open_orders": 0, "delivered_today": 0, "failed_attempts_today": 0, "delivery_success_rate_7d": null},
  "needs_attention": {
    "pending_drivers":   {"count": 0, "items": [{"user_id","full_name","created_at"}]},
    "locked_users":      {"count": 0, "items": [{"id","full_name","locked_until"}]},
    "stale_pending_orders": {"count": 0, "items": [{"tracking_token","merchant_order_ref","merchant_name","created_at"}]},
    "failed_attempt_orders": {"count": 0, "items": [{"tracking_token","merchant_order_ref","merchant_name","updated_at"}]}
  },
  "open_orders_by_status": {"pending":0,"assigned":0,"out_for_delivery":0,"attempt_failed":0},
  "drivers_by_status": {"pending":0,"offline":0,"available":0,"on_route":0,"rejected":0},
  "users_by_role": {"customer":0,"merchant":0,"dispatcher":0,"driver":0,"fleet_manager":0,"admin":0},
  "warehouses": [{"id","code","name","open_orders","active_routes"}],
  "recent_activity": [{"id","occurred_at","actor_name","action","target_label"}]
}
```
Definitions: `orders_today` = orders created since local midnight (`APP_TIMEZONE`); `delivered_today` / `failed_attempts_today` = `order_events` with `to_status` = delivered / attempt_failed since local midnight; `delivery_success_rate_7d` = delivered events ÷ (delivered + attempt_failed events) over 7 days, `null` if denominator is 0; lists are capped at 5, oldest first (stale/pending) or newest (failed); `warehouses` = active only, top 8 by open orders.

### 7.2 Drivers
| Method & path | Params / body | Result / rules |
|---|---|---|
| `GET /drivers` | `segment=pending\|active\|rejected\|all` (default pending), `q`, `sort=created_at\|full_name\|last_login_at\|status`, `dir`, `page`, `page_size` | items `{user_id, full_name, email, phone, status, account_active, vehicle:{id,type,registration_number}\|null, created_at, last_login_at}`; `counts:{pending,active,rejected,all}`. `q` also matches vehicle registration. Pending defaults to `created_at asc`; other segments default to `created_at desc` |
| `GET /drivers/{user_id}` | | item fields + `stats:{completed_deliveries, failed_stops}`, `active_route:{id,status,started_at,stops_total,stops_done}\|null`, `recent_routes[≤5]:{id,status,created_at,stops_total,stops_done}`, `vehicle` incl. `max_weight_kg, max_volume_m3`. 404 if no driver row |
| `POST /drivers/{user_id}/verify` | — | `pending\|rejected → offline`. Else 409 `invalid_state`. Audit `driver.verify`. Email "approved" |
| `POST /drivers/{user_id}/reject` | `{reason?: ≤200}` | `pending → rejected`. Else 409. Audit `driver.reject` (reason in details). Email "rejected" (+reason) |
| `POST /drivers/bulk` | `{action:"verify"\|"reject", user_ids:[≤50 unique], reason?}` | `{results:[{user_id, ok, code?}]}`; per-item transaction + audit; never all-or-nothing |

Blocking/unblocking a driver uses the Users endpoints (§7.3).

### 7.3 Users
| Method & path | Params / body | Rules |
|---|---|---|
| `GET /users` | `q`, `role`, `status=all\|active\|inactive\|locked`, `sort=created_at\|full_name\|last_login_at`, `dir`, page params | items `{id, full_name, email, phone, roles[], is_active, is_locked, locked_until, invited (bool), last_login_at, created_at}`; `counts:{all,active,inactive,locked}`. `invited` = never logged in and has an unused unexpired reset token |
| `GET /users/{id}` | | item + `roles:[{role, granted_at, granted_by_name}]`, `warehouses:[{id,code,name}]`, `merchants:[{id,name}]`, `driver_status\|null`, `active_sessions` (unrevoked unexpired refresh tokens) |
| `POST /users` | `{full_name, email, role:"dispatcher"\|"fleet_manager"\|"admin", warehouse_ids?:[uuid], current_password? (required iff role=admin)}` | Email exists → 409 `email_exists`. `warehouse_ids` only for dispatcher/fleet_manager, each must be an active warehouse. Create user (unusable password hash) + role (`granted_by`=actor) + `warehouse_staff` rows + 72 h reset token; email invite after commit. 201 `{user, invite_sent}`. Audit `user.invite` |
| `POST /users/{id}/deactivate` | — | §3.10 rules; blocks 409 `driver_has_active_route` if user is a driver with an active route; if driver is `available` set `drivers.status='offline'`; revoke refresh tokens. Audit |
| `POST /users/{id}/reactivate` | — | `is_active=true`. Audit (skip audit if already active) |
| `POST /users/{id}/unlock` | — | `failed_login_count=0, locked_until=NULL`. Audit |
| `POST /users/{id}/revoke-sessions` | — | Revoke all refresh tokens. Not on self. Audit |
| `POST /users/{id}/send-reset` | — | Create standard reset token + email (existing reset email). Active users only. Audit. Rate-limited (§3.6) |
| `POST /users/{id}/resend-invite` | — | Only if `invited`; mark previous unused tokens `used_at=now()`, issue new 72 h token, email. Audit |
| `POST /users/{id}/roles` | `{role, current_password? (iff admin)}` | role ∈ dispatcher/fleet_manager/admin else 409 `role_not_assignable`; idempotent if already held. Audit `user.role_grant` |
| `POST /users/{id}/roles/{role}/revoke` | `{current_password? (iff admin)}` | Same role set; §3.10 for admin; if the last of dispatcher/fleet_manager is revoked, also delete that user's `warehouse_staff` rows. Audit `user.role_revoke` |

### 7.4 Merchants
| Method & path | Params / body | Rules |
|---|---|---|
| `GET /merchants` | `q`, `status=all\|active\|inactive`, `sort=name\|created_at\|orders_total`, `dir`, page params | items `{id, name, contact_email, contact_phone, is_active, member_count, orders_total, orders_30d, created_at}`; `counts:{all,active,inactive}` |
| `GET /merchants/{id}` | | item + `members:[{user_id, full_name, email, account_active}]` (read-only), `orders_by_status{}`, `recent_orders[≤10]:{tracking_token, merchant_order_ref, status, created_at}` |
| `POST /merchants` | `{name, contact_email?, contact_phone?, owner_email, owner_full_name}` | One transaction: insert merchant (409 `merchant_name_exists` via `uq_merchants_name_ci`); find user by `owner_email`: if missing create (unusable password); if existing and inactive → 409 `owner_inactive`; ensure `merchant` role (`granted_by`=actor); insert `merchant_members`; if user was created, issue 72 h invite token and email after commit. 201 `{merchant, owner:{user_id, created}, invite_sent}`. Audit `merchant.create` |
| `PATCH /merchants/{id}` | `{name?, contact_email?, contact_phone?}` (≥1 field) | Audit `merchant.update` with before/after |
| `POST /merchants/{id}/deactivate` / `/reactivate` | — | Always allowed. Audit. **Order-intake code must reject orders for inactive merchants** (add this check where orders are created, or leave a clearly marked TODO + failing test stub if that endpoint doesn't exist yet) |

### 7.5 Warehouses
| Method & path | Params / body | Rules |
|---|---|---|
| `GET /warehouses` | `q`, `status`, `sort=code\|name\|open_orders\|created_at`, `dir`, page params | items `{id, code, name, address, latitude, longitude, is_active, staff_count, open_orders, active_routes, created_at}`; `counts:{all,active,inactive}` |
| `GET /warehouses/{id}` | | warehouse item (including `active_routes` count) + `staff:[{user_id, full_name, email, roles}]`, `orders_by_status{}`, `active_route_list:[{id, driver_name, status, stops_total, stops_done}]` |
| `POST /warehouses` | `{code, name, address, latitude, longitude}` | `code` trimmed+uppercased, `^[A-Z0-9-]{2,12}$`, unique (409 `warehouse_code_exists`); name ≤120; address ≤300. Audit |
| `PATCH /warehouses/{id}` | `{name?, address?, latitude?+longitude?}` | `code` immutable (422 if sent); lat/lon must come together. Audit with before/after |
| `POST /warehouses/{id}/deactivate` | — | 409 `warehouse_has_open_orders` / `warehouse_has_active_routes`. Audit. **Order-intake must reject orders to inactive warehouses** (same note as merchants) |
| `POST /warehouses/{id}/reactivate` | — | Audit |
| `POST /warehouses/{id}/staff` | `{user_id}` | User must be active and hold dispatcher or fleet_manager else 409 `user_not_staff`; idempotent. Audit `warehouse.staff_add` |
| `DELETE /warehouses/{id}/staff/{user_id}` | — | Idempotent. Audit `warehouse.staff_remove` |

### 7.6 Orders (read-only)
| Method & path | Params | Result |
|---|---|---|
| `GET /orders` | `q`, `status` (repeatable), `merchant_id`, `warehouse_id`, `from`, `to` (ISO datetimes), `overdue` (bool), `limit`, `cursor` | items `{merchant_order_ref, tracking_token, merchant:{id,name}, warehouse:{id,code}, status, recipient_name, is_guest, window_earliest, window_latest, driver:{id,full_name}\|null, created_at}`; `next_cursor`. `driver` = driver of the order's most recent route stop (use a `LATERAL … ORDER BY created_at DESC LIMIT 1` on `route_stops`, which has `idx_route_stops_order`). `q` rules, OR-combined: matches `^[A-Z]{10}$` after `strip().upper()` → `tracking_token` exact; matches `^\+[1-9][0-9]{7,14}$` → `recipient_phone` exact; always also `ILIKE` on `merchant_order_ref` and `recipient_name`. `overdue=true` → `window_latest < now()` AND status in the open set |
| `GET /orders/counts` | same filters except `status`, `limit`, `cursor` | `{pending, assigned, out_for_delivery, delivered, attempt_failed, returned, cancelled}` |
| `GET /orders/{tracking_token}` | | item + `recipient_phone`, `delivery_address`, `latitude`, `longitude`, `weight_kg`, `volume_m3`, `updated_at`, `customer:{id,full_name}\|null`, `warehouse:{id,code,name,latitude,longitude}`, `distance_km_straight` (`ST_Distance` between warehouse and delivery geography ÷ 1000, 1 decimal), `events:[{from_status,to_status,occurred_at,seconds_since_previous,actor:{id,full_name}\|null}]` ordered newest first, `stops:[{stop_id, route_id, route_status, driver:{id,full_name}, vehicle:{type,registration_number,max_weight_kg,max_volume_m3}, sequence, status, failure_reason, planned_arrival_at, arrived_at, completed_at, route_load:{weight_kg,volume_m3}, parcel_exceeds_vehicle}]` newest first. `route_load` = sum over all stops of that route. `parcel_exceeds_vehicle` = this order's weight or volume > vehicle max |

Performance note (prototype vs production): substring `ILIKE` on `merchant_order_ref` / `recipient_name` is a sequential scan, which is fine at prototype volumes. If `orders` grows past roughly 100k rows, enable `pg_trgm` (free on Neon) and add GIN trigram indexes on those two columns. Do not add them now.

### 7.7 Activity
| Method & path | Params | Result |
|---|---|---|
| `GET /activity/filters` | — | `{actions, actors:[{id,full_name}], target_types}` filter options from recorded audit rows |
| `GET /activity` | `action`, `actor_id`, `target_type`, `from`, `to`, `limit`, `cursor` | items `{id, occurred_at, actor:{id,full_name}\|null, action, target_type, target_id, target_label, details}`; `next_cursor`. Read-only; no write endpoint exists |

---

## 8. State and business rules (implement as a pure function + table, unit-tested)

| Entity | From → To | Allowed when | Side effects |
|---|---|---|---|
| Driver status | pending → offline (verify) | always | email approved |
| Driver status | rejected → offline (verify) | always | email approved |
| Driver status | pending → rejected (reject) | always | email rejected |
| Driver status | any other | never via admin | — |
| User active | true → false | not self; not last admin; no active route if driver | revoke tokens; driver `available`→`offline` |
| User active | false → true | always | — |
| User lock | locked → unlocked | always | counter reset |
| Role grant/revoke | dispatcher / fleet_manager / admin only | admin needs password; not self-revoke; not last admin | revoke last staff role → remove warehouse_staff rows |
| Merchant active | either direction | always | none (intake enforces) |
| Warehouse active | true → false | no open orders, no active routes | none |
| Warehouse code | — | immutable | — |

---

## 9. Emails (use the existing SMTP helper; plain, professional text + HTML)
1. **Staff invite** — "You've been invited to LOGIPULSE as {Role}. Set your password: {APP_BASE_URL}/reset-password?token=… (valid 72 hours, single use)."
2. **Merchant owner invite** — same mechanics, wording "Your merchant account for {Merchant} is ready."
3. **Existing user given merchant access** — notification only, no token.
4. **Password reset** — existing template.
5. **Driver approved** / **Driver rejected** (+ reason if provided).
Never include passwords. Tokens: `secrets.token_urlsafe(32)`, stored hashed (existing scheme), single-use.
Small UI change on the existing `/reset-password` page: if URL has `invite=1`, heading reads "Set your password" instead of "Reset your password" (append `&invite=1` to invite links).

---

## 10. Frontend technical requirements
- Plain HTML/CSS/JS, ES modules, no build step or CSS framework. No paid or unpinned third-party code.
- Structure: `frontend/shared/{css,js}/`; `frontend/public/{home,login,register,reset-password,track}/{index.html,css/,js/}`; `frontend/core-api/admin/{index.html,drivers.html,users.html,merchants.html,warehouses.html,orders.html,activity.html,css/{tokens.css,admin.css},js/{api.js,shell.js,main.js,pages/}}`.
- Each admin HTML document is minimal and sets `body[data-page]`; it loads `/admin/assets/js/main.js`. `shell.js` bootstraps `/api/admin/me` and creates the shared sidebar/topbar. Each sidebar link performs a normal page load. `main.js` mounts the page module and reads `id` and table state from `location.search`.
- All API data is inserted with `textContent` / DOM APIs. `innerHTML` only for static, hard-coded markup. Zero hard-coded data. Mutations disable while in flight and show progress; double-submit impossible.
- Data-heavy pages may show a subtle "Last refreshed" time based on the browser's most recent successful fetch. This is UI fetch time only and must not be presented as proof that upstream data is fresh.
- On refresh failure, preserve last successfully rendered data only if clearly marked stale and the error/retry state remains visible; never silently present old data as current.

---

## 11. Seed, test and QA

### 11.1 Scripts
- `create_admin` (§3.9).
- `python -m app.scripts.seed_demo_data [--wipe]` — **dev only**, refuses when `ENV=production`. Creates clearly marked demo rows (emails `@demo.local`, names prefixed `[Demo]`): 2 warehouses, 3 merchants (one inactive), staff users, 8 drivers across all statuses (some with vehicles), 1 locked user, 1 invited user, ~60 orders across all statuses with consistent `order_events`, 3 routes with stops, a few audit rows. `--wipe` removes only the marked rows. Purpose: let the UI be checked by hand against realistic data.

### 11.2 Automated tests (no dependency on pre-existing data)
1. **Route enumeration test:** iterate all routes of the app whose path starts with `/api/admin` and assert each has `require_admin` in its dependencies (fails the build if someone adds an unguarded route).
2. For every admin endpoint: no cookie → 401; customer session → 403; driver session → 403; dispatcher session → 403; deactivated admin → 401; locked admin → 401.
3. All seven admin page URLs and `/admin/assets/*`: admin → 200; anonymous → 302 to login; non-admin → 403. Unknown `/admin/x` → 404.
4. CSRF: mutation with bad `Origin` → 403 `csrf`; non-JSON content type → 415.
5. Pure unit tests (no DB): state-transition table (§8), warehouse code/coordinate validation, sort/filter whitelist rejection, cursor encode/decode, `q` escaping.
Integration tests that need seeded business data are optional; if you add them, create their own rows in a transaction and roll back.

---

## 12. Definition of done
No admin page or API route is reachable without the admin role; no unaudited mutation; no hard-coded data; no secrets in responses or logs. All seven page URLs load their own HTML, preserve the shared shell with the correct active link, and have no console errors. Table and drawer state is restorable from query parameters.
