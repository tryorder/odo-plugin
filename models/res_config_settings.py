# -*- coding: utf-8 -*-
import secrets

from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # Tenant identifier on the TryOrder platform (e.g. "dev196").
    connector_tenant = fields.Char(
        string="Tenant",
        config_parameter="order_connector.tenant",
    )

    # Shared secret the platform must send in the X-Api-Key header on every
    # inbound request (catalog, branches, orders, ...).
    connector_api_key = fields.Char(
        string="API Key",
        config_parameter="order_connector.api_key",
    )

    # Base URL of the TryOrder API gateway, e.g.
    # https://order-api-gateway.karim-group.org
    # Outbound status webhooks are posted to <base_url>/webhook/odoo.
    connector_gateway_base_url = fields.Char(
        string="Gateway Base URL",
        config_parameter="order_connector.gateway_base_url",
    )

    # Optional secret echoed back to the platform so it can verify our
    # outbound webhooks (sent as X-Webhook-Secret).
    connector_webhook_secret = fields.Char(
        string="Outbound Webhook Secret",
        config_parameter="order_connector.webhook_secret",
    )

    def action_order_connector_generate_api_key(self):
        """Generate a fresh random API key and store it as a system parameter."""
        self.ensure_one()
        key = secrets.token_urlsafe(32)
        self.env['ir.config_parameter'].sudo().set_param('order_connector.api_key', key)
        self.connector_api_key = key
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }
