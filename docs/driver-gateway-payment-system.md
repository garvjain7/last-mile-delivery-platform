# Driver Gateway Payments — Quick Reference

## What runs where

- **Driver Gateway:** Python 3, FastAPI, and `httpx`. It allowlists and proxies driver finance requests to Core API; it does not store payment details or calculate earnings.
- **Core API:** Python, FastAPI, SQLAlchemy, and PostgreSQL. It authenticates the driver, validates requests, stores the wallet and ledger, and encrypts payout details.
- **Routing Worker:** Python. It posts idempotent ledger credits after a completed delivery is processed.
- **Driver App:** Vanilla JavaScript ES modules. It calls the Gateway and displays balances and masked payout details.

The Gateway forwards the browser's session cookie and relevant request body to Core API. Core API enforces driver authorization. The Gateway does not connect to PostgreSQL.

## Driver finance endpoints

| Method | Gateway path | Purpose |
|---|---|---|
| `GET` | `/driver/earnings` | Balance, earnings totals, and recent ledger entries |
| `GET` | `/driver/payment-methods` | List the signed-in driver's saved methods |
| `POST` | `/driver/payment-methods` | Add a UPI handle or bank account |
| `PUT` | `/driver/payment-methods/{method_id}/preferred` | Select a saved method as preferred |

These are proxied to the same paths on Core API. Only listed methods and paths are forwarded. No delete or payout-transfer endpoint is currently provided.

## Earnings formula and ledger

For each completed delivery, the Routing Worker calculates INR credits:

```text
base pay       = ₹4.50
weight bonus   = round(weight_kg × ₹0.20, 2)
distance bonus = round(max(0, planned_distance_m − 3,000) / 1,000 × ₹0.50, 2)
delivery total = base pay + weight bonus + distance bonus
```

Amounts use decimal arithmetic and round half up to two decimal places. The distance component uses the planned stop distance; the first 3 km do not earn a distance bonus. Zero-value components are not written. Tips and other bonuses are not automatic in this formula; trusted operations adjustments can add tips, bonuses, or adjustments.

Each credit is stored as a `driver_earnings` ledger entry and added to the driver's INR `driver_wallets.available_balance`. Route-stop and source-event uniqueness constraints prevent duplicate delivery credits. `GET /driver/earnings` returns the available balance, totals by category, and up to 50 newest transactions (`limit` defaults to 20).

## Payout methods and sensitive fields

Supported method types:

- **UPI:** `method_type: "upi"` and `upi_id` (for example, `name@bank`).
- **Bank account:** `method_type: "bank_account"`, `account_holder_name`, `account_number`, and `ifsc_code`.

Core API validates the UPI handle, requires a 1–200 character account-holder name, a 6–18 digit account number, and an IFSC matching `AAAA0XXXXXX`. The submitted details are treated as secrets, encrypted with Fernet using `PAYMENT_METHOD_ENCRYPTION_KEY`, and persisted in `driver_payment_methods.encrypted_details`. The API returns only a method ID, type, masked details, preferred flag, and creation time: UPI is masked, and bank accounts show only the last four digits.

Only one saved method per driver may be preferred. Adding a method can make it preferred; the preferred endpoint switches the selection. This records a payout destination only—**it does not initiate a bank or UPI transfer**.

## Setup note

Apply the driver-finance database migration and configure a valid `PAYMENT_METHOD_ENCRYPTION_KEY` for Core API before using these endpoints. Without the schema or encryption key, finance requests cannot be served successfully.
