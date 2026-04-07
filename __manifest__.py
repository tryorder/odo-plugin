# -*- coding: utf-8 -*-
{
    'name': 'Order Connector',
    'version': '1.1',
    'category': 'Sales/Sales',
    'summary': 'Sync POS products and categories with Order',
    'description': 'Sync POS products and categories with Order',
    'author': 'Order',
    'website': 'https://tryorder.com',
    'license': 'LGPL-3',
    'depends': ['base', 'pos_sale', 'product', 'point_of_sale', 'sale_management'],
    'installable': True,
    'application': True,
    'auto_install': False,
    'images': ['static/description/icon.png'],
    "data": [
        # "views/pos_sync_templates.xml",
        #'views/res_config_settings_view.xml',
        "views/pos_sync_menu.xml"
    ],
    "assets": {
        "point_of_sale.assets": [
            "order_connector/static/src/xml/pos_sync_templates.xml",
            "order_connector/static/src/js/PosSyncPage.js",
        ],
        "web.assets_backend": [
            "order_connector/static/src/xml/pos_sync_templates.xml",
            "order_connector/static/src/js/PosSyncPage.js",
        ]
    }
}