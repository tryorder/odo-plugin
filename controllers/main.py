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
        return self._json({
            'success': True,
            'categories': self._catalog_categories(),
            'items': self._catalog_items(),
            'sizes': [],
        })

    def _catalog_categories(self):
        categories = request.env['pos.category'].sudo().search([])
        result = []
        for cat in categories:
            result.append({
                '_id': str(cat.id),
                'remoteId': str(cat.id),
                'name_en': self._tr(cat, 'name', 'en_US'),
                'name_ar': self._tr(cat, 'name', 'ar_001'),
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

    def _catalog_items(self):
        base = self._base_url()
        products = request.env['product.template'].sudo().search([('available_in_pos', '=', True)])
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
                'name_ar': self._tr(product, 'name', 'ar_001'),
                'description_en': self._strip_html(self._tr(product, 'description_sale', 'en_US')),
                'description_ar': self._strip_html(self._tr(product, 'description_sale', 'ar_001')),
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
                    'name_ar': self._tr(prod, 'name', 'ar_001') if prod else '',
                    'extra_price': getattr(ci, 'extra_price', 0.0) or 0.0,
                })
            combos.append({
                'id': f"combo-{combo.id}",
                'name_en': self._tr(combo, 'name', 'en_US'),
                'name_ar': self._tr(combo, 'name', 'ar_001'),
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
                'name_ar': self._tr(attribute, 'name', 'ar_001'),
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
                        'name_ar': self._tr(ptav, 'name', 'ar_001'),
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
            price = float(item.get('price') or template.list_price)
            for modifier in item.get('modifiers') or []:
                price += float(modifier.get('price') or 0) * float(modifier.get('qty') or 1)

            taxes = variant.taxes_id
            if taxes and company:
                taxes = taxes.filtered(lambda t: t.company_id == company) or taxes
            if taxes:
                tax_res = taxes.compute_all(price, currency, qty, product=variant, partner=partner)
                subtotal, subtotal_incl = tax_res['total_excluded'], tax_res['total_included']
            else:
                subtotal = subtotal_incl = price * qty

            amount_total += subtotal_incl
            amount_tax += subtotal_incl - subtotal

            line_vals = {
                'product_id': variant.id,
                'qty': qty,
                'price_unit': price,
                'price_subtotal': subtotal,
                'price_subtotal_incl': subtotal_incl,
                'discount': 0.0,
                'tax_ids': [(6, 0, taxes.ids if taxes else [])],
                'full_product_name': self._as_text(item.get('name')) or variant.name,
            }
            if line_note_field and item.get('note'):
                line_vals[line_note_field] = self._as_text(item.get('note'))
            lines.append((0, 0, line_vals))

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
        note_field = self._first_field('pos.order', ['general_note', 'note'])
        if note_field and order_note:
            pos_vals[note_field] = order_note

        pos_order = env['pos.order'].sudo().create(pos_vals)

        # Register a payment so the order is marked paid (shows as a real order).
        method = (session.payment_method_ids[:1]
                  or config.payment_method_ids[:1]
                  or env['pos.payment.method'].sudo().search([('company_id', '=', company.id)], limit=1))
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
            price = float(item.get('price') or template.list_price)

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

        note_bits = []
        if order.get('order_type'):
            note_bits.append(f"Type: {order['order_type']}")
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
        sale_order = request.env['sale.order'].sudo().browse(order_id)
        if not sale_order.exists():
            return self._json({'success': False, 'error': 'Order not found'}, status=404)

        if status in ('canceled', 'cancelled', 'rejected'):
            sale_order._action_cancel() if hasattr(sale_order, '_action_cancel') else sale_order.action_cancel()
            return self._json({'success': True, 'order_id': str(order_id), 'state': sale_order.state})

        if status in ('confirmed', 'accepted') and sale_order.state in ('draft', 'sent'):
            sale_order.action_confirm()
            return self._json({'success': True, 'order_id': str(order_id), 'state': sale_order.state})

        return self._json({'success': True, 'order_id': str(order_id), 'state': sale_order.state,
                           'note': f'No transition for status "{status}"'})
