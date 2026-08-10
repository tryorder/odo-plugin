# -*- coding: utf-8 -*-
import base64

from odoo import http
from odoo.http import request


class PublicProductImageController(http.Controller):
    """Serves product images publicly so the platform can render menu items by URL."""

    @http.route('/public/product/image/<int:product_id>', type='http', auth='public')
    def product_image(self, product_id, **kwargs):
        product = request.env['product.template'].sudo().browse(product_id)
        if product.exists() and product.image_512:
            image_data = base64.b64decode(product.image_512)
            return request.make_response(image_data, [
                ('Content-Type', 'image/png'),
                ('Content-Length', len(image_data)),
            ])
        return request.not_found()
