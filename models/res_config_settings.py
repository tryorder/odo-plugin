from odoo import models, fields, api

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # Tenant for the connector
    connector_tenant = fields.Char(
        string="Tenant",
        config_parameter="order_connector.tenant"
    )

    # Enable Test Mode
    connector_test_mode = fields.Boolean(
        string="Enable Test Mode",
        config_parameter="order_connector.test_mode"
    )
