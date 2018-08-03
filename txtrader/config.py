#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
  config.py
  ---------

  TxTrader Config module - Read Config Environment Variables

  Copyright (c) 2015 Reliance Systems Inc. <mkrueger@rstms.net>
  Licensed under the MIT license.  See LICENSE for details.

"""
from os import environ

class Config(object):
    """initialize with label to make all /etc/txtrader vars to use the form TXTRADER_label_VARNAME"""

    def __init__(self, label=''):
        self.label = '' if label else '_%s' % label.upper()

    def get(self, key):
        name = 'TXTRADER%s_%s' % (self.label, key)
        if not name in environ.keys():
            #print('Config.get(%s): %s not found in %s' % (key, name, environ.keys()))
            name = 'TXTRADER_%s' % key
        if not name in environ.keys():
            print('ALERT: Config.get(%s) failed' % key)
        return environ[name]
