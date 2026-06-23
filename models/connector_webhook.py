# -*- coding: utf-8 -*-
import logging

import requests

from odoo import models

_logger = logging.getLogger(__name__)


class OrderConnectorWebhook(models.AbstractModel):
    """Shared helper for pushing events to the TryOrder platform gateway.

    Webhooks are posted to ``<gateway_base_url>/webhook/odoo``. Delivery is
    deferred to a post-commit hook so a slow/unreachable gateway never blocks
    the POS or the order write. The hook closes over plain data only (URL,
    headers, body) and never touches the ORM/cursor, which is safe after commit.
    """

    _name = 'order.connector.webhook'
    _description = 'Order Connector Webhook Helper'

    def _build_request(self, payload):
        """Resolve URL/headers/body from config. Returns None if not configured."""
        params = self.env['ir.config_parameter'].sudo()
        base = (params.get_param('order_connector.gateway_base_url') or '').strip()
        if not base:
            _logger.warning("Order Connector: gateway base URL not configured; skipping webhook %s", payload)
            return None

        url = base.rstrip('/') + '/webhook/odoo'
        headers = {'Content-Type': 'application/json'}
        secret = params.get_param('order_connector.webhook_secret')
        if secret:
            headers['X-Webhook-Secret'] = secret

        body = dict(payload)
        body.setdefault('tenant', params.get_param('order_connector.tenant'))
        return url, headers, body

    @staticmethod
    def _deliver(url, headers, body):
        try:
            response = requests.post(url, json=body, headers=headers, timeout=10)
            response.raise_for_status()
            _logger.info("Order Connector webhook delivered: type=%s order_id=%s",
                         body.get('type'), (body.get('data') or {}).get('order_id'))
        except requests.exceptions.RequestException as exc:
            _logger.error("Order Connector webhook failed (%s): %s", url, exc)

    def notify(self, payload):
        """Send immediately (best-effort). Never raises."""
        built = self._build_request(payload)
        if built:
            self._deliver(*built)

    def notify_after_commit(self, payload):
        """Deliver the webhook once the current transaction commits."""
        built = self._build_request(payload)
        if not built:
            return
        url, headers, body = built
        self.env.cr.postcommit.add(lambda: self._deliver(url, headers, body))
