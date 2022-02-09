# -*- coding: utf-8 -*-

from odoo import api, fields, models, _

#class ProductPackaging(models.Model):
#    _inherit = 'product.packaging'

#    package_carrier_type = fields.Selection(selection_add=[('coordina', 'Coordinadora')])
#    coordina_carrier = fields.Char('Carrier Prefix', index=True)

class PackageType(models.Model):
    _inherit = 'stock.package.type'

    package_carrier_type = fields.Selection(selection_add=[('coordina', 'Coordinadora')])