# -*- coding: utf-8 -*-
{
    'name': 'Order Connector',
    'version': '2.0',
    'category': 'Sales/Point of Sale',
    'summary': 'Two-way integration bridge between Odoo and the TryOrder platform',
    'description': """
Order Connector
===============

Exposes a small, API-key protected HTTP API that the TryOrder (service-pos)
platform consumes as a normal provider:

* GET  /order_connector/ping              - health / credential check
* GET  /order_connector/branches          - list POS branches (pos.config)
* GET  /order_connector/catalog           - full menu (categories + products + modifiers)
* POST /order_connector/orders            - create an order in Odoo (sale.order)
* PUT  /order_connector/orders/<id>/status- update / cancel an order

It also pushes order status changes back to the platform webhook
(<gateway>/webhook/odoo) whenever a sale.order or pos.order changes state.

No external OCA dependency (queue_job) is required: outbound webhooks are sent
through a post-commit hook so they never block the POS.
""",
    'author': 'TryOrder',
    'website': 'https://tryorder.com',
    'license': 'LGPL-3',
    'depends': ['base', 'product', 'point_of_sale', 'sale_management', 'pos_sale'],
    'installable': True,
    'application': True,
    'auto_install': False,
    'images': ['static/description/icon.png'],
    'data': [
        'security/ir.model.access.csv',
        'views/res_config_settings_view.xml',
        'views/connector_log_views.xml',
        'views/pos_order_views.xml',
    ],
}
