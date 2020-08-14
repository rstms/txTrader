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
from sys import exit

defaults = {
    "API_ACCOUNT": 'API_ACCOUNT',
    "API_CLIENT_ID": 0,
    "API_HOST": '127.0.0.1',
    "API_PORT": 51070,
    "API_ROUTE": "DEMO",
    "API_TIMEZONE": "US/Eastern",
    "DEBUG_API_MESSAGES": 0,
    "GATEWAY_DISCONNECT_TIMEOUT": 30,
    "GATEWAY_DISCONNECT_SHUTDOWN": 1,
    "ENABLE_BARCHART": 1,
    "ENABLE_SYMBOL_BARCHART": 0,
    "ENABLE_EXECUTION_ACCOUNT_FORMAT": 1,
    "ENABLE_HIGH_LOW": 1,
    "ENABLE_SECONDS_TICK": 1,
    "ENABLE_TICKER": 0,
    "ENABLE_EXCEPTION_HALT": 0,
    "ENABLE_AUTO_RESET": 1,
    "LOCAL_RESET_TIME": "05:00",
    "GET_BACKOFF_FACTOR": .1,
    "GET_RETRIES": 8,
    "HOST": "127.0.0.1",
    "HTTP_PORT": 50070,
    "LOG_LEVEL": "WARN",
    "LOG_API_MESSAGES": 0,
    "LOG_CLIENT_MESSAGES": 0,
    "LOG_CXN_EVENTS": 0,
    "LOG_HTTP_REQUESTS": 1,
    "LOG_HTTP_RESPONSES": 1,
    "LOG_RESPONSE_TRUNCATE": 96,
    "LOG_ORDER_UPDATES": 1,
    "LOG_ORDER_UPDATE_DUPS": 0,
    "LOG_EXECUTION_UPDATES": 1,
    "LOG_CALLBACK_METRICS": 0,
    "MODE": "rtx",
    "SUPPRESS_ERROR_CODES": 2100,
    "TCP_PORT": 50090,
    "TESTING": 0,
    "TIME_OFFSET": 0,
    "TIMEOUT_ACCOUNT": 15,
    "TIMEOUT_ADDSYMBOL": 15,
    "TIMEOUT_BARCHART": 10,
    "TIMEOUT_DEFAULT": 30,
    "TIMEOUT_ORDER": 300,
    "TIMEOUT_ORDERSTATUS": 3600,
    "TIMEOUT_POSITION": 30,
    "TIMEOUT_TIMER": 30,
    "USERNAME": "txtrader_user",
    "PASSWORD": "change_this_password",
}


class Config(object):
    """initialize with label to make all /etc/txtrader vars to use the form TXTRADER_label_VARNAME"""

    def __init__(self, label='', output=print):
        self.label = '' if label else '_%s' % label.upper()
        self.output = output

    def get(self, key):
        prefix = 'TXTRADER%s_' % (self.label)
        source = 'env'
        value = environ.get('TXTRADER%s_%s' % (self.label, key))
        if not value:
            value = environ.get('TXTRADER_%s' % key)
            if not value:
                source = 'internal'
                value = defaults[key]
                if value == None:
                    self.output('ALERT: Config.get(%s) failed' % key)
                    exit(1)
        default = ' (default)' if value == defaults[key] else ''
        self.output(f"config {key}={'XXXXXXXX' if 'PASSWORD' in key else value} {source}{default}")
        return value
