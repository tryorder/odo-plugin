# -*- coding: utf-8 -*-
{
    'name': 'TryOrder',
    # Odoo Apps Store requires the version to be prefixed with the Odoo
    # series: <series>.<major>.<minor>.<patch>.<build>.
    'version': '16.0.2.0.0',
    'category': 'Sales/Point of Sale',
    'summary': 'Two-way POS integration between Odoo and the TryOrder ordering platform',
    'description': """
TryOrder
========

Connect your Odoo Point of Sale to the TryOrder ordering platform.

TryOrder turns your Odoo instance into a channel for the TryOrder platform: your
POS products and branches are exported to TryOrder, and orders placed on TryOrder
are created back in Odoo Point of Sale - with prices, discounts, notes, payment
type and live status kept in sync both ways.

Requires a TryOrder account. This module is the Odoo side of the integration and
does nothing on its own.

Features
--------

* Menu / catalog sync: POS categories, products, variants, modifiers and combos,
  in English and Arabic, with images.
* Branch-aware menus: each mapped POS (pos.config) receives only its own products,
  honoring the branch company and its Limit Categories settings.
* Order sync: creates a real pos.order (visible in Point of Sale) with line notes,
  order notes, order type and the correct payment method.
* Itemized discounts: Coupon, Wallet and Loyalty Points each appear as their own
  labeled line; free-product coupons sync at price 0.
* Live status, both ways: status pushed from TryOrder shows as a colored badge on
  the order; Odoo state changes are pushed back via a non-blocking webhook.
* Built-in observability: every inbound call and outbound webhook is logged inside
  Odoo.

The integration is exposed as a small, API-key protected HTTP API:

* GET  /order_connector/ping                     - health / credential check
* GET  /order_connector/branches                 - list POS branches (pos.config)
* GET  /order_connector/catalog?branch_id=..     - branch-specific menu
* POST /order_connector/orders                   - create an order in Odoo
* PUT  /order_connector/orders/<id>/status       - update / cancel an order

No external OCA dependency (queue_job) is required: outbound webhooks are sent
through a post-commit hook so they never block the POS.
""",
    'author': 'TryOrder',
    'maintainer': 'TryOrder',
    'website': 'https://tryorder.com',
    'support': 'support@tryorder.com',
    'license': 'LGPL-3',
    'depends': ['base', 'product', 'point_of_sale', 'sale_management', 'pos_sale'],
    'installable': True,
    'application': True,
    'auto_install': False,
    # First image is the store listing banner; add screenshots here as you
    # produce them (static/description/screenshot_*.png).
    'images': ['static/description/icon.png'],
    'data': [
        'security/ir.model.access.csv',
        'views/res_config_settings_view.xml',
        'views/connector_log_views.xml',
    ],
}
