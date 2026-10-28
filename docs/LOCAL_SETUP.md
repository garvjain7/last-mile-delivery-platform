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
git clone git@github.com:Ishpreetkaur-t/Last-Mile-Delievery.git
cd Last-Mile-Delievery
git checkout feature/india-data-pipeline
./setup_linux_mac.sh
source venv/bin/activate
pip install -r data/requirements.txt
cp .env.example .env
```
Windows (PowerShell):
```powershell
git clone https://github.com/Ishpreetkaur-t/Last-Mile-Delievery.git
cd Last-Mile-Delievery
git checkout feature/india-data-pipeline
.\setup_windows.ps1
.\venv\Scripts\Activate.ps1
pip install -r data/requirements.txt
Copy-Item .env.example .env
```
If PowerShell refuses to run the scripts: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

Every command below is the same on all three systems. Run each one in a terminal where the venv is active.

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

Terminal 2:
```bash
python scripts/smoke_test.py          # 30/30 steps passed
python -m pytest tests/data -q        # 13 passed
```

## 7. One order by hand, through every role

All test accounts use the password `LastMile#2026`, except the admin.

| # | Where | Do | You should see |
|---|---|---|---|
| 1 | Browser `localhost:8000/login` as `customer003@lastmile.example.com` | **New request** → seller *Mahanadi Electronics*, address `Telibandha, Raipur, Chhattisgarh`, any weight → Create | Order page with a 10-letter tracking code. Copy the order id from the page URL. |
| 2 | `localhost:8000/docs` | `POST /auth/login` with `{"email":"merchant2@lastmile.example.com","password":"LastMile#2026"}`, then `POST /api/merchant/orders/{order_id}/send` | `"status": "sent"`, warehouse `RPR-MANA` |
| 3 | `/docs` | Log in as `dispatch.rpr-mana@lastmile.example.com`, then `POST /api/hub/orders/{order_id}/receive` | `"status": "pending"` |
| 4 | Terminal 2 | `python -m services.routing_worker.app.plan_pending --hub RPR-MANA --ignore-shifts` | `3 routes, 101 parcels assigned`, and why the rest were not |
| 5 | `/docs` | Log in as `rider.rpr-mana.three_wheeler.2@lastmile.example.com`, then `GET /api/driver/route` | That rider's 55 stops; your order is one of them |
| 6 | Terminal 2 | `python scripts/demo_rider.py --tracking <code>` (plays the rider's phone) | `202` per event: deliveries up to your parcel, one failed attempt, one repeated event |
| 7 | Terminal 2 | `python -m services.routing_worker.app.terminal_events --once` | One line per event (parcel, stop, status change); `1 attempt_failed`, `1 duplicate, ignored` |
| 8 | Browser `localhost:8000/track?code=<code>`, and admin **Orders** (`seed_admin@test.internal` / `AdminPass123!`) | Open them | **Delivered**, with each step's time |

Steps 1–8 in one command:
```bash
python -m services.simulator.app.main
```
This takes about 4 minutes and ends with `status shown: Delivered`.

Then reset with `python scripts/reset_demo_db.py`.

## If something goes wrong

| Symptom | Fix |
|---|---|
| `Could not find a version… greenlet` during setup | The venv was made with the wrong Python. Delete `venv/` and install Python 3.11 |
| `Connection refused` on port 6379 | Redis isn't running (step 1) |
| Order form: "address could not be located" | `NOMINATIM_URL` (step 3), or use the exact address above |
| Order form: "CSRF check failed" | Use `localhost`, not `127.0.0.1` |
| "Access denied" in pages | Logins last 15 minutes; sign in again |
| `/docs` POST returns 415 | Click **Try it out** and keep the JSON body box (even `{}`) |
| Ports already in use | Set `PUBLIC_BASE_URL` / `CORE_API_URL` and `DRIVER_GATEWAY_URL` in `.env` to the ports you use |
