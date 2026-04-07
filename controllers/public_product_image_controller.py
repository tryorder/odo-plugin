from odoo import http
from odoo.http import request
import base64

class PublicProductImageControlle(http.Controller):
    @http.route('/public/product/image/<int:product_id>', type='http', auth='public')
    def product_image(self, product_id, **kwargs):
        product = request.env['product.product'].sudo().browse(product_id)
        if product and product.image_512:
            image_data = base64.b64decode(product.image_256)
            return request.make_response(image_data, [
                ('Content-Type', 'image/png'),
                ('Content-Length', len(image_data))
            ])
        return request.not_found()
