# Run and test the platform locally (macOS, Linux, Windows)

From a fresh clone to one order delivered, in about 15 minutes. You need
**Python 3.11**, **Redis** and the URL of a test database (below). No Docker.

## 1. Install Python 3.11 and Redis (once)

| | Python 3.11 | Redis |
|---|---|---|
| **macOS** | `brew install python@3.11` | `brew install redis` then `brew services start redis` |
| **Linux** (Ubuntu) | `sudo apt install python3.11 python3.11-venv` | `sudo apt install redis-server` (starts automatically) |
| **Windows** | Installer from [python.org](https://www.python.org/downloads/) (3.11.x) | [Memurai](https://www.memurai.com/get-memurai) Developer edition (a Redis-compatible Windows service), or `sudo apt install redis-server` inside WSL |

Redis must answer on `localhost:6379`.

## 2. Clone and install (once)

macOS / Linux:
```bash
git clone https://github.com/Ishpreetkaur-t/Last-Mile-Delievery.git
cd Last-Mile-Delievery
git checkout feature/india-data-pipeline
./setup_linux_mac.sh
source venv/bin/activate
cp .env.example .env
```
Windows (PowerShell):
```powershell
git clone https://github.com/Ishpreetkaur-t/Last-Mile-Delievery.git
cd Last-Mile-Delievery
git checkout feature/india-data-pipeline
.\setup_windows.ps1
.\venv\Scripts\Activate.ps1
Copy-Item .env.example .env
```
If PowerShell refuses to run the scripts: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

Every command below is the same on all three systems.

**Every new terminal needs the venv activated first** (`source venv/bin/activate`, or `.\venv\Scripts\Activate.ps1` on Windows). Otherwise you get `command not found: python`.

## 3. Edit `.env`

Change two lines:
```
DATABASE_URL=postgresql+asyncpg://<user>:<password>@<host>/lastmile_india?ssl=require
NOMINATIM_URL=https://nominatim.openstreetmap.org
```
- `DATABASE_URL`: the team's test database `lastmile_india` (ask Ajay for the URL). Never use the production database.
- The geocoder in `.env.example` (`localhost:8080`) doesn't run locally, so placing an order would fail without the change.

## 4. Load the test data (and reset it any time)

```bash
python scripts/reset_demo_db.py
```
This empties and reloads `lastmile_india` from `data/snapshot/raipur_world.ttl.gz`, then clears the rider event queue in Redis. It ends with `44/45 checks pass`; the 1 failure is a closed hub planted on purpose. It refuses any other database.
Run it again whenever you want clean data, for example after each test.

(To rebuild the snapshot from OpenStreetMap and India Post yourself, see `data/README.md`. Not needed for testing.)

## 5. Start the services

Terminal 1 (leave it running):
```bash
honcho start -f Procfile.dev core_api control_tower gateway
```
Wait for three `Application startup complete` lines (ports 8000, 8001, 8002).

In the browser always use **`http://localhost:8000`**, not `127.0.0.1`. Core API rejects form posts from any other address.

## 6. Automated checks

Terminal 2 (activate the venv first):
```bash
python scripts/smoke_test.py          # 30/30 steps passed
python -m pytest tests/data -q        # 13 passed
```

## 7. One order by hand, through every role

You follow one parcel from the customer to the doorstep, acting as a different person at each step.
The services from step 5 must be running. Use Terminal 2 for the commands.

**Before you start**, reset so the hub's riders are free (riders stay busy after every run):
```bash
python scripts/reset_demo_db.py
```

**How to use `localhost:8000/docs`:** click an endpoint → **Try it out** → fill in the fields → **Execute** → read **Server response** (code and body).
- Leave a POST's request body as it is (`{}` is fine). An empty body gives a 415 error.
- `{order_id}` means the order's long id (like `6c4ff67a-…`), not the 10-letter tracking code.
- You log in on `POST /auth/login`, and the login stays until you log in as someone else.
- Each step is done by a different person, so log in as that person first. The platform checks who may do what, and the wrong person gets 403. That check is part of the test.

All passwords are `LastMile#2026`.

### 7.1 Customer places an order (browser)
1. Open `http://localhost:8000/login` and sign in as `customer003@lastmile.example.com`.
2. Click **New request** and fill in:
   - Seller **Mahanadi Electronics**
   - Recipient name: any name. Phone `+919000077777`
   - Address `Telibandha, Raipur, Chhattisgarh`
   - Weight **1.5**, Volume **0.01**. Keep it small: a large parcel may not fit on any free rider.
3. Click **Create delivery request**.

✅ The order page opens with status *preparing* and a 10-letter **tracking code**. Write the code down.

### 7.2 Shop sends it to the hub (`/docs`, as the shop)
1. `POST /auth/login`, body `{"email": "merchant2@lastmile.example.com", "password": "LastMile#2026"}`
   ✅ `"roles": ["merchant"]`
2. `GET /api/merchant/orders` → Execute as is. It lists the shop's orders that are still `placed`.
   ✅ Find the entry whose `tracking_token` is your code, and copy its `"id"`.
3. `POST /api/merchant/orders/{order_id}/send` → paste the `id` → Execute.
   ✅ `"status": "sent"` and warehouse `RPR-MANA`: the platform picked the nearest open hub.

### 7.3 Hub confirms the parcel arrived (`/docs`, as hub staff)
1. `POST /auth/login`, body `{"email": "dispatch.rpr-mana@lastmile.example.com", "password": "LastMile#2026"}`
   ✅ `"roles": ["dispatcher"]`
2. `POST /api/hub/orders/{order_id}/receive` → the same `id` → Execute.
   ✅ `"status": "pending"`: waiting at the hub for a rider.

### 7.4 Routing gives it to a rider (Terminal 2)
```bash
python -m services.routing_worker.app.plan_pending --hub RPR-MANA --ignore-shifts --priority <code>
```
`--priority` marks your parcel urgent, so the planner fits it in first. The hub has more parcels waiting than its free riders can carry.

✅ It shows 3 routes, each with its rider's email, and why some parcels were not planned. The line that matters:
```
-> <code> is stop N for rider.rpr-mana.<vehicle>.<n>@lastmile.example.com
```
Write down that rider's email.

### 7.5 The rider sees their route (`/docs`, as that rider)
1. `POST /auth/login` with **the rider email from 7.4**, password `LastMile#2026`
   ✅ `"roles": ["driver"]`
2. `GET /api/driver/route` → Execute as is. Leave the `access_token` box empty; the login fills it.
   ✅ The rider's stops in order. Search (Cmd/Ctrl+F) for your code: it is stop N.

### 7.6 The rider delivers (Terminal 2)
There is no rider app yet, so this script plays the rider's phone. It starts the route and delivers every stop up to yours. Then it reports one failed doorstep attempt and re-sends one event, as a phone would after losing signal.
```bash
python scripts/demo_rider.py --tracking <code>
```
✅ `202` for each event, sent to the Driver Gateway.

### 7.7 The worker records the events (Terminal 2)
```bash
python -m services.routing_worker.app.terminal_events --once
```
Let it finish (a second or two per line).

✅ One line per event: parcel, stop, status change. The summary shows the deliveries, `1 attempt_failed` and `1 duplicate, ignored` (the re-sent event is recorded only once).

### 7.8 Everyone sees it delivered (browser)
- `http://localhost:8000/track?code=<code>` (no login): ✅ **Delivered**, with a time for each step.
- Admin: sign in as `seed_admin@test.internal` / `AdminPass123!` → **Orders** → open your order. ✅ The timeline shows every person who handled it.

### The same flow in one command
```bash
python -m services.simulator.app.main
```
It does 7.1–7.8 through the same APIs in about 4 minutes, and ends with `status shown: Delivered`.

Reset afterwards: `python scripts/reset_demo_db.py`.

## If something goes wrong

| Symptom | Fix |
|---|---|
| `Could not find a version… greenlet` during setup | The venv was made with the wrong Python. Delete `venv/` and install Python 3.11 |
| `Connection refused` on port 6379 | Redis isn't running (step 1) |
| Order form: "address could not be located" | `NOMINATIM_URL` (step 3), or use the exact address above |
| Order form: "CSRF check failed" | Use `localhost`, not `127.0.0.1` |
| "Access denied" in pages | Logins last 15 minutes; sign in again |
| `/docs` POST returns 415 | Click **Try it out** and keep the JSON body box (even `{}`) |
| 7.4 says `was not planned` | Reset, then redo from 7.1 with the small parcel (riders were busy, or the parcel was too big) |
| `/docs` returns 403 "… role required" | You're logged in as the previous person: run `POST /auth/login` as the person for this step |
| Ports already in use | Set `PUBLIC_BASE_URL` / `CORE_API_URL` and `DRIVER_GATEWAY_URL` in `.env` to the ports you use |
