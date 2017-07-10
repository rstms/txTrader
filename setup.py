# -*- coding: utf-8 -*-
"""
  setup.py
  --------

  TxTrader setup script

  Copyright (c) 2015 Reliance Systems Inc. <mkrueger@rstms.net>
  Licensed under the MIT license.  See LICENSE for details.

"""

from distutils.core import setup
from txtrader.version import VERSION, LABEL
setup(
  name='txTrader',
  version=VERSION,
  description=LABEL,
  author='Matt Krueger',
  author_email='mkrueger@rstms.net',
  url='https://github.com/rstms/txTrader',
  license = 'MIT',
  packages=['txtrader'],
  package_dir={'txtrader': 'txtrader'},
)

