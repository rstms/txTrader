#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
  version.py
  ----------

  TxTrader version module 

  Copyright (c) 2015 Reliance Systems Inc. <mkrueger@rstms.net>
  Licensed under the MIT license.  See LICENSE for details.

"""

VERSION_MAJOR = 1
VERSION_MINOR = 12 
VERSION_PATCH = 0
BUILD=2406
DATE='2020-03-11'
TIME='13:29:31'
VERSION = '%s.%s.%s' % (VERSION_MAJOR, VERSION_MINOR, VERSION_PATCH)
DATETIME = '%s %s' % (DATE, TIME)
LABEL = 'TxTrader Securities Trading API Controller'
HEADER = '%s %s (build %s) %s' % (LABEL, VERSION, BUILD, DATETIME)
COMMIT='commit ef96247825f3078ae09b69b3d631046d29f50193 (HEAD -> refs/heads/master, refs/remotes/origin/master, refs/remotes/origin/HEAD)'
