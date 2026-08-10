# -*- coding: utf-8 -*-
from odoo import models, fields


class OrderConnectorLog(models.Model):
    """Audit trail of Order Connector traffic:
    inbound  = the platform hit one of our /order_connector/* endpoints,
    outbound = we pushed an event to the platform webhook.
    """

    _name = 'order.connector.log'
    _description = 'Order Connector Log'
    _order = 'create_date desc'
    _rec_name = 'endpoint'

    direction = fields.Selection(
        [('inbound', 'Inbound (endpoint hit)'),
         ('outbound', 'Outbound (webhook push)')],
        string='Direction', index=True,
    )
    method = fields.Char(string='Method')
    endpoint = fields.Char(string='Endpoint / URL', index=True)
    event_type = fields.Char(string='Event')
    status_code = fields.Integer(string='Status')
    success = fields.Boolean(string='Success', index=True)
    remote_addr = fields.Char(string='Remote IP')
    request_body = fields.Text(string='Request Body')
    response_body = fields.Text(string='Response Body')
