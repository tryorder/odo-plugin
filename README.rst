========
TryOrder
========

.. |badge_license| image:: https://img.shields.io/badge/license-LGPL--3-blue.png
    :target: https://www.gnu.org/licenses/lgpl-3.0-standalone.html
    :alt: License: LGPL-3

|badge_license|

Two-way integration bridge between Odoo and the `TryOrder <https://tryorder.com>`_
ordering platform.

TryOrder turns your Odoo instance into a channel for TryOrder: your POS
products and branches are exported to TryOrder, and orders placed on TryOrder are
created back in Odoo Point of Sale — with prices, discounts, notes, payment type
and live status kept in sync both ways.

.. note::

   This module is the **Odoo side** of the integration and requires a TryOrder
   account. It does nothing on its own.

Features
========

* **Menu / catalog sync** — POS categories, products, variants, modifiers and
  combos, in English and Arabic, with images.
* **Branch-aware menus** — each mapped POS (``pos.config``) receives only its own
  products, honoring the branch company and *Limit Categories* settings.
* **Order sync** — creates a real ``pos.order`` (visible in Point of Sale) with
  line notes, order notes, order type and the correct payment method.
* **Itemized discounts** — Coupon, Wallet and Loyalty Points each appear as their
  own labeled line; free-product coupons sync at price 0.
* **Live status, both ways** — status pushed from TryOrder shows as a colored badge
  on the order; Odoo state changes are pushed back via a non-blocking webhook.
* **Observability** — every inbound call and outbound webhook is logged inside Odoo.

HTTP API
========

All endpoints are protected by a shared API key sent in the ``X-Api-Key`` header
(configured under *Settings > Order Connector*).

===================================================  ============================================
Endpoint                                             Purpose
===================================================  ============================================
``GET  /order_connector/ping``                       Health / credential check
``GET  /order_connector/branches``                   List POS branches (``pos.config``)
``GET  /order_connector/catalog?branch_id=..``       Branch-specific menu
``POST /order_connector/orders``                     Create an order in Odoo
``PUT  /order_connector/orders/<id>/status``         Update / cancel an order
===================================================  ============================================

Installation
============

#. Install the module (Apps > *Order Connector*).
#. Open *Settings > Order Connector* and set the API key shared with TryOrder.
#. In TryOrder, connect the Odoo account and map each branch to a POS.
#. Sync the menu and start receiving orders.

Requirements
============

* Odoo 18 Community.
* Standard modules only: ``point_of_sale``, ``sale_management``, ``pos_sale``.

License
=======

LGPL-3. See ``LICENSE``.

Support
=======

support@tryorder.com — https://tryorder.com
