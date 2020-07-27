#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
  __init__.py
  -----------

  TxTrader module init

  Copyright (c) 2015 Reliance Systems Inc. <mkrueger@rstms.net>
  Licensed under the MIT license.  See LICENSE for details.

"""

__all__ = ['version', 'tcpserver', 'webserver', 'rtx', 'client', 'monitor']
from .version import VERSION, DATE, TIME
from .revision import REVISION
LABEL = 'TxTrader Securities Trading API Controller'
HEADER = f"{LABEL} {VERSION} {DATE} {TIME}"
