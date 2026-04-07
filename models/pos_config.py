from odoo import models

class PosConfig(models.Model):
    _inherit = "pos.config"

    def get_branches(self):
        """
        Return all POS branches (pos.config).
        This will be callable via /web/dataset/call_kw
        """
        branches = self.sudo().search([])
        return [
            {
                "id": branch.id,
                "name": branch.name,
                "company_id": branch.company_id.id if branch.company_id else False,
            }
            for branch in branches
        ]
