# -*- coding: utf-8 -*-
"""
  setup.py
  --------

  TxTrader setup script

  Copyright (c) 2020 Reliance Systems Inc. <mkrueger@rstms.net>
  Licensed under the MIT license.  See LICENSE for details.

"""

import sys
from setuptools import setup, find_packages

if sys.version_info < (3, 7):
    sys.exit('Python < 3.7 is not supported')

from txtrader import VERSION, LABEL

setup(
    name='txTrader',
    version=VERSION,
    description=LABEL,
    author='Matt Krueger',
    author_email='mkrueger@rstms.net',
    url='https://github.com/rstms/txTrader',
    license='MIT',
    packages=find_packages(exclude=('tests', 'docs')),
    install_requires=[
        'twisted', 'ujson', 'hexdump', 'pytz', 'tzlocal', 'Click', 'txtrader-client', 'txtrader-monitor', 'wait-for-it'
    ],
    tests_require=['pytest', 'requests'],
    entry_points={'console_scripts': ['txtraderd=txtrader.daemon:txtraderd']},
    include_package_data=True,
    package_data={'': ['*.tac']},
)
