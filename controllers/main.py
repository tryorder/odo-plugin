# -*- coding: utf-8 -*-
import json
import logging
import re
import html

from odoo import http, SUPERUSER_ID
from odoo.http import request

_logger = logging.getLogger(__name__)


class OrderConnectorController(http.Controller):
    """HTTP API consumed by the TryOrder (service-pos) platform.

    All endpoints are protected by a shared API key sent in the ``X-Api-Key``
    header and validated against the ``order_connector.api_key`` system
    parameter (configured under Settings > Order Connector).
    """

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _check_auth(self):
        """Return None when authorised, otherwise a JSON error response."""
        expected = request.env['ir.config_parameter'].sudo().get_param('order_connector.api_key')
        provided = request.httprequest.headers.get('X-Api-Key')
        if not expected:
            return self._json({'success': False, 'error': 'API key not configured in Odoo'}, status=503)
        if not provided or provided != expected:
            return self._json({'success': False, 'error': 'Unauthorized'}, status=401)
        return None

    @staticmethod
    def _json(payload, status=200):
        OrderConnectorController._log_inbound(payload, status)
        return request.make_json_response(payload, status=status)

    @staticmethod
    def _log_inbound(payload, status):
        """Record every inbound endpoint hit in order.connector.log (best-effort)."""
        try:
            method = request.httprequest.method
            req_body = None
            if method in ('POST', 'PUT', 'PATCH'):
                req_body = (request.httprequest.get_data(as_text=True) or '')[:10000]
            success = payload.get('success') if isinstance(payload, dict) else (200 <= status < 300)
            request.env['order.connector.log'].sudo().create({
                'direction': 'inbound',
                'method': method,
                'endpoint': request.httprequest.path,
                'status_code': status,
                'success': bool(success),
                'remote_addr': request.httprequest.remote_addr,
                'request_body': req_body,
                'response_body': json.dumps(payload, default=str, ensure_ascii=False)[:10000],
            })
        except Exception:
            _logger.exception('order_connector: failed to write inbound log')

    @staticmethod
    def _body():
        try:
            raw = request.httprequest.get_data(as_text=True) or '{}'
            return json.loads(raw)
        except (ValueError, TypeError):
            return {}

    @staticmethod
    def _as_text(value):
        """Coerce a value to a string. The platform may send localized names as
        dicts ({'ar': '...', 'en': '...'}); pick en, then ar, then any value."""
        if isinstance(value, dict):
            return str(value.get('en') or value.get('ar') or next(iter(value.values()), '') or '')
        return str(value) if value is not None else ''

    @staticmethod
    def _strip_html(value):
        if not value:
            return ''
        text = re.sub(r'<[^>]*>', '', value)
        text = html.unescape(text)
        return re.sub(r'\s+', ' ', text).strip()

    @staticmethod
    def _tr(record, field, lang):
        return record.with_context(lang=lang)[field]

    @staticmethod
    def _ar_code():
        """The Arabic language code this database actually has installed.

        Odoo ships Arabic as 'ar_001', but a database may carry a country
        variant instead ('ar_SA', 'ar_EG', ...) or no Arabic at all. Odoo 17+
        raises "Invalid language code" for a language that is not installed,
        which fails the whole request, so never hardcode it. Returns None when
        the database has no Arabic.
        """
        try:
            installed = [code for code, _name in request.env['res.lang'].sudo().get_installed()]
        except Exception:  # noqa: BLE001 - a language lookup must never break a request
            _logger.exception("Order Connector: could not list installed languages")
            return None
        if 'ar_001' in installed:
            return 'ar_001'
        return next((code for code in installed if code == 'ar' or code.startswith('ar_')), None)

    @classmethod
    def _tr_ar(cls, record, field):
        """Arabic value of `field`, falling back to the English one when the
        database has no Arabic installed, so the platform still gets a name."""
        return cls._tr(record, field, cls._ar_code() or 'en_US')

    # ------------------------------------------------------------------ #
    # GET /order_connector/ping
    # ------------------------------------------------------------------ #
    @http.route('/order_connector/ping', type='http', auth='public', methods=['GET'], csrf=False)
    def ping(self, **kw):
        auth = self._check_auth()
        if auth:
            return auth
        params = request.env['ir.config_parameter'].sudo()
        return self._json({
            'success': True,
            'tenant': params.get_param('order_connector.tenant'),
            'company': request.env.company.name,
            'version': '2.0',
        })

    # ------------------------------------------------------------------ #
    # GET /order_connector/branches
    # ------------------------------------------------------------------ #
    @http.route('/order_connector/branches', type='http', auth='public', methods=['GET'], csrf=False)
    def branches(self, **kw):
        auth = self._check_auth()
        if auth:
            return auth
        configs = request.env['pos.config'].sudo().search([])
        data = [{
            'id': str(config.id),
            'name': config.name,
            'company': config.company_id.name if config.company_id else None,
        } for config in configs]
        # Fall back to companies if no POS is configured yet.
        if not data:
            data = [{
                'id': str(company.id),
                'name': company.name,
                'company': company.name,
            } for company in request.env['res.company'].sudo().search([])]
        return self._json({'success': True, 'branches': data})

    # ------------------------------------------------------------------ #
    # GET /order_connector/catalog
    # ------------------------------------------------------------------ #
    @http.route('/order_connector/catalog', type='http', auth='public', methods=['GET'], csrf=False)
    def catalog(self, **kw):
        auth = self._check_auth()
        if auth:
            return auth
        # When a branch (pos.config) is given, only export the products and
        # categories available in that branch, so each mapped branch receives
        # its own menu instead of every product in the database.
        config = self._resolve_catalog_config(kw.get('branch_id'))
        return self._json({
            'success': True,
            'categories': self._catalog_categories(config),
            'items': self._catalog_items(config),
            'sizes': [],
        })

    def _resolve_catalog_config(self, branch_id):
        """Return the pos.config for branch_id, or None (unfiltered)."""
        if not branch_id:
            return None
        try:
            config = request.env['pos.config'].sudo().browse(int(branch_id))
        except (ValueError, TypeError):
            return None
        return config if config.exists() else None

    def _config_category_ids(self, config):
        """The pos.category ids available at this branch, expanded to include
        child categories. Returns None when the branch does not restrict
        categories (all categories available)."""
        if not config or not getattr(config, 'limit_categories', False):
            return None
        available = getattr(config, 'iface_available_categ_ids', False)
        if not available:
            return None
        return request.env['pos.category'].sudo().search(
            [('id', 'child_of', available.ids)]).ids

    def _product_domain(self, config):
        """Search domain for the products exported to a branch: available in
        POS, in the branch's company, and within its category limits."""
        domain = [('available_in_pos', '=', True)]
        if config:
            company = config.company_id
            if company:
                domain += ['|', ('company_id', '=', False), ('company_id', '=', company.id)]
            categ_ids = self._config_category_ids(config)
            if categ_ids is not None:
                domain.append(('pos_categ_ids', 'in', categ_ids))
        return domain

    def _catalog_categories(self, config=None):
        domain = []
        categ_ids = self._config_category_ids(config)
        if categ_ids is not None:
            domain = [('id', 'in', categ_ids)]
        categories = request.env['pos.category'].sudo().search(domain)
        result = []
        for cat in categories:
            result.append({
                '_id': str(cat.id),
                'remoteId': str(cat.id),
                'name_en': self._tr(cat, 'name', 'en_US'),
                'name_ar': self._tr_ar(cat, 'name'),
                'description_en': '',
                'description_ar': '',
                'parent_id': str(cat.parent_id.id) if cat.parent_id else None,
                'sort': cat.sequence,
            })
        return result

    def _base_url(self):
        """Public base URL. Uses web.base.url (set to the https public host when
        Odoo runs behind a TLS-terminating proxy) instead of host_url, which is
        http on the internal proxy hop and 301-redirects (IPD-209)."""
        params = request.env['ir.config_parameter'].sudo()
        base = (params.get_param('web.base.url') or '').strip() or request.httprequest.host_url
        return base.rstrip('/')

    def _catalog_items(self, config=None):
        base = self._base_url()
        products = request.env['product.template'].sudo().search(self._product_domain(config))
        result = []
        for product in products:
            pos_categs = product.pos_categ_ids
            category_id = str(pos_categs[0].id) if pos_categs else None
            has_image = bool(product.image_512)
            is_combo = product.type == 'combo'
            result.append({
                '_id': str(product.id),
                'remoteId': str(product.id),
                'sku': product.default_code or '',
                'type': product.type,
                'name_en': self._tr(product, 'name', 'en_US'),
                'name_ar': self._tr_ar(product, 'name'),
                'description_en': self._strip_html(self._tr(product, 'description_sale', 'en_US')),
                'description_ar': self._strip_html(self._tr_ar(product, 'description_sale')),
                'price': product.list_price,
                'category': category_id,
                'is_disabled': not product.active,
                'image_url': f"{base}/public/product/image/{product.id}" if has_image else None,
                'add_on': self._catalog_addons(product),
                'combos': self._catalog_combos(product) if is_combo else [],
            })
        return result

    def _catalog_combos(self, product):
        """IPD-210: export Odoo combo groups/choices so combo options sync.

        Odoo combo product -> combo_ids (product.combo, the choice groups) ->
        combo_item_ids (product.combo.item) -> product_id + extra_price.
        """
        combos = []
        for combo in getattr(product, 'combo_ids', []) or []:
            items = []
            for ci in getattr(combo, 'combo_item_ids', []) or []:
                prod = getattr(ci, 'product_id', False)
                tmpl_id = prod.product_tmpl_id.id if prod else None
                items.append({
                    'id': f"comboitem-{ci.id}",
                    'product_id': str(tmpl_id) if tmpl_id else None,
                    'name_en': self._tr(prod, 'name', 'en_US') if prod else '',
                    'name_ar': self._tr_ar(prod, 'name') if prod else '',
                    'extra_price': getattr(ci, 'extra_price', 0.0) or 0.0,
                })
            combos.append({
                'id': f"combo-{combo.id}",
                'name_en': self._tr(combo, 'name', 'en_US'),
                'name_ar': self._tr_ar(combo, 'name'),
                'items': items,
            })
        return combos

    def _catalog_addons(self, product):
        """Map Odoo product attributes -> modifier groups/options.

        Each attribute line becomes a modifier category; each of its values
        becomes a modifier (with price_extra as the option price).
        """
        add_on = []
        for line in product.attribute_line_ids:
            attribute = line.attribute_id
            category = {
                '_id': f"attr-{attribute.id}",
                'remoteId': f"attr-{attribute.id}",
                'name_en': self._tr(attribute, 'name', 'en_US'),
                'name_ar': self._tr_ar(attribute, 'name'),
                'description_en': '',
                'description_ar': '',
                # Standard Odoo attribute lines have no "required" flag; default to optional.
                'min_selection': 0,
                'max_selection': 1 if attribute.display_type in ('radio', 'select', 'color') else len(line.product_template_value_ids),
                'status': True,
            }
            for ptav in line.product_template_value_ids:
                add_on.append({
                    'modifierCategory': category,
                    'modifier': {
                        '_id': f"ptav-{ptav.id}",
                        'remoteId': f"ptav-{ptav.id}",
                        'name_en': self._tr(ptav, 'name', 'en_US'),
                        'name_ar': self._tr_ar(ptav, 'name'),
                        'price': ptav.price_extra,
                        'category': f"attr-{attribute.id}",
                    },
                })
        return add_on

    # ------------------------------------------------------------------ #
    # POST /order_connector/orders
    # ------------------------------------------------------------------ #
    @http.route('/order_connector/orders', type='http', auth='public', methods=['POST'], csrf=False)
    def create_order(self, **kw):
        auth = self._check_auth()
        if auth:
            return auth

        body = self._body()
        order = body.get('order') or {}
        items = order.get('items') or []
        if not items:
            return self._json({'success': False, 'error': 'order.items is required'}, status=422)

        try:
            record, kind = self._create_order(order, items)
        except ValueError as exc:
            _logger.warning("Order Connector create_order rejected: %s", exc)
            return self._json({'success': False, 'error': str(exc)}, status=422)
        except Exception as exc:  # noqa: BLE001 - surface any ORM error to the platform
            _logger.exception("Order Connector create_order failed")
            return self._json({'success': False, 'error': str(exc)}, status=500)

        name = (record.name or record.pos_reference) if kind == 'pos' else record.name
        return self._json({
            'success': True,
            'order_id': str(record.id),
            'order_name': name,
            'state': record.state,
            'kind': kind,
        })

    def _create_order(self, order, items):
        """Prefer a pos.order so the order shows in Point of Sale > Orders.
        Falls back to a sale.order when no POS session is available or the
        pos.order can't be built (wrapped in a savepoint so a failed attempt
        rolls back cleanly and doesn't leave a half-created order)."""
        session = None
        try:
            session = self._resolve_open_session(order.get('branch_id'))
        except Exception:  # noqa: BLE001
            _logger.exception("Order Connector: could not resolve a POS session")

        if session:
            try:
                with request.env.cr.savepoint():
                    return self._build_pos_order(order, items, session), 'pos'
            except ValueError:
                raise
            except Exception:  # noqa: BLE001
                _logger.exception("Order Connector: pos.order failed; falling back to sale.order")

        return self._build_sale_order(order, items), 'sale'

    def _resolve_open_session(self, branch_id):
        """Return an opened pos.session for the branch's POS config, opening one
        if needed. Returns None if none can be obtained (caller falls back)."""
        env = request.env
        config = None
        if branch_id:
            try:
                cfg = env['pos.config'].sudo().browse(int(branch_id))
                config = cfg if cfg.exists() else None
            except (ValueError, TypeError):
                config = None
        if not config:
            config = env['pos.config'].sudo().search([], limit=1)
        if not config:
            return None

        session = env['pos.session'].sudo().search(
            [('config_id', '=', config.id), ('state', '=', 'opened')],
            limit=1, order='id desc')
        if session:
            return session

        try:
            session = env['pos.session'].sudo().create({'config_id': config.id, 'user_id': SUPERUSER_ID})
            if session.state != 'opened':
                session.action_pos_session_open()
            return session if session.state == 'opened' else None
        except Exception:  # noqa: BLE001
            _logger.exception("Order Connector: could not open a POS session for config %s", config.id)
            return None

    @staticmethod
    def _order_type_label(order_type):
        """Readable label for the order type (delivery / pickup / dinein / ...)."""
        if not order_type:
            return ''
        key = str(order_type).lower().replace('-', '_').replace(' ', '_')
        return {
            'delivery': 'Delivery',
            'pickup': 'Pickup',
            'pick_up': 'Pickup',
            'dinein': 'Dine In',
            'dine_in': 'Dine In',
            'drivethru': 'Drive Thru',
            'drive_thru': 'Drive Thru',
        }.get(key, str(order_type).replace('_', ' ').title())

    @staticmethod
    def _first_field(model, candidates):
        """Return the first of `candidates` that exists on `model` (note field
        names differ across Odoo versions), else None."""
        fields = request.env[model].sudo()._fields
        for name in candidates:
            if name in fields:
                return name
        return None

    def _delivery_product(self):
        """Find or create the shared 'Delivery Fee' service product used to
        represent the order's delivery fee as a line."""
        Product = request.env['product.product'].sudo()
        prod = Product.search([('default_code', '=', 'ORDER_DELIVERY_FEE')], limit=1)
        if not prod:
            prod = Product.create({
                'name': 'Delivery Fee',
                'default_code': 'ORDER_DELIVERY_FEE',
                'type': 'service',
                'sale_ok': True,
                'purchase_ok': False,
                'available_in_pos': True,
                'taxes_id': [(6, 0, [])],
                'list_price': 0.0,
            })
        return prod

    # Normalize the raw discount labels the platform sends into the names
    # merchants expect to see in Odoo.
    _DISCOUNT_LABELS = {
        'discount': 'Order Discount',
        'order discount': 'Order Discount',
        'coupon': 'Coupon Discount',
        'coupon discount': 'Coupon Discount',
        'wallet': 'Wallet Discount',
        'wallet balance': 'Wallet Discount',
        'wallet discount': 'Wallet Discount',
        'points': 'Loyalty Points Discount',
        'loyalty': 'Loyalty Points Discount',
        'loyalty points': 'Loyalty Points Discount',
        'loyalty points discount': 'Loyalty Points Discount',
    }

    def _discount_label(self, label):
        """Map a raw discount label to the display name shown in Odoo, e.g.
        'Wallet Balance' -> 'Wallet Discount'. Unknown labels get a
        ' Discount' suffix unless they already carry one."""
        text = self._as_text(label).strip()
        if not text:
            return 'Order Discount'
        key = text.lower()
        if key in self._DISCOUNT_LABELS:
            return self._DISCOUNT_LABELS[key]
        return text if key.endswith('discount') else '%s Discount' % text

    def _discount_product(self, label=None):
        """Find or create the service product used to represent an order-level
        discount as a negative line. Each discount type gets its own product so
        the backend Products list (which shows the product, not the line label)
        reads e.g. 'Coupon Discount' / 'Wallet Discount' instead of a single
        generic 'Order Discount' for every source."""
        display = self._discount_label(label)
        if display == 'Order Discount':
            code = 'ORDER_DISCOUNT'  # keep the original code for back-compat
        else:
            slug = re.sub(r'[^A-Z0-9]+', '_', display.upper()).strip('_')
            code = 'ORDER_DISCOUNT_%s' % slug
        Product = request.env['product.product'].sudo()
        prod = Product.search([('default_code', '=', code)], limit=1)
        if not prod:
            prod = Product.create({
                'name': display,
                'default_code': code,
                'type': 'service',
                'sale_ok': True,
                'purchase_ok': False,
                'available_in_pos': True,
                'taxes_id': [(6, 0, [])],
                'list_price': 0.0,
            })
        return prod

    def _discount_components(self, order):
        """Normalize the order-level discounts into a list of
        (label, amount) pairs. Prefers the itemized `discounts` breakdown
        (coupon / wallet balance / loyalty points) so each shows as its own
        line; falls back to the single aggregate `discount` for older callers."""
        components = []
        breakdown = order.get('discounts')
        if isinstance(breakdown, (list, tuple)) and breakdown:
            for component in breakdown:
                if not isinstance(component, dict):
                    continue
                amount = float(component.get('amount') or 0)
                if not amount:
                    continue
                label = self._as_text(component.get('label')) or 'Discount'
                components.append((label, amount))
            if components:
                return components

        discount = float(order.get('discount') or 0)
        if discount:
            components.append(('Discount', discount))
        return components

    def _pos_payment_method(self, session, payment_type):
        """Pick the POS payment method matching the order's payment type:
        a cash method for offline/cash, otherwise a non-cash (card) method.
        Falls back to any available method."""
        methods = session.payment_method_ids or session.config_id.payment_method_ids
        if not methods:
            methods = request.env['pos.payment.method'].sudo().search(
                [('company_id', '=', session.company_id.id)])
        if not methods:
            return request.env['pos.payment.method'].sudo().browse(False)

        def is_cash(m):
            mtype = getattr(m, 'type', None)
            if mtype:
                return mtype == 'cash'
            return bool(getattr(m, 'is_cash_count', False))

        want_cash = (payment_type or '').lower() in ('offline', 'cash', 'cod', 'cash_on_delivery')
        cash = methods.filtered(is_cash)
        non_cash = methods - cash
        if want_cash:
            return (cash or methods)[:1]
        return (non_cash or methods)[:1]

    @staticmethod
    def _localized(value, lang):
        """Pick one language out of a localized value ({en,ar} dict)."""
        if isinstance(value, dict):
            return str(value.get(lang) or '')
        return ''

    def _addon_names_from_id(self, mod_id):
        """Resolve an add-on's English & Arabic names from its Odoo source,
        using Odoo's own translations so the option matches the UI language
        (the same way the main product line does). The catalog exports add-on
        ids as 'ptav-<id>' (a product attribute value) and combo items as
        'comboitem-<id>'; a plain integer is treated as a product id.
        Returns (en, ar) with '' when unresolved."""
        mod_id = self._as_text(mod_id)
        if not mod_id:
            return '', ''
        env = request.env
        try:
            m = re.match(r'^ptav-(\d+)$', mod_id)
            if m:
                rec = env['product.template.attribute.value'].sudo().browse(int(m.group(1)))
                if rec.exists():
                    return self._tr(rec, 'name', 'en_US'), self._tr_ar(rec, 'name')
            m = re.match(r'^comboitem-(\d+)$', mod_id)
            if m:
                ci = env['product.combo.item'].sudo().browse(int(m.group(1)))
                if ci.exists() and ci.product_id:
                    return self._tr(ci.product_id, 'name', 'en_US'), self._tr_ar(ci.product_id, 'name')
            if mod_id.isdigit():
                prod = env['product.product'].sudo().browse(int(mod_id))
                if prod.exists():
                    return self._tr(prod, 'name', 'en_US'), self._tr_ar(prod, 'name')
        except Exception:  # noqa: BLE001 - fall back to the order-supplied name
            _logger.exception("Order Connector: could not resolve add-on name for %s", mod_id)
        return '', ''

    def _addon_product(self, name_value, mod_id=None):
        """Find or create a POS service product for an order add-on / combo
        option, so each selected option shows as its own order line.

        The product is named in both English and Arabic so the order line
        reads in the user's language, and carries NO internal reference so the
        line shows a clean product name (not "[ORDER_ADDON_x]") — the backend
        order list renders the product's display name, not the line label.

        Names come from Odoo's own translations (resolved from the option id)
        when available, so they localize even when the order only carried one
        language; otherwise the order-supplied name is used."""
        en_odoo, ar_odoo = self._addon_names_from_id(mod_id)
        en = en_odoo or self._localized(name_value, 'en') or self._as_text(name_value)
        ar = ar_odoo or self._localized(name_value, 'ar')
        display = (en or ar or 'Add-on').strip()

        Product = request.env['product.product'].sudo()
        # Reuse our own add-on products (service / POS / no reference), matched
        # by their English name. The default_code filter keeps us from touching
        # real catalog products (which normally carry a reference).
        prod = Product.with_context(lang='en_US').search([
            ('name', '=', display),
            ('type', '=', 'service'),
            ('available_in_pos', '=', True),
            ('sale_ok', '=', True),
            ('purchase_ok', '=', False),
            ('default_code', '=', False),
        ], limit=1)
        if not prod:
            prod = Product.with_context(lang='en_US').create({
                'name': display,
                'type': 'service',
                'sale_ok': True,
                'purchase_ok': False,
                'available_in_pos': True,
                'taxes_id': [(6, 0, [])],
                'list_price': 0.0,
            })
        ar_lang = self._ar_code()
        if ar and ar_lang and ar != display:
            try:
                prod.with_context(lang=ar_lang).write({'name': ar})
            except Exception:  # noqa: BLE001 - translation is best-effort
                _logger.exception("Order Connector: could not set Arabic add-on name")
        return prod

    def _tax_amounts(self, taxes, currency, partner, unit_price, qty, product=None):
        """Return (subtotal_excl, subtotal_incl) for a line, applying `taxes`."""
        if taxes:
            res = taxes.compute_all(unit_price, currency, qty, product=product, partner=partner)
            return res['total_excluded'], res['total_included']
        return unit_price * qty, unit_price * qty

    def _build_pos_order(self, order, items, session):
        env = request.env
        ProductTemplate = env['product.template'].sudo()
        config = session.config_id
        company = config.company_id or env.company
        currency = config.currency_id or company.currency_id
        partner = self._resolve_partner(order.get('customer') or {})
        line_note_field = self._first_field('pos.order.line', ['customer_note', 'note'])

        lines = []
        amount_total = 0.0
        amount_tax = 0.0
        item_notes = []
        for item in items:
            template_id = item.get('product_id')
            if not template_id:
                continue
            try:
                template = ProductTemplate.browse(int(template_id))
            except (ValueError, TypeError):
                template = ProductTemplate.browse(False)
            if not template.exists():
                raise ValueError(f"Unknown product_id {template_id}")

            variant = template.product_variant_id
            qty = float(item.get('qty') or 1)
            # Use the price the platform sends, including 0 (e.g. a free-product
            # coupon). Only fall back to the Odoo list price when no price is
            # sent at all — `or` would wrongly treat 0 as missing.
            item_price = item.get('price')
            price = float(item_price) if item_price is not None else template.list_price

            taxes = variant.taxes_id
            if taxes and company:
                taxes = taxes.filtered(lambda t: t.company_id == company) or taxes

            # Main product line at its own price (add-ons are their own lines
            # below, not folded into this price).
            subtotal, subtotal_incl = self._tax_amounts(taxes, currency, partner, price, qty, variant)
            amount_total += subtotal_incl
            amount_tax += subtotal_incl - subtotal

            line_note = self._as_text(item.get('note')) if item.get('note') else ''
            display_name = self._as_text(item.get('name')) or variant.name
            if line_note:
                # The pos.order backend form shows neither customer_note nor a
                # per-line note column, so also collect notes to append to the
                # order's General Notes where they are actually visible.
                display_name = '%s\nNote: %s' % (display_name, line_note)
                item_notes.append('%s: %s' % (
                    self._as_text(item.get('name')) or variant.name, line_note))

            line_vals = {
                'product_id': variant.id,
                'qty': qty,
                'price_unit': price,
                'price_subtotal': subtotal,
                'price_subtotal_incl': subtotal_incl,
                'discount': 0.0,
                'tax_ids': [(6, 0, taxes.ids if taxes else [])],
                'full_product_name': display_name,
            }
            if line_note_field and line_note:
                line_vals[line_note_field] = line_note
            lines.append((0, 0, line_vals))

            # Selected add-ons / combo options as their own lines so they show
            # in the order with their quantity and price. They carry the parent
            # product's taxes, so the order total is unchanged versus folding
            # the add-on price into the main line.
            for modifier in item.get('modifiers') or []:
                mod_price = float(modifier.get('price') or 0)
                mod_qty = float(modifier.get('qty') or 1) * qty
                mod_name_value = modifier.get('name')
                mod_sub, mod_incl = self._tax_amounts(taxes, currency, partner, mod_price, mod_qty)
                amount_total += mod_incl
                amount_tax += mod_incl - mod_sub
                addon = self._addon_product(mod_name_value, modifier.get('id'))
                lines.append((0, 0, {
                    'product_id': addon.id,
                    'qty': mod_qty,
                    'price_unit': mod_price,
                    'price_subtotal': mod_sub,
                    'price_subtotal_incl': mod_incl,
                    'discount': 0.0,
                    'tax_ids': [(6, 0, taxes.ids if taxes else [])],
                    'full_product_name': self._as_text(mod_name_value) or addon.name,
                }))

        if not lines:
            raise ValueError('No resolvable products in order.items')

        # Delivery fee as its own (untaxed) line so it counts toward the total.
        delivery_fee = float(order.get('delivery_fee') or 0)
        if delivery_fee:
            dp = self._delivery_product()
            lines.append((0, 0, {
                'product_id': dp.id,
                'qty': 1,
                'price_unit': delivery_fee,
                'price_subtotal': delivery_fee,
                'price_subtotal_incl': delivery_fee,
                'discount': 0.0,
                'tax_ids': [(6, 0, [])],
                'full_product_name': dp.name,
            }))
            amount_total += delivery_fee

        # Order-level discounts (coupon / wallet balance / loyalty points) each
        # as its own labeled negative line so they are reflected in the order
        # details and reduce the total.
        for label, amount in self._discount_components(order):
            dpp = self._discount_product(label)
            lines.append((0, 0, {
                'product_id': dpp.id,
                'qty': 1,
                'price_unit': -amount,
                'price_subtotal': -amount,
                'price_subtotal_incl': -amount,
                'discount': 0.0,
                'tax_ids': [(6, 0, [])],
                'full_product_name': dpp.name,
            }))
            amount_total -= amount

        pos_vals = {
            'session_id': session.id,
            'company_id': company.id,
            'partner_id': partner.id,
            'pricelist_id': config.pricelist_id.id if config.pricelist_id else False,
            'lines': lines,
            'amount_tax': amount_tax,
            'amount_total': amount_total,
            'amount_paid': 0.0,
            'amount_return': 0.0,
            'connector_managed': True,
            'connector_provider_order_id': order.get('provider_order_id') or '',
        }
        order_note = self._as_text(order.get('note'))
        type_label = self._order_type_label(order.get('order_type'))
        if type_label:
            order_note = ('Order Type: %s\n%s' % (type_label, order_note)).strip()
        if item_notes:
            order_note = ('%s\n\nItem Notes:\n- %s' % (
                order_note, '\n- '.join(item_notes))).strip()
        note_field = self._first_field('pos.order', ['general_note', 'note'])
        if note_field and order_note:
            pos_vals[note_field] = order_note

        pos_order = env['pos.order'].sudo().create(pos_vals)

        # Register a payment so the order is marked paid (shows as a real order),
        # matching the order's payment type (cash for offline, card otherwise).
        method = self._pos_payment_method(session, order.get('payment_type'))
        if method:
            try:
                env['pos.payment'].sudo().create({
                    'pos_order_id': pos_order.id,
                    'amount': amount_total,
                    'payment_method_id': method.id,
                })
                pos_order.action_pos_order_paid()
            except Exception:  # noqa: BLE001 - keep the order even if it stays unpaid/draft
                _logger.exception("Order Connector: could not mark pos order %s paid", pos_order.id)
        else:
            _logger.warning("Order Connector: no POS payment method for config %s; order stays draft", config.id)

        # A draft pos.order keeps Odoo's default name "/"; assign the config's
        # order-ref sequence so it has a proper reference.
        if not pos_order.name or pos_order.name == '/':
            ref = None
            try:
                if config.sequence_id:
                    ref = config.sequence_id.sudo().next_by_id()
            except Exception:  # noqa: BLE001
                ref = None
            pos_order.name = ref or ('Order/%s' % pos_order.id)

        return pos_order

    def _build_sale_order(self, order, items):
        env = request.env
        ProductTemplate = env['product.template'].sudo()

        partner = self._resolve_partner(order.get('customer') or {})

        order_lines = []
        for item in items:
            template_id = item.get('product_id')
            if not template_id:
                continue
            try:
                template = ProductTemplate.browse(int(template_id))
            except (ValueError, TypeError):
                template = ProductTemplate.browse(False)
            if not template.exists():
                raise ValueError(f"Unknown product_id {template_id}")

            variant = template.product_variant_id
            qty = float(item.get('qty') or 1)
            # Use the price the platform sends, including 0 (e.g. a free-product
            # coupon). Only fall back to the Odoo list price when no price is
            # sent at all — `or` would wrongly treat 0 as missing.
            item_price = item.get('price')
            price = float(item_price) if item_price is not None else template.list_price

            name_parts = [self._as_text(item.get('name')) or template.name]
            for modifier in item.get('modifiers') or []:
                mod_name = self._as_text(modifier.get('name')) or modifier.get('id')
                mod_price = float(modifier.get('price') or 0)
                # Fold modifier prices into the line so the order total matches.
                price += mod_price * float(modifier.get('qty') or 1)
                name_parts.append(f"+ {mod_name}" + (f" ({mod_price})" if mod_price else ''))
            if item.get('note'):
                name_parts.append(str(item['note']))

            order_lines.append((0, 0, {
                'product_id': variant.id,
                'product_uom_qty': qty,
                'price_unit': price,
                'name': '\n'.join(self._as_text(p) for p in name_parts if p),
            }))

        if not order_lines:
            raise ValueError('No resolvable products in order.items')

        # Delivery fee as its own (untaxed) line so it counts toward the total.
        delivery_fee = float(order.get('delivery_fee') or 0)
        if delivery_fee:
            dp = self._delivery_product()
            order_lines.append((0, 0, {
                'product_id': dp.id,
                'product_uom_qty': 1,
                'price_unit': delivery_fee,
                'name': dp.name,
                'tax_id': [(6, 0, [])],
            }))

        # Order-level discounts (coupon / wallet balance / loyalty points) each
        # as its own labeled negative line so they are reflected in the total.
        for label, amount in self._discount_components(order):
            dpp = self._discount_product(label)
            order_lines.append((0, 0, {
                'product_id': dpp.id,
                'product_uom_qty': 1,
                'price_unit': -amount,
                'name': dpp.name,
                'tax_id': [(6, 0, [])],
            }))

        note_bits = []
        if order.get('order_type'):
            note_bits.append(f"Order Type: {self._order_type_label(order.get('order_type'))}")
        if order.get('note'):
            note_bits.append(str(order['note']))
        if order.get('payment_type'):
            note_bits.append(f"Payment: {order['payment_type']}")

        sale_order = env['sale.order'].sudo().create({
            'partner_id': partner.id,
            'order_line': order_lines,
            'client_order_ref': order.get('provider_order_id') or '',
            'note': '\n'.join(note_bits),
            'connector_managed': True,
            'connector_provider_order_id': order.get('provider_order_id') or '',
        })

        # Confirm so it becomes a real sales order (state -> 'sale').
        try:
            sale_order.action_confirm()
        except Exception:  # noqa: BLE001 - keep the draft order if confirmation fails
            _logger.exception("Order Connector: could not confirm sale order %s", sale_order.name)

        return sale_order

    def _resolve_partner(self, customer):
        env = request.env
        Partner = env['res.partner'].sudo()
        phone = (customer.get('phone') or '').strip()
        name = (customer.get('name') or 'TryOrder Customer').strip()

        partner = Partner.browse(False)
        if phone:
            partner = Partner.search(['|', ('phone', '=', phone), ('mobile', '=', phone)], limit=1)
        if not partner:
            partner = Partner.create({
                'name': name,
                'phone': phone or False,
                'email': customer.get('email') or False,
            })
        return partner

    # ------------------------------------------------------------------ #
    # PUT /order_connector/orders/<id>/status
    # ------------------------------------------------------------------ #
    @http.route('/order_connector/orders/<int:order_id>/status', type='http', auth='public',
                methods=['PUT', 'POST'], csrf=False)
    def update_order_status(self, order_id, **kw):
        auth = self._check_auth()
        if auth:
            return auth

        body = self._body()
        status = (body.get('status') or '').lower()
        env = request.env

        pos_order = env['pos.order'].sudo().browse(order_id)
        if pos_order.exists():
            return self._apply_status(pos_order, status, is_pos=True)

        sale_order = env['sale.order'].sudo().browse(order_id)
        if sale_order.exists():
            return self._apply_status(sale_order, status, is_pos=False)

        return self._json({'success': False, 'error': 'Order not found'}, status=404)

    def _apply_status(self, order, status, is_pos):
        # Always record the latest platform status in the order note so
        # intermediate statuses (pending/preparing/ready/...) are reflected;
        # terminal statuses also transition the order state.
        self._record_status_note(order, status)
        # Store the latest status on its own field so it can render as a
        # colored badge in the order header (pos.order only).
        if status and 'connector_status' in order._fields:
            try:
                order.connector_status = status
            except Exception:  # noqa: BLE001 - never fail the status update on this
                _logger.exception("Order Connector: could not set connector_status on %s", order.id)
        try:
            if status in ('canceled', 'cancelled', 'rejected'):
                if is_pos:
                    if order.state != 'cancel':
                        order.write({'state': 'cancel'})
                else:
                    order._action_cancel() if hasattr(order, '_action_cancel') else order.action_cancel()
            elif status in ('completed', 'delivered', 'done', 'picked_up'):
                if is_pos and order.state not in ('done', 'invoiced'):
                    if hasattr(order, 'action_pos_order_done'):
                        order.action_pos_order_done()
                    else:
                        order.write({'state': 'done'})
            elif status in ('confirmed', 'accepted') and not is_pos and order.state in ('draft', 'sent'):
                order.action_confirm()
        except Exception:  # noqa: BLE001 - status is recorded in the note regardless
            _logger.exception("Order Connector: could not transition order %s to %s", order.id, status)

        return self._json({'success': True, 'order_id': str(order.id),
                           'state': order.state, 'status': status})

    def _record_status_note(self, order, status):
        note_field = self._first_field(order._name, ['general_note', 'note'])
        if not note_field or not status:
            return
        try:
            existing = order[note_field] or ''
            label = 'Status: %s' % status
            if existing.rstrip().endswith(label):
                return  # don't duplicate the same trailing status
            order[note_field] = existing + ('\n' if existing else '') + label
        except Exception:  # noqa: BLE001
            _logger.exception("Order Connector: could not record status note on %s", order.id)
