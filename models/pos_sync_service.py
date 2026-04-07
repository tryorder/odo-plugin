from odoo import models, api, fields
from datetime import datetime
import requests
import json
import base64
import logging
import re
import html

_logger = logging.getLogger(__name__)

class PosSyncService(models.Model):
    _name = 'pos.sync.service'
    _description = 'POS Sync Service'

    name = fields.Char(default='POS Sync Service', readonly=True)

    @api.model
    def fetch_categories(self):
        """Fetch all POS categories with translations."""
        Category = self.env['pos.category'].sudo()
        categories = Category.search([])
        result = []

        for cat in categories:
            result.append({
                'id': int(cat.id),
                'name': {
                    'ar': cat.with_context(lang='ar_001').name,
                    'en': cat.with_context(lang='en_US').name
                },
                'sequence': cat.sequence,
                'parent_id': int(cat.parent_id.id) if cat.parent_id else None
            })
        return result

    @api.model
    def strip_html(self, html_content):
        """Remove HTML tags, decode entities, normalize spaces."""
        if not html_content:
            return ''
        text = re.sub(r'<[^>]*>', '', html_content)
        text = html.unescape(text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    @api.model
    def get_pos_category_ids(self, product):
        """Return list of POS category IDs for a product."""
        if not product.pos_categ_ids:
            return []
        if hasattr(product.pos_categ_ids, 'mapped'):
            return product.pos_categ_ids.mapped('id')
        return [product.pos_categ_ids.id]

    @api.model
    def fetch_products(self):
        """Fetch products with variants, attributes, and categories."""
        Product = self.env['product.template'].sudo()
        products = Product.search([])
        result = []

        for product in products:
            has_image = bool(product.image_512)

            attributes = []
            for line in product.attribute_line_ids:
                attributes.append({
                    "id": line.attribute_id.id,
                    "name": {
                        'ar': line.attribute_id.with_context(lang='ar_001').name,
                        'en': line.attribute_id.with_context(lang='en_US').name,
                    },
                    "active": line.attribute_id.active,
                    "display_type": line.attribute_id.display_type,
                    "values": [
                        {
                            "id": v.id,
                            "name": {
                                'ar': v.with_context(lang='ar_001').name,
                                'en': v.with_context(lang='en_US').name,
                            },
                            "price_extra": v.price_extra,
                        } for v in line.product_template_value_ids
                    ]
                })

            result.append({
                'id': product.id,
                'type': product.type,
                'name': {
                    'ar': product.with_context(lang='ar_001').name,
                    'en': product.with_context(lang='en_US').name
                },
                'public_description': {
                    'ar': self.strip_html(product.with_context(lang='ar_001').public_description),
                    'en': self.strip_html(product.with_context(lang='en_US').public_description)
                },
                'list_price': product.list_price,
                'active': product.active,
                'available_in_pos': product.available_in_pos,
                'sale_ok': product.sale_ok,
                'purchase_ok': product.purchase_ok,
                'sequence': product.sequence,
                'product_variant_count': product.product_variant_count,
                'image_url': f"{self.env['ir.config_parameter'].sudo().get_param('web.base.url')}/public/product/image/{product.id}" if has_image else None,
                'pos_categ_ids': self.get_pos_category_ids(product),
                "attributes": attributes
            })
        return result

    @api.model
    def sync_products(self):
        """
        Main method to sync POS products & categories to external API.
        Can be called from cron, button, or other server actions.
        """
        params = self.env['ir.config_parameter'].sudo()

        tenant = params.get_param('order_connector.tenant') 
        test_mode = params.get_param('order_connector.test_mode') == 'True'

        url = "https://api.order-lab.online/webhook/odoo" if test_mode else "https://app.tryordersystem.com/webhook/odoo"

        headers = {"Content-Type": "application/json"}

        data = {
            'categories': self.fetch_categories(),
            'products': self.fetch_products()
        }

        json_str = json.dumps(data, separators=(',', ':'))
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"products_{tenant}_{timestamp}.json"

        # Create public attachment
        attachment = self.env['ir.attachment'].sudo().create({
            'name': filename,
            'datas': base64.b64encode(json_str.encode("utf-8")),
            'mimetype': 'application/json',
            'res_model': False,
            'public': True
        })

        base_url = params.get_param('web.base.url')
        file_url = f"{base_url}/web/content/{attachment.id}?download=false"

        payload = {
            'event_type': 'sync',
            'tenant': tenant,
            'file_url': file_url
        }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            response.raise_for_status()
            _logger.info("POS sync success for tenant %s", tenant)

            # Delete attachment
            attachment.sudo().unlink()

            return {"success": True, "file_url": file_url}
        except requests.exceptions.RequestException as e:
            attachment.sudo().unlink()
            _logger.error("POS Sync failed: %s", str(e))
            return {"success": False, "error": str(e), "data": payload}
