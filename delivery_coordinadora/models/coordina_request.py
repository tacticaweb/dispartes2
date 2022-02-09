# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
import base64
from binascii import a2b_base64
import io
import logging
import re
import requests
from lxml import html
from PyPDF2 import PdfFileWriter, PdfFileReader
from xml.etree import ElementTree as etree
from werkzeug.urls import url_join

from odoo import _
from odoo.exceptions import UserError
from odoo.tools import float_round

_logger = logging.getLogger(__name__)


COUNTRIES_WITHOUT_POSTCODES = [
    'AO', 'AG', 'AW', 'BS', 'BZ', 'BJ', 'BW', 'BF', 'BI', 'CM', 'CF', 'KM',
    'CG', 'CD', 'CK', 'CI', 'DJ', 'DM', 'GQ', 'ER', 'FJ', 'TF', 'GM', 'GH',
    'GD', 'GN', 'GY', 'HK', 'IE', 'JM', 'KE', 'KI', 'MO', 'MW', 'ML', 'MR',
    'MU', 'MS', 'NR', 'AN', 'NU', 'KP', 'PA', 'QA', 'RW', 'KN', 'LC', 'ST',
    'SC', 'SL', 'SB', 'SO', 'ZA', 'SR', 'SY', 'TZ', 'TL', 'TK', 'TO', 'TT',
    'TV', 'UG', 'AE', 'VU', 'YE', 'ZW'
]

def _grams(kilograms):
    return int(kilograms * 1000)


class CoordinaRequest():

    def __init__(self, prod_environment, debug_logger):
        self.debug_logger = debug_logger
        if prod_environment:
            self.base_url = 'http://sandbox.coordinadora.com/agw/ws/guias/1.6/server.php'
        else:
            self.base_url = 'http://sandbox.coordinadora.com/agw/ws/guias/1.6/server.php'

    def check_required_value(self, recipient, shipper, order=False, picking=False):
        recipient_required_fields = ['city', 'country_id', 'zip']
        if not recipient.street and not recipient.street2:
            recipient_required_fields.append('street')
        shipper_required_fields = ['city', 'zip', 'country_id']
        if not shipper.street and not shipper.street2:
            shipper_required_fields.append('street')

        res = [field for field in recipient_required_fields if not recipient[field]]
        if res:
            return _("The recipient address is incomplete or wrong (Missing field(s):  \n %s)") % ", ".join(res).replace("_id", "")
        
        res = [field for field in shipper_required_fields if not shipper[field]]
        if res:
            return _("The address of your company/warehouse is incomplete or wrong (Missing field(s):  \n %s)") % ", ".join(res).replace("_id", "")
        
        if order:
            if order.order_line and all(order.order_line.mapped(lambda l: l.product_id.type == 'service')):
                return _("The estimated shipping price cannot be computed because all your products are service.")
            if not order.order_line:
                return _("Please provide at least one item to ship.")
            error_lines = order.order_line.filtered(lambda line: not line.product_id.weight and not line.is_delivery and line.product_id.type != 'service' and not line.display_type)
            if error_lines:
                return _("The estimated shipping price cannot be computed because the weight is missing for the following product(s): \n %s") % ", ".join(error_lines.product_id.mapped('name'))
        return False

    def _parse_address(self, partner):
        if partner.street and partner.street2:
            street = '%s %s' % (partner.street, partner.street2)
        else:
            street = partner.street or partner.street2
        match = re.match(r'^(.*?)(\S*\d+\S*)?\s*$', street, re.DOTALL)
        street = match.group(1)
        street_number = match.group(2)  # None if no number found
        if street_number and len(street_number) > 8:
            street = match.group(0)
            street_number = None
        return (street, street_number)

    def send_shipping(self, picking, carrier):

        receiver = picking.partner_id
        receiver_company = receiver.commercial_partner_id.name if receiver.commercial_partner_id != receiver else ''
        sender = picking.picking_type_id.warehouse_id.partner_id
        boxes = self._compute_boxes(picking, carrier)

        ###### need to change the get_rate !!!!!!!!!!
    
        # Announce shipment to bpost
        reference_id = str(picking.name.replace("/", "", 2))[:50]
        ss, sn = self._parse_address(sender)
        rs, rn = self._parse_address(receiver)

        # bpsot only allow a zip with a size of 8 characters. In some country
        # (e.g. brazil) the postalCode could be longer than 8. In this case we
        # set the zip in the locality.
        receiver_postal_code = receiver.zip
        receiver_locality = receiver.city

        # Some country do not use zip code (Saudi Arabia, Congo, ...). Bpost
        # always require at least a zip or a PO box.
        if not receiver_postal_code:
            receiver_postal_code = '/'
        elif len(receiver_postal_code) > 8:
            receiver_locality = '%s %s' % (receiver_locality, receiver_postal_code)
            receiver_postal_code = '/'

        if receiver.state_id:
            receiver_locality = '%s, %s' % (receiver_locality, picking.partner_id.state_id.display_name)

        values = {'id_cliente': carrier.sudo().coordina_id,
                  'reference': picking.origin,
                  'sender': {'nit': sender.vat,
                             'nombre': sender.name,
                             'telefono': sender.phone,
                             'ciudad': sender.zip,
                             'streetName': ss,
                             'number': sn,
                             },
                  'receiver': {'nit': receiver.vat,
                               'nombre': receiver.name,
                               'telefono': receiver.phone,
                               'ciudad': receiver.zip,
                               'streetName': rs,
                               'number': rn,
                               },
                  "valor": 50000,
                  "codigo_cuenta": 2,
                  "codigo_producto": 0,
                  "nivel_servicio": 1,
                  "contenido": "Productos Calzado",
                  "observaciones": "Odoo",
                  "forma_pago": 1,
                  "carrier_user": carrier.sudo().coordina_user,
                  "carrier_pass": carrier.sudo().coordina_pass,
                  }
        xml = carrier.env['ir.qweb']._render('delivery_coordinadora.coordina_shipping_request', values)
        print ("XML: ", xml)
        code, response = self._send_request('send', xml.encode())
        print ("code: ", code, "response: ", response)
        if code != 201 and response:
            raise UserError(response)
        return True

    def _split_labels(self, labels, ns):

        def _get_page(src_pdf, page_nums):
            with io.BytesIO(base64.b64decode(src_pdf)) as stream:
                try:
                    pdf = PdfFileReader(stream)
                    writer = PdfFileWriter()
                    for page in page_nums:
                        writer.addPage(pdf.getPage(page))
                    stream2 = io.BytesIO()
                    writer.write(stream2)
                    return a2b_base64(base64.b64encode(stream2.getvalue()))
                except Exception:
                    _logger.error('Error ')
                    return False

        barcodes = labels.findall("ns1:barcode", ns)
        src_pdf = labels.find("ns1:bytes", ns).text

        # return barcodes ends with '050'
        main_indeces = [index for index, barcode in enumerate(barcodes) if barcode.text[-3:] != '050']
        return_indeces = [index for index, barcode in enumerate(barcodes) if barcode.text[-3:] == '050']

        main_label = {
            'tracking_codes': [barcodes[index].text for index in main_indeces],
            'label': _get_page(src_pdf, main_indeces)
        }

        return_label = False
        if len(barcodes) > 1:
            return_label = {
                'tracking_codes': [barcodes[index].text for index in return_indeces],
                'label': _get_page(src_pdf, return_indeces)
            }

        return (main_label, return_label)

    def _send_request(self, action, xml, reference=None, with_return_label=False):
        METHODS = {'POST'}
        HEADERS = {'content-Type': 'text/xml'}
        
        URLS = self.base_url
        self.debug_logger("%s\n%s\n%s" % (URLS, HEADERS, xml if xml else None), 'coordina_request_%s' % action)
        try:
            response = requests.post(url=URLS, data=xml, headers=HEADERS, timeout=15)
        except requests.exceptions.Timeout:
            raise UserError(_('El servicio de mensajeria Coordinadora no responde, intentelo mas tarde.'))
        self.debug_logger("%s\n%s" % (response.status_code, response.text), 'coordina_response_%s' % action)

        return response.status_code, response.text

    def _compute_boxes(self, picking, carrier):
        """Group the move lines in the picking to different boxes.

        Lines with the same result_package_id belong to the same box,
        and lines without result_package_id are assigned to one box.
        This method returns a list of summary of each box which will be
        used in creating the request in making order in bpost.
        """
        boxes = []
        for package in picking.package_ids:
            package_lines = picking.move_line_ids.filtered(lambda sml: sml.result_package_id.id == package.id)
            parcel_value = sum(sml.sale_price for sml in package_lines)
            weight_in_kg = 0
            boxes.append({
                'weight': str(_grams(weight_in_kg)),
                'parcelValue': max(min(int(parcel_value*100), 2500000), 100),
                'contentDescription': ' '.join(["%d %s" % (line.qty_done, re.sub('[\W_]+', ' ', line.product_id.name or '')) for line in package_lines])[:50],
            })
        lines_without_package = picking.move_line_ids.filtered(lambda sml: not sml.result_package_id)
        if lines_without_package:
            parcel_value = sum(sml.sale_price for sml in lines_without_package)
            weight_in_kg = 0
            boxes.append({
                'weight': str(_grams(weight_in_kg)),
                'parcelValue': max(min(int(parcel_value*100), 2500000), 100),
                'contentDescription': ' '.join(["%d %s" % (line.qty_done, re.sub('[\W_]+', ' ', line.product_id.name or '')) for line in lines_without_package])[:50],
            })
        return boxes

    def _compute_return_boxes(self, picking, carrier):
        weight = sum(move.product_qty * move.product_id.weight for move in picking.move_lines)
        weight_in_kg = carrier._bpost_convert_weight(weight)
        parcel_value = sum(move.product_qty * move.product_id.lst_price for move in picking.move_lines)
        boxes = [{
            'weight': str(_grams(weight_in_kg)),
            'parcelValue': max(min(int(parcel_value*100), 2500000), 100),
            'contentDescription': ' '.join(["%d %s" % (line.product_qty, re.sub('[\W_]+', ' ', line.product_id.name or '')) for line in picking.move_lines])[:50],
        }]
        return boxes
