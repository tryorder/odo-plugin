# -*- coding: utf-8 -*-
import json
import logging

import requests

import odoo
from odoo import api, models, SUPERUSER_ID

_logger = logging.getLogger(__name__)


class OrderConnectorWebhook(models.AbstractModel):
    """Shared helper for pushing events to the TryOrder platform gateway.

    Webhooks are posted to ``<gateway_base_url>/webhook/odoo``. Delivery is
    deferred to a post-commit hook so a slow/unreachable gateway never blocks
    the POS or the order write. Every push is recorded in order.connector.log.
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
        """POST the event. Returns (status_code, ok, response_text). Never raises."""
        status, ok, resp = 0, False, ''
        try:
            response = requests.post(url, json=body, headers=headers, timeout=10)
            status, ok = response.status_code, response.ok
            resp = (response.text or '')[:10000]
            response.raise_for_status()
            _logger.info("Order Connector webhook delivered: type=%s order_id=%s",
                         body.get('type'), (body.get('data') or {}).get('order_id'))
        except requests.exceptions.RequestException as exc:
            resp = resp or str(exc)
            _logger.error("Order Connector webhook failed (%s): %s", url, exc)
        return status, ok, resp

    @staticmethod
    def _log_vals(url, body, status, ok, resp):
        return {
            'direction': 'outbound',
            'method': 'POST',
            'endpoint': url,
            'event_type': (body or {}).get('type'),
            'status_code': status,
            'success': ok,
            'request_body': json.dumps(body, default=str, ensure_ascii=False)[:10000],
            'response_body': (resp or '')[:10000],
        }

    def notify(self, payload):
        """Send immediately (best-effort) and log. Never raises."""
        built = self._build_request(payload)
        if not built:
            return
        url, headers, body = built
        status, ok, resp = self._deliver(url, headers, body)
        try:
            self.env['order.connector.log'].sudo().create(self._log_vals(url, body, status, ok, resp))
        except Exception:
            _logger.exception('order_connector: outbound log write failed')

    def notify_after_commit(self, payload):
        """Deliver the webhook once the current transaction commits, then log it."""
        built = self._build_request(payload)
        if not built:
            return
        url, headers, body = built
        dbname = self.env.cr.dbname

        def _send():
            status, ok, resp = OrderConnectorWebhook._deliver(url, headers, body)
            # Fresh cursor: the request transaction has already committed here.
            try:
                registry = odoo.registry(dbname)
                with registry.cursor() as cr:
                    env = api.Environment(cr, SUPERUSER_ID, {})
                    env['order.connector.log'].create(
                        OrderConnectorWebhook._log_vals(url, body, status, ok, resp))
                    cr.commit()
            except Exception:
                _logger.exception('order_connector: outbound log write failed')

        self.env.cr.postcommit.add(_send)
