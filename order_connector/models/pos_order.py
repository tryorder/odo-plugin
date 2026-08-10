# -*- coding: utf-8 -*-
from odoo import models, fields


class PosOrder(models.Model):
    _inherit = 'pos.order'

    # Marks POS orders tracked by the TryOrder platform.
    connector_managed = fields.Boolean(
        string="Managed by Order Connector",
        default=False,
        copy=False,
    )
    connector_provider_order_id = fields.Char(
        string="TryOrder Order Code",
        copy=False,
    )
    # Latest fulfilment status pushed from the platform (accepted / ready /
    # delivered / ...). Shown as a colored badge in the order header.
    connector_status = fields.Char(
        string="Order Status",
        copy=False,
        index=True,
    )

    def write(self, vals):
        old_states = {order.id: order.state for order in self}
        res = super().write(vals)

        if 'state' in vals:
            allowed_states = ['paid', 'done', 'invoiced', 'cancel']
            for order in self:
                if not order.connector_managed:
                    continue
                old_state = old_states.get(order.id)
                new_state = order.state
                if old_state != new_state and new_state in allowed_states:
                    order._order_connector_notify_status(old_state, new_state)

        return res

    def _order_connector_notify_status(self, old_state, new_state):
        self.ensure_one()
        payload = {
            'type': 'ORDER_UPDATE_WEBHOOK',
            'source': 'pos.order',
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
