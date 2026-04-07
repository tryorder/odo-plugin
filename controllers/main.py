from odoo import http
from odoo.http import request
from datetime import datetime
from io import BytesIO
import requests
import json
import os
import gzip
import base64
import logging
import re
import html

_logger = logging.getLogger(__name__)


class PosSyncController(http.Controller):

    def _fetch_categories(self):
        """
        Fetch all product categories with their names translated in the given languages.
        Returns only JSON-serializable types.
        """
        Category = request.env['pos.category'].sudo()
        categories = Category.search([])

        # Log the raw categories variable
        _logger.info("Fetched POS categories variable: %s", categories)

        result = []

        for cat in categories:

            result.append({
                'id': int(cat.id),  # ensure integer
                'name': {
                    'ar': cat.with_context(lang='ar_001').name,
                    'en': cat.with_context(lang='en_US').name
                },
                'sequence': cat.sequence,
                'parent_id': int(cat.parent_id.id) if cat.parent_id else None  # int or None
            })

        return result


    def _fetch_variants(self, variants):
     
        result = []
        for variant in variants:
            # Get attribute values linked to the variant
            attributes = []

            for value in variant.product_template_attribute_value_ids:
                attributes.append({
                    "id": value.attribute_id.id,
                    "name": {
                        'ar': value.attribute_id.with_context(lang='ar_001').name,
                        'en': value.attribute_id.with_context(lang='en_US').name
                    },
                    "value": {
                        "id": value.product_attribute_value_id.id,
                        "name": {
                            'ar': value.product_attribute_value_id.with_context(lang='ar_001').name,
                            'en': value.product_attribute_value_id.with_context(lang='en_US').name
                        },
                    },
                })

            result.append({
                "id": variant.id,
                "name": {
                    'ar': variant.with_context(lang='ar_001').name,
                    'en': variant.with_context(lang='en_US').name
                },
                "default_code": variant.default_code,
                "barcode": variant.barcode,
                "list_price": variant.list_price,
                "standard_price": variant.standard_price,
                "weight": variant.weight,
                "volume": variant.volume,
                "active": variant.active,
                "type": variant.type,
                "categ_id": variant.categ_id.id if variant.categ_id else None,
                "product_tmpl_id": variant.product_tmpl_id.id,
                "uom_id": {
                    "id": variant.uom_id.id,
                    "name": variant.uom_id.name,
                } if variant.uom_id else None,
                "uom_po_id": {
                    "id": variant.uom_po_id.id,
                    "name": variant.uom_po_id.name,
                } if variant.uom_po_id else None,
                'product_variant_count': variant.product_variant_count,
                "attributes": attributes,  # linked attributes + values
                "create_date": str(variant.create_date),
                "write_date": str(variant.write_date)
            })

        return result

    def get_variants_by_template(self, variants):
        """
        Fetch all variants for a given product.template ID.
        Returns a list of dictionaries with variant details.
        """

        result = []
        for variant in variants:
            result.append({
                'id': variant.id,
                'name': variant.name,
                'default_code': variant.default_code,
                'list_price': variant.list_price,
                'active': variant.active,
                'available_in_pos': variant.available_in_pos,
            })

        return result

    def _get_pos_category_ids(self, product):
        """
        Return a list of POS category IDs from a product, 
        whether pos_categ_ids is a single record or multiple.
        """
        if not product.pos_categ_ids:
            return []
        
        # If it has 'mapped' method, it's a recordset (Many2many)
        if hasattr(product.pos_categ_ids, 'mapped'):
            return product.pos_categ_ids.mapped('id')
        
        # Otherwise, it's a single record (Many2one)
        return [product.pos_categ_ids.id]

    def _strip_html(self, html_content):
        """Remove HTML tags, decode entities, and strip extra spaces/newlines."""
        if not html_content:
            return ''
        
        # Remove HTML tags
        text = re.sub(r'<[^>]*>', '', html_content)
        
        # Decode HTML entities (&amp; → &, &nbsp; → space, etc.)
        text = html.unescape(text)
        
        # Normalize whitespace (collapse multiple spaces/newlines into one space)
        text = re.sub(r'\s+', ' ', text).strip()
        
        return text

    def _fetch_products(self):
        """Fetch all products with variants and category IDs."""
        Product = request.env['product.template'].sudo()
        products = Product.search([])
        result = []

        # available_in_pos
        for product in products:

            # Get all POS category IDs linked to variants of this template
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
                    'ar': self._strip_html(product.with_context(lang='ar_001').public_description),
                    'en': self._strip_html(product.with_context(lang='en_US').public_description)
                },
                'list_price': product.list_price,
                'active': product.active,
                'available_in_pos': product.available_in_pos,
                'sale_ok': product.sale_ok,
                'purchase_ok': product.purchase_ok,
                'sequence': product.sequence,
               'product_variant_count': product.product_variant_count,
              #  'taxes_id': product.taxes_id,
              #  'image_512': str(product.image_512) if has_image else None,
                'image_url': f"{request.httprequest.host_url}public/product/image/{product.id}"  if has_image else None,
                'pos_categ_ids': self._get_pos_category_ids(product),
                "attributes": attributes
         
            })
        return result

   @http.route('/my_test_route', auth='public', type='http', website=True)
    def my_test_method(self, **kw):
        return "Hello, this is a test page from my Odoo custom module!"

    @http.route('/pos/sync', type='json', auth='user')
    def sync_products(self):

        # Fetch config values
        params = request.env['ir.config_parameter'].sudo()
        tenant = params.get_param('order_connector.tenant') 
        test_mode = params.get_param('order_connector.test_mode')

        # Use debug mode to decide endpoint
        url = "https://api.order-lab.online/webhook/odoo" if test_mode else "https://app.tryordersystem.com/webhook/odoo"
       
        headers = {
            "Content-Type": "application/json",
            # "Authorization": f"Bearer {api_key}" if api_key else ""
        }

        # Build JSON data


        data = {
            'categories': self._fetch_categories(),
            'products': self._fetch_products(),
          #  'variants': self._fetch_variants()
        }

        # Minify JSON (no spaces, no line breaks)
        json_str = json.dumps(data, separators=(',', ':'))

        # Add datetime to filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"products_{tenant}_{timestamp}.json"

        # Create public attachment
        attachment = request.env['ir.attachment'].sudo().create({
            'name': filename,
            'datas': base64.b64encode(json_str.encode("utf-8")),
            'mimetype': 'application/json',
            'res_model': False,  # Not linked to a record
            'public': True       # Make it public
        })

        # Generate public URL for the attachment
        base_url = params.get_param('web.base.url')
        file_url = f"{base_url}/web/content/{attachment.id}?download=false"


        # Prepare payload
        payload = {
            'event_type': 'sync',
            'tenant': tenant,
            'file_url': file_url
        }

        try:
            # Send data to external API
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            response.raise_for_status()
            return {"success": True}
        except requests.exceptions.RequestException as e:
            logging.error("POS Sync failed: %s", str(e))
            return {"success": False, "error": str(e), "data": payload}
