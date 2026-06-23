# -*- coding: utf-8 -*-
from odoo import models, fields


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # Marks orders that originated from / are tracked by the TryOrder platform.
    connector_managed = fields.Boolean(
        string="Managed by Order Connector",
        default=False,
        copy=False,
    )
    # The platform's order code (order_code) so logs are traceable on both ends.
    connector_provider_order_id = fields.Char(
        string="TryOrder Order Code",
        copy=False,
    )

    def write(self, vals):
        old_states = {order.id: order.state for order in self}
        res = super().write(vals)

        if 'state' in vals:
            for order in self:
                if not order.connector_managed:
                    continue
                old_state = old_states.get(order.id)
                new_state = order.state
                if old_state != new_state:
                    order._order_connector_notify_status(old_state, new_state)

        return res

    def _order_connector_notify_status(self, old_state, new_state):
        self.ensure_one()
        payload = {
            'type': 'ORDER_UPDATE_WEBHOOK',
            'source': 'sale.order',
            'data': {
                'order_id': str(self.id),
                'provider_order_id': self.connector_provider_order_id or '',
                'order_status': new_state,
                'old_status': old_state,
                'name': self.name,
                'amount_total': self.amount_total,
                'customer': self.partner_id.name if self.partner_id else None,
            },
        }
        self.env['order.connector.webhook'].notify_after_commit(payload)
