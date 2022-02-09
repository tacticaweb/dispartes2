# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import Warning, UserError
from odoo.osv import osv
from odoo.http import request
import time
import math
from datetime import datetime, date, time, timedelta
import sys
import pytz
import json

from .coordina_request import CoordinaRequest

class DeliveryCoordinadora(models.Model):
    _inherit = 'delivery.carrier'

    delivery_type = fields.Selection(selection_add=[
        ('coordina', 'Coordinadora')
    ], ondelete={'coordina': lambda recs: recs.write({'delivery_type': 'fixed', 'fixed_price': 0})})
    coordina_id = fields.Char("Id Cliente", groups="base.group_system", help="Enter your Id Cliente from Coordinadora account.")
    coordina_user = fields.Char("API User", groups="base.group_system", help="Enter your API User from Coordinadora account.")
    coordina_pass = fields.Char("API Pass", groups="base.group_system", help="Enter your API Password from Coordinadora account.")
    coordina_delivery_type = fields.Char('Coordinadora Carrier Type')
    coordina_default_packaging_id = fields.Many2one("stock.package.type", string="Default Package Type for Coordinadora")
    
    def coordina_get_tracking_link(self, picking):
        return 'https://www.fedex.com/apps/fedextrack/?action=track&trackingnumber=%s' % picking.carrier_tracking_ref
    
    def coordina_rate_shipment(self, order):
        price = 0
        return {'success': True,
                'price': price,
                'error_message': False,
                'warning_message': False}
    
    def coordina_send_shipping(self, pickings):
        res = []
        coordina = CoordinaRequest(self.prod_environment, self.log_xml)
        for picking in pickings:
            check_value = coordina.check_required_value(picking.partner_id, picking.picking_type_id.warehouse_id.partner_id, picking=picking)
            if check_value:
                raise UserError(check_value)
            shipping = coordina.send_shipping(picking, self)
            order = picking.sale_id
            company = order.company_id or picking.company_id or self.env.company
            order_currency = picking.sale_id.currency_id or picking.company_id.currency_id
            if order_currency.name == "EUR":
                carrier_price = shipping['price']
            else:
                quote_currency = self.env['res.currency'].search([('name', '=', 'EUR')], limit=1)
                carrier_price = quote_currency._convert(shipping['price'], order_currency, company, order.date_order or fields.Date.today())
            carrier_tracking_ref = TRACKING_REF_DELIM.join(shipping['main_label']['tracking_codes'])
            tracking_links = '<br/>'.join(self._tracking_link_element(code) for code in shipping['main_label']['tracking_codes'])
            logmessage = (_("Shipment created into bpost <br/> <b>Tracking Links</b> <br/>%s") % (tracking_links))
            bpost_labels = [('Labels-bpost.%s' % self.bpost_label_format, shipping['main_label']['label'])]
            if picking.sale_id:
                for pick in picking.sale_id.picking_ids:
                    pick.message_post(body=logmessage, attachments=bpost_labels)
            else:
                picking.message_post(body=logmessage, attachments=bpost_labels)

            if shipping['return_label']:
                carrier_return_label_ref = TRACKING_REF_DELIM.join(shipping['return_label']['tracking_codes'])
                logmessage = (_("Return labels created into bpost <br/> <b>Tracking Numbers: </b><br/>%s") % (carrier_return_label_ref))
                picking.message_post(body=logmessage, attachments=[('%s-%s.%s' % (self.get_return_label_prefix(), 1, self.bpost_label_format), shipping['return_label']['label'])])

            shipping_data = {'exact_price': carrier_price,
                             'tracking_number': carrier_tracking_ref}
            res = res + [shipping_data]
        return res
