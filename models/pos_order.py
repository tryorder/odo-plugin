from odoo import models, api
import requests
import logging

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    _inherit = "pos.order"

    @api.model
    def write(self, vals):
        # Capture old states before updating
        old_states = {order.id: order.state for order in self}

        res = super(PosOrder, self).write(vals)

        # Check after update
        for order in self:
            old_state = old_states.get(order.id)
            new_state = order.state

            allowed_states = ["paid", "done", "cancel"]  # adjust for POS

            if old_state != new_state and new_state in allowed_states:
                # Trigger async webhook with retry
                self.with_delay(queue_name='webhook', max_retries=5, retry_delay=60)._send_status_webhook_async(
                    order.id, old_state, new_state
                )

        return res

    def _send_status_webhook_async(self, order_id, old_state, new_state):
        """Async job to send webhook with retry support"""
        order = self.browse(order_id)
        params = self.env['ir.config_parameter'].sudo()

        tenant = params.get_param('order_connector.tenant')
        test_mode = params.get_param('order_connector.test_mode') == 'True'

        url = "https://api.order-lab.online/webhook/odoo" if test_mode else "https://app.tryordersystem.com/webhook/odoo"

        payload = {
            "event_type": "status_updated",
            "order_id": order.id,
            "name": order.name,
            "old_status": old_state,
            "new_status": new_state,
            "customer": order.partner_id.name,
            "amount_total": order.amount_total,
        }

        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            _logger.info("Webhook sent successfully for Order %s (new state: %s)", order.name, new_state)
        except Exception as e:
            _logger.error("Webhook failed for Order %s: %s. Retrying...", order.name, str(e))
            # Raise exception to trigger retry
            raise