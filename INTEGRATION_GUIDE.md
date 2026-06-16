# Odoo ↔ TryOrder (service-pos) — Full Integration Guide

This guide takes you from nothing to a working two-way Odoo integration on your
local machine, step by step. Nothing is assumed beyond what you already have
(service-pos on Valet, Docker Desktop installed).

> **Roles**
> - **Odoo + `order_connector` plugin** — runs in Docker, acts as the provider HTTP API.
> - **service-pos** — runs on Valet, integrates Odoo as a normal provider (slug `odoo`).
> - **API Gateway** (`https://order-api-gateway.karim-group.org`) — public entry that
>   forwards `/webhook/odoo` to service-pos so Odoo can reach you for status updates.

---

## 0. Architecture at a glance

```
service-pos (Valet)                Odoo plugin (Docker :8069)            Odoo core
  Odoo.php  ──── GET /catalog ───►  /order_connector/catalog   ──► product.template / pos.category
            ──── POST /orders ───►  /order_connector/orders     ──► sale.order (confirmed)
            ◄─── webhook ─────────  posts to <gateway>/webhook/odoo  ◄── sale.order state change
```

- **Menu**: service-pos **pulls** the catalog from the plugin.
- **Orders**: service-pos **pushes** orders to the plugin → created as `sale.order`.
- **Status**: the plugin **pushes** status changes back via the gateway.
- **Auth**: every inbound plugin request carries `X-Api-Key: <shared secret>`.

---

## ⚡ Already provisioned on this machine

The local stack is **already running and configured** (you only need Docker Desktop open):

| What | Value |
|------|-------|
| Odoo URL | http://localhost:8069 |
| Database | `odoo` |
| **Login** | **`admin`** / **`admin`** |
| API Key (current) | `testkey123` — regenerate anytime in Settings › Order Connector |
| Tenant | `dev196` |
| Gateway Base URL | `https://order-api-gateway.karim-group.org` |
| Demo data | loaded (38 POS products, 3 categories, 1 POS branch "Shop") |

To open the plugin admin: browse to http://localhost:8069 → log in `admin`/`admin` →
**Settings → Order Connector** to see/change the API key, tenant, gateway URL and
webhook secret. (If the containers are stopped: `cd odo-plugin/docker && docker compose up -d`.)

> Skip to **§3** to connect it to service-pos, or **§9** to connect from the dashboard UI.

---

## 1. Start Odoo 17 locally (Docker)

> Docker Desktop must be **running** first (open the app; `docker info` should succeed).

```bash
cd /home/karim-youssef/Sites/odo-plugin/docker
docker compose up -d            # pulls odoo:17 + postgres:15 on first run (a few minutes)
docker compose logs -f odoo     # wait for: "HTTP service (werkzeug) running on 0.0.0.0:8069"
```

Odoo is now at **http://localhost:8069**. The plugin repo is mounted into the
container as the addon `order_connector` (see `docker-compose.yml`).

### 1.1 Create the database + install the plugin

1. Open http://localhost:8069 → **Create database**:
   - Master Password: `admin` (from `odoo.conf`)
   - Database name: `odoo`
   - Email / Password: your admin login (e.g. `admin` / `admin`)
   - ✅ **Check "Load demonstration data"** — this gives you sample products &
     POS categories to sync. (Without it the catalog is empty.)
2. After login: turn on developer mode — **Settings → Developer Tools → Activate the developer mode**.
3. **Apps → Update Apps List** (top menu, dev mode) → confirm.
4. Search **"Order Connector"** → **Activate / Install**.

> If you don't see it: `docker compose restart odoo`, then Update Apps List again.
> To apply later code changes: **Apps → Order Connector → Upgrade**, or
> `docker compose restart odoo` for controller/Python changes (XML/view changes
> need an Upgrade).

### 1.2 Configure the plugin

**Settings** → scroll to the **Order Connector** panel:

| Field | Value |
|-------|-------|
| **Tenant** | your service-pos tenant, e.g. `dev196` |
| **API Key** | click **Generate new key** → copy the value |
| **Gateway Base URL** | `https://order-api-gateway.karim-group.org` |
| **Outbound Webhook Secret** | (optional) any string; set the same value on the account in service-pos |

Click **Save**. Keep the **API Key** handy — service-pos needs it.

### 1.3 Smoke-test the plugin

```bash
cd /home/karim-youssef/Sites/odo-plugin/docker
./smoke-test.sh <API_KEY> http://localhost:8069
```

You should get `{"success": true, ...}` from **ping**, a **branches** list, and a
**catalog** payload with `categories` and `items`. To also test order creation,
pick a product id from the catalog and:

```bash
PRODUCT_ID=<id_from_catalog> ./smoke-test.sh <API_KEY> http://localhost:8069
```

If all four steps pass, the plugin side is done. ✅

---

## 2. Prepare service-pos

```bash
cd /home/karim-youssef/Sites/service-pos
php artisan migrate          # creates odoo_configs table + seeds the 'odoo' provider
composer dump-autoload       # (optional) ensure the new classes are autoloaded
```

Confirm the provider exists and grab its id:

```bash
php artisan tinker
>>> \App\Models\Provider::where('slug','odoo')->first(['id','slug','name']);
```

Copy the provider **id** (UUID) — call it `PROVIDER_ID` below.

> **Networking note:** service-pos runs natively on Valet and Odoo runs in Docker
> on the **same machine**, so service-pos reaches the plugin at
> `http://localhost:8069` directly. The account `base_url` is therefore
> `http://localhost:8069`.

---

## 3. Connect a merchant (account + integration)

You can do this over HTTP (production path) or via tinker (most reliable locally).
Tinker is recommended for the first run because it skips gateway auth headers.

### 3.1 Create the account (stores Odoo credentials)

```bash
php artisan tinker
```
```php
$provider = \App\Models\Provider::where('slug','odoo')->first();

$account = \App\Models\Account::create([
    'tenant'      => 'dev196',                 // your tenant
    'name'        => 'Odoo Local',
    'provider_id' => $provider->id,
    'user_name'   => 'system',
    'user_id'     => 'system',
    'settings'    => [],
    'config'      => [
        'base_url'       => 'http://localhost:8069',
        'api_key'        => 'PASTE_THE_API_KEY_FROM_ODOO',
        'webhook_secret' => null,              // or the value you set in 1.2
    ],
]);
$account->id;   // copy this — ACCOUNT_ID
```

Verify connectivity from service-pos to the plugin:

```php
$account->getClient()->getBranchList($account);   // should return [['name'=>..,'id'=>..], ...]
```

### 3.2 Create an integration (links one branch)

Pick an internal `branch_id` from service-pos and a `linked_id` from the branch
list above (the Odoo POS config id), then:

```php
$provider->integrations()->updateOrCreate(
    ['tenant' => 'dev196', 'branch_id' => 'YOUR_INTERNAL_BRANCH_ID'],
    [
        'account_id'       => $account->id,
        'linked_id'        => 'ODOO_POS_CONFIG_ID',   // from getBranchList
        'linked_name'      => 'Main POS',
        'provider_id'      => $provider->id,
        'integration_info' => [],
        'status'           => true,
    ]
);
```

### 3.2-alt Over HTTP (production path)

```
POST  https://service-pos.test/api/v1/providers/integrate/{PROVIDER_ID}
Body (create account):   { "tenant":"dev196","name":"Odoo Local","base_url":"http://localhost:8069","api_key":"...","settings":{} }
Body (create integration): { "type":"create","tenant":"dev196","account_id":"...","branch_id":"...","linked_id":"...","linked_name":"Main POS","provider_id":"{PROVIDER_ID}" }
```
(Send the same auth/tenant headers your platform normally uses for these calls.)

---

## 4. Sync the menu (Odoo → service-pos)

`QUEUE_CONNECTION=sync` in your `.env`, so the sync runs inline (no worker needed).

```php
// in tinker, with $account from step 3
$account->sync();
```
or over HTTP: `POST https://service-pos.test/api/v1/accounts/sync/{ACCOUNT_ID}`.

What happens:
1. `SyncOdooAccountJob` → `Odoo::sync()` calls `GET /order_connector/catalog`,
   derives modifiers from each item's `add_on[]`, uploads the raw JSON to S3
   (`sync/odoo/{account}/{syncLog}.json`).
2. `App\Jobs\Sync\Odoo\HandleSyncJob` formats it into the internal menu and
   writes `OdooConfig` mapping rows.

Check the result:

```php
\App\Models\SyncLog::where('account_id',$account->id)->latest()->first(['result','sync_counters']);
\App\Models\OdooConfig::where('tenant','dev196')->count();   // > 0 means products mapped
```

`result` should progress to `processing`/success and `sync_counters` should show
non-zero `products`/`groups`. Your menu items now exist in service-pos.

---

## 5. Push an order (service-pos → Odoo)

In normal operation the platform calls `Odoo::sendOrder()` automatically when an
order is placed for this branch. To verify the plugin endpoint end-to-end right
now, use a real product id from the catalog:

```bash
curl -sS -X POST \
  -H "X-Api-Key: <API_KEY>" -H "Content-Type: application/json" \
  http://localhost:8069/order_connector/orders \
  -d '{"order":{"provider_order_id":"TEST-1","order_type":"pickup",
       "customer":{"name":"Test","phone":"0500000000"},
       "items":[{"product_id":"<PRODUCT_TEMPLATE_ID>","qty":2,"price":12.5}]}}' | python3 -m json.tool
```

Expect `{"success": true, "order_id": "<n>", "state": "sale"}`. In Odoo, open
**Sales → Orders** — the order is there, confirmed, tagged *Managed by Order Connector*.

> The full platform path (`Odoo::sendOrder`) maps internal item ids to Odoo ids
> via `OdooConfig` (populated in step 4), so it only works after a sync. The curl
> above bypasses mapping by sending the Odoo `product_id` directly.

---

## 6. Status webhooks (Odoo → service-pos)

When that `sale.order` changes state (e.g. you cancel it, or it's marked done),
the plugin posts to `https://order-api-gateway.karim-group.org/webhook/odoo`,
which the gateway forwards to `POST /api/v1/webhooks/odoo` in service-pos.

- Trigger: in Odoo, open the order → **Cancel** (or confirm/lock).
- service-pos `Webhooks\Odoo` maps the Odoo state (`sale`→accepted, `done`→delivered,
  `cancel`→canceled) and emits `UpdateOrderStatusEvent`, logging an
  `UpdateOrderStatusLog`.

Verify:
```php
\App\Models\UpdateOrderStatusLog::where('provider','odoo')->latest()->first();
```

> The webhook only matches orders that service-pos created (it looks up `Order`
> by `external_id`). Native Odoo-POS orders aren't ingested as new orders yet
> (documented as a future phase in `app/Services/Providers/Odoo/docs.md`).

You can also test the gateway hop directly:
```bash
curl -sS -X POST -H "Content-Type: application/json" \
  https://order-api-gateway.karim-group.org/webhook/odoo \
  -d '{"type":"ORDER_UPDATE_WEBHOOK","data":{"order_id":"<odoo_order_id>","order_status":"cancel"}}'
```

---

## 7. Troubleshooting

| Symptom | Cause / Fix |
|--------|-------------|
| `docker compose up` fails / `Cannot connect to the Docker daemon` | Start **Docker Desktop** first. |
| Plugin not in Apps list | Dev mode on → **Update Apps List**; `docker compose restart odoo`. |
| `ping` returns 401 | API key mismatch — regenerate in Odoo, update `Account.config.api_key`. |
| `ping` returns 503 "API key not configured" | Set + Save the API Key in Odoo Settings → Order Connector. |
| Catalog empty (`items: []`) | DB created without demo data, or products not `available_in_pos`. Tick **Available in POS** on products, or recreate DB with demo data. |
| `sync` result `failed` | Check `storage/logs/laravel.log` for "Odoo sync" lines; usually S3 perms or unreachable `base_url`. |
| `getBranchList` empty | No POS configured in Odoo — the plugin falls back to companies; create a POS under **Point of Sale → Configuration**. |
| Order push 422 "Unknown product_id" | The `product_id` isn't a valid `product.template` id (use one from `/catalog`). |
| Webhook never arrives | Set **Gateway Base URL** in Odoo; confirm the gateway routes `/webhook/odoo` to service-pos; check `docker compose logs odoo` for "webhook failed". |
| Code changes not reflected | Python/controller → `docker compose restart odoo`; views/XML/fields → **Apps → Order Connector → Upgrade**. |

### Useful log spots
- Odoo plugin: `docker compose logs -f odoo` (look for `order_connector` / `Order Connector`).
- service-pos: `storage/logs/laravel.log` (grep `Odoo`).

---

## 9. Connect from the dashboard UI (control-panel-dashboard)

A full Odoo provider frontend now exists (mirrors Foodiezone). Once service-pos has
the `odoo` provider (you ran `php artisan migrate`) and the dashboard is running:

1. Open the dashboard → **Apps → POS** (`/apps/pos`). **Odoo** appears in the provider
   grid (logo is a placeholder at `assets/images/integration/odoo.png` — replace with
   the real Odoo logo).
2. Click **Odoo** → **Accounts** tab → **Add Account**, fill in:
   - **Name** — e.g. "Odoo Local"
   - **Base URL** — `http://localhost:8069` (the plugin URL)
   - **API Key** — the key from Odoo › Settings › Order Connector (`testkey123`)
   - **Webhook Secret** — optional (must match Odoo's "Outbound Webhook Secret")
   - Adjust the sync settings (auto-sync, which fields to sync) → **Save**.
   This POSTs to `api/v1/pos/providers/integrate/{id}` → gateway → service-pos
   `Odoo::createAccount`, which validates the key via `/order_connector/ping`.
3. Go to the **Branches** tab → toggle a branch on → in the modal pick the **Account**,
   the **Branch** (the Odoo POS, from `/order_connector/branches`), and a **Tax Category**
   → **Save**. This creates the integration (`linked_id` = Odoo POS id).
4. Back on the **Accounts** tab, click the **Sync** icon to pull the menu (or it
   auto-syncs). Watch the sync status; items then appear in your menu.

**Files added to the dashboard:**
`components/Apps/Pos/Odoo/{AccountFormModal,Accounts,Box,Branches,IntegrationModal}.vue`,
`assets/images/integration/odoo.png`, and `odoo`/`OdooDesc` keys in `lang/en.json` + `lang/ar.json`.
(`'odoo'` was already in the `isSupportAccounts` list in `pages/apps/pos/_provider.vue`.)

## 10. API Gateway (webhooks) — status

Already wired for `odoo` and verified:
- `config/thirdparty_services.php` → `odoo` entry (**fixed**: it referenced GRUBTECH env
  vars by mistake; now uses `THIRDPARTY_ODOO_APP_TOKEN` / `THIRDPARTY_ODOO_APP_PASSWORD`,
  which are optional — the `validate.webhook` middleware is a pass-through).
- `config/services/pos.php` → `webhook_subscriptions` maps `odoo` → `webhooks/odoo`.

So `POST https://order-api-gateway.karim-group.org/webhook/odoo` (what the plugin sends)
is forwarded to service-pos `api/v1/webhooks/odoo`. No further gateway work needed.

---

## 8. What was built (file map)

**Plugin (`odo-plugin`, module `order_connector`)**
- `controllers/main.py` — API: ping / branches / catalog / orders / status (X-Api-Key auth)
- `controllers/public_product_image_controller.py` — public product images (bugfix: image_512)
- `models/connector_webhook.py` — post-commit webhook sender (no `queue_job` dependency)
- `models/sale_order.py`, `models/pos_order.py` — status-change webhooks
- `models/res_config_settings.py` + `views/res_config_settings_view.xml` — settings UI
- `docker/` — `docker-compose.yml`, `odoo.conf`, `smoke-test.sh`

**service-pos**
- `app/Services/Providers/Odoo/Odoo.php` — provider client (+ `docs.md`)
- `app/Http/Controllers/Webhooks/Odoo.php` + route `webhooks/odoo`
- `app/Jobs/SyncOdooAccountJob.php`, `app/Jobs/Sync/Odoo/HandleSyncJob.php`
- `app/Models/OdooConfig.php` + `app/Events/Config/Odoo/*`
- migrations: `create_odoo_configs_table`, `add_odoo_to_providers_table`
- wiring: `Provider::getClient()`, `Enums\Blend\Providers`, `Account` sync dispatch, `config/services.php`
