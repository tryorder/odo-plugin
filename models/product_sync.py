from odoo import models, api

class ProductSync(models.Model):
    _inherit = "product.product"

    @api.model
    def pos_sync_products(self):
        """Return a list of products for POS"""
        products = self.search([])
        result = []
        for p in products:
            result.append({
                "id": p.id,
                "name": p.name,
                "price": p.list_price,
                "barcode": p.barcode,
            })
        return result
