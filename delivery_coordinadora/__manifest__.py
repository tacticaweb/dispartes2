# -*- coding: utf-8 -*-
{
    'name': 'Delivery - Coordinadora',
    'description': "Seguimiento de Pagos",
    'author': "SOLUCIONES OPEN SOURCE",
    'website': "http://www.solucionesos.com",
    'summary': "Api Connector Coordinadora",
    'version': '0.1',
    "license": "OPL-1",
    'support': 'luis.m.varon@gmail.com',
    'category': 'delivery',
        # any module necessary for this one to work correctly
    'depends': ['delivery', 'mail'],

    # always loaded
    'data': [
        'views/coordina_request_templates.xml',
        'views/delivery_coordina_views.xml',
    #    'views/res_config_settings_views.xml',
        'data/delivery_coordina_data.xml',
            ],
    'qweb': [],
    'installable': True,
}
