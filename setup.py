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
        'attrs==19.3.0', 'Automat==20.2.0', 'certifi==2020.6.20', 'chardet==3.0.4', 'click==7.1.2',
        'constantly==15.1.0', 'hexdump==3.3', 'hyperlink==19.0.0', 'idna==2.10', 'incremental==17.5.0',
        'PyHamcrest==2.0.2', 'pytz==2020.1', 'requests==2.24.0', 'six==1.15.0', 'Twisted==20.3.0',
        'txtrader-client>=1.5.4', 'txtrader-monitor>=1.1.3', 'tzlocal==2.1', 'ujson==3.0.0', 'urllib3==1.25.10',
        'wait-for-it==2.0.1', 'zope.interface==5.1.0'
    ],
    tests_require=['pytest', 'requests'],
    entry_points={'console_scripts': ['txtraderd=txtrader.daemon:txtraderd']},
    include_package_data=True,
    package_data={'': ['*.tac']},
)
