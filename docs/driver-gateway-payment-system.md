# Driver Gateway Payments and Earnings

This document describes the implemented driver finance flow: how delivery earnings are calculated, which PostgreSQL tables store them, how the application reads them, and how payout destinations are protected. The earnings formula is a prototype policy implemented in the Routing Worker; it is not a payment-provider quote or a transfer.

## Service and database architecture

```text
Driver App
   │ authenticated HTTP request
   ▼
Driver Gateway ── allowlisted proxy ──► Core API ── SQLAlchemy ──► PostgreSQL (Neon in hosted deployments)
                                              ▲
                                              │ same DATABASE_URL target
Routing Worker ───────────────────────────────┘
```

- **Driver Gateway** authenticates/forwards driver requests and events. It has no PostgreSQL connection and does not calculate earnings.
- **Core API** owns driver authentication, finance reads, payment-method writes, and PostgreSQL access.
- **Routing Worker** consumes driver events from Redis Streams and writes delivery outcomes and their earnings to PostgreSQL.
- **Redis Streams** transport queued events to the worker. Redis acceptance is not a durable finance commit; the worker's PostgreSQL transaction is authoritative.
- **PostgreSQL / Neon** is the durable store when the services' `DATABASE_URL` is configured with the relevant Neon connection URL. Core API and Routing Worker each create their own database engine from `DATABASE_URL`; configure both to target the same database. Driver Gateway uses `CORE_API_URL` to reach Core API and does not need `DATABASE_URL`.

Do not put a database URL, password, encryption key, or other secret in this document. Keep `DATABASE_URL` in the deployment's secret/environment configuration. A local or E2E configuration may point at a separate test database; passing a local test does not by itself prove that Neon contains the same schema or data.

## Earnings formula

For each accepted `delivery.completed` event, the Routing Worker calculates the following INR ledger credits:

```text
base pay       = ₹4.50
weight bonus   = round_half_up(weight_kg × ₹0.20, 2)
distance bonus = round_half_up(max(0, planned_distance_m − 3,000) / 1,000 × ₹0.50, 2)
delivery total = base pay + non-zero weight bonus + non-zero distance bonus
```

The implementation uses Python `Decimal` arithmetic and `ROUND_HALF_UP` to two decimal places. The first 3 km of the planned stop leg do not earn a distance bonus. The distance is `route_stops.planned_distance_m`; if it is missing, the worker obtains the leg distance from OSRM and stores it on the stop before calculating the credit. Weight comes from `orders.weight_kg`. Zero-valued bonus entries are omitted; the base-pay entry is always included.

**Example:** For a 2 kg order with an 8 km planned stop leg:

```text
base pay       = ₹4.50
weight bonus   = 2 × ₹0.20 = ₹0.40
distance bonus = (8 − 3) × ₹0.50 = ₹2.50
delivery total = ₹7.40
```

This is the currently coded prototype formula, not a configurable tariff. Tips are not automatically included. Trusted operations adjustments can add `tip`, `bonus`, or `adjustment` ledger entries.

## Database tables and relationships

The database schema is defined in the repository's [`schema.sql`](../schema.sql), mirrored by [`db_models/models.py`](../db_models/models.py), and the finance tables were introduced by [`2026_11_18_01_driver_payments_earnings.sql`](../db/migrations/2026_11_18_01_driver_payments_earnings.sql). Existing installations with the older `driver_earnings` table shape have a separate guarded upgrade in [`2026_11_19_01_driver_earnings_legacy_archive.sql`](../db/migrations/2026_11_19_01_driver_earnings_legacy_archive.sql); it renames the legacy table to preserve those rows.

| Table | Purpose and key relationship |
|---|---|
| `drivers` | Driver identity is `drivers.user_id`; finance records use this as their `driver_id`. |
| `orders` | Supplies `weight_kg` and the order reference for a delivery credit. |
| `routes` | Associates a delivery credit with its assigned route. |
| `route_stops` | Supplies the planned leg distance and links the credit to a particular delivery stop. |
| `driver_earnings` | Append-only, itemized ledger. Each row stores the driver, INR amount, entry type, description, source event, and optional route/stop/order references. |
| `driver_wallets` | One row per driver, with the current INR `available_balance`. Created when a delivery credit or trusted adjustment is posted. |
| `driver_payment_methods` | Stores encrypted payout details and separately exposes masked details; it is not a transfer or earnings table. |
| `processed_events` | Durable event receipt/idempotency status written by the worker; it is not the earnings ledger. |

`driver_earnings` has unique indexes on `(route_stop_id, entry_type)` and `(source_event_id, entry_type)` when those values are present. These prevent duplicate earning components for the same stop or source event. Each ledger credit also records `route_id`, `route_stop_id`, and `order_id` when created for a completed delivery. `driver_wallets.available_balance` is updated alongside the ledger credits in the same worker database transaction.

The worker processes `delivery.completed` by updating the stop/order and related delivery records, adding itemized earning rows, updating the wallet, and writing the event receipt. These database changes commit together; the Redis message is acknowledged only after the database transaction completes. The database, not the Redis stream, is the source of truth for the finance records.

## Finance endpoints

| Method | Driver Gateway path | Purpose |
|---|---|---|
| `GET` | `/driver/earnings` | Read available balance, totals by category, and recent ledger transactions. `limit` defaults to 20 and is capped at 50. |
| `GET` | `/driver/payment-methods` | List the signed-in driver's saved methods with masked details. |
| `POST` | `/driver/payment-methods` | Save a UPI handle or bank account. |
| `PUT` | `/driver/payment-methods/{method_id}/preferred` | Select the driver's preferred saved method. |

The Gateway allowlists and proxies these requests to the same Core API paths, forwarding the session cookie. Core API enforces the signed-in driver's identity, so a driver cannot read or modify another driver's finance records through these self-service endpoints.

`GET /driver/earnings` returns `currency`, `available_balance`, totals for `base_pay`, `tips`, `bonuses`, `adjustments`, `total_earned`, and the most recent transactions. `bonuses` includes distance, weight, and operations bonus entries. Payout requests, withdrawals, and bank/UPI transfers are not implemented.

## Payout method security

Supported method types:

- **UPI:** `method_type: "upi"` with a UPI ID.
- **Bank account:** `method_type: "bank_account"` with account-holder name, account number, and IFSC.

Core API validates the values, encrypts the submitted details with Fernet using `PAYMENT_METHOD_ENCRYPTION_KEY`, and stores the ciphertext in `driver_payment_methods.encrypted_details`. It stores a masked representation separately and returns only the method ID, type, masked details, preferred flag, and creation time. UPI IDs are masked; bank accounts expose only the last four digits.

At most one saved payout method per driver can be preferred, enforced by a partial unique index. Adding a method makes it preferred if requested or if the driver has no preferred method yet. Selecting another preferred method switches the preference. Saving a destination does **not** initiate a payout.

## Deployment and Neon verification

1. Initialize a fresh database from the current `schema.sql`, or select the migration that matches the target's current schema. Do not blindly apply both finance migrations: the legacy archive migration is for the specifically detected older earnings-table shape, and its preserved legacy data should be reviewed.
2. Set Core API and Routing Worker `DATABASE_URL` values to the same intended database. For the hosted Neon environment, use its Neon connection URL as a protected secret; do not copy it into source control or documentation.
3. Configure Core API's `PAYMENT_METHOD_ENCRYPTION_KEY` with a valid Fernet key. Finance-method creation returns `503` if the key is missing or invalid.
4. Confirm the schema is present on the **same Neon database** used by the deployed services. At minimum, verify `driver_wallets`, `driver_earnings`, `driver_payment_methods`, the finance enum types, and the `route_stops.planned_distance_m` column.
5. After a real delivery is committed, verify `driver_earnings` contains itemized rows and `driver_wallets.available_balance` reflects their sum. Check `processed_events` for the event receipt and compare the IDs to the relevant route stop and order.

The application selects its database from runtime environment configuration. A successful local test only verifies the local database and services that the test was configured to use; it does not confirm Neon deployment configuration or Neon data.
