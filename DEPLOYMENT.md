# Order Connector — Odoo Module Deployment (DevOps)

Install the **`order_connector`** Odoo addon onto a self-hosted Odoo instance
(target: `https://odoo.order.sa`, **Odoo 18.0**). This module is the HTTP bridge
that connects Odoo to the TryOrder platform.

> Custom modules **cannot** be installed from the Odoo web UI — the module folder
> must be placed on the server's filesystem (addons path) or pushed to the
> instance's Git repo (Odoo.sh), then installed from **Apps**. Server/deploy
> access is required; the `admin` web login alone is not enough.

---

## 0. What you receive

- **`order_connector.zip`** — the module (unzips to a folder named `order_connector`).
  - The top-level folder **must** be named exactly `order_connector` (it is the
    module's technical name; do not rename it).
- Alternatively, the source is in Git: repo `odo-plugin`, branch
  `feat/odoo-integration` (the repo root *is* the module; deploy it as
  `order_connector`).

Module contents (no external Python deps, no OCA modules required):
```
order_connector/
  __manifest__.py
  __init__.py
  controllers/        # HTTP API (ping, branches, catalog, orders, status)
  models/             # settings, webhook sender, sale_order/pos_order hooks
  views/              # Settings panel
  static/description/icon.png
```
Odoo dependencies (all standard Odoo apps): `base`, `product`, `point_of_sale`,
`sale_management`, `pos_sale`.

---

## 1. Information to confirm before you start

| Question | Why |
|----------|-----|
| What is Odoo's **`addons_path`**? (check `odoo.conf`) | That's where the folder goes |
| Is Odoo run via **Docker**, **systemd/bare-metal**, or **Odoo.sh**? | Determines copy vs git + restart command |
| Is there an **extra/custom addons** dir already? | Prefer it over core addons dirs |
| Outbound HTTPS allowed from the Odoo server? | Needed for status webhooks to the gateway |
| Is the Odoo server reachable from the TryOrder backend? | Needed for menu sync / order push |

---

## 2. Install

### Option A — Docker / docker-compose
```bash
# 1. Copy the module into the mounted addons volume (host path that maps to the
#    container's addons_path, e.g. ./extra-addons -> /mnt/extra-addons)
unzip order_connector.zip -d /srv/odoo/extra-addons/      # adjust path

# 2. Confirm addons_path includes that dir (odoo.conf), then restart
docker compose restart odoo
# (first install of a new module: a plain restart is enough; it appears in Apps)
```

### Option B — Bare metal (systemd / apt / source)
```bash
# 1. Drop the folder into the configured extra-addons dir
unzip order_connector.zip -d /opt/odoo/extra-addons/      # adjust path
chown -R odoo:odoo /opt/odoo/extra-addons/order_connector

# 2. Ensure addons_path in /etc/odoo/odoo.conf includes that dir, then restart
sudo systemctl restart odoo
```

### Option C — Odoo.sh
```bash
# Add the module to the repo connected to the Odoo.sh project, then push.
cp -r order_connector  <odoo.sh-repo>/
cd <odoo.sh-repo> && git add order_connector && git commit -m "Add order_connector" && git push
# Odoo.sh builds and makes it installable on the branch's database.
```

### Then, in the Odoo web UI (as admin)
1. **Settings → Developer Tools → Activate the developer mode**.
2. **Apps → Update Apps List** (confirm).
3. Search **"Order Connector"** → **Activate / Install**.

> If it doesn't appear: re-check `addons_path` includes the folder, the folder is
> named `order_connector`, ownership/permissions are correct, then restart Odoo
> and Update Apps List again. Check the Odoo log for `order_connector` lines.

---

## 3. Configure (app owner can do this; no shell needed)

**Settings → Order Connector**:

| Field | Value |
|-------|-------|
| Tenant | the TryOrder tenant id (e.g. `dev196`) |
| API Key | click **Generate new key**, then copy it (used by the platform) |
| Gateway Base URL | `https://order-api-gateway.karim-group.org` |
| Outbound Webhook Secret | optional |

The platform side stores **Base URL = `https://odoo.order.sa`** + this API Key.

---

## 4. Verify (smoke test)

From a host that can reach the Odoo server, with the generated API key:

```bash
KEY="<api-key-from-settings>"; BASE="https://odoo.order.sa"

# 1) auth + health  -> {"success": true, ...}
curl -s -H "X-Api-Key: $KEY" "$BASE/order_connector/ping"

# 2) no key -> 401 (auth is enforced)
curl -s -o /dev/null -w "%{http_code}\n" "$BASE/order_connector/ping"

# 3) branches (POS configs) -> {"success": true, "branches": [...]}
curl -s -H "X-Api-Key: $KEY" "$BASE/order_connector/branches"

# 4) catalog -> categories + items
curl -s -H "X-Api-Key: $KEY" "$BASE/order_connector/catalog" | head -c 500
```

Expected: `ping` returns `success:true`; missing key returns `401`.

---

## 5. Networking

- **Inbound to Odoo** (`/order_connector/*`): the TryOrder backend must be able to
  reach `https://odoo.order.sa`. It's behind Cloudflare — ensure these API paths
  are not blocked/challenged (allow `X-Api-Key` header; don't force a JS challenge
  on `/order_connector/*`).
- **Outbound from Odoo**: the server must reach
  `https://order-api-gateway.karim-group.org` over HTTPS (order-status webhooks).

---

## 6. Upgrade / Rollback

```bash
# Upgrade after code changes (views/fields): replace the folder, then
docker compose restart odoo        # or: sudo systemctl restart odoo
# In UI: Apps -> Order Connector -> Upgrade

# Rollback / uninstall: Apps -> Order Connector -> Uninstall, then remove the folder.
```
Uninstalling removes the module's two helper fields on sale.order/pos.order; it
does not delete your products, orders, or POS data.

---

## 7. Notes / caveats

- **Odoo version:** the module was developed and verified on **Odoo 17**; the
  target is **Odoo 18**. It should install on 18, but please install on a
  **staging/test database first** and check the log for errors before production.
  (The app team can adjust quickly if Odoo 18 flags an API difference.)
- **Module name is fixed:** keep the folder named `order_connector`.
- **No external dependencies:** no `pip install`, no OCA `queue_job` needed.
- **Coordinate with the backend team** on which integration build is current
  before going live (the plugin and the TryOrder backend must use the same
  sync model).
