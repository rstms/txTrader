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
    install_requires=['click==7.1.2', 'hexdump==3.3', 'pytz==2020.1', 'twisted==20.3.0', 'tzlocal==2.1', 'ujson==3.1.0'],
    tests_require=[
        'txtrader-client==1.5.4', 'txtrader-monitor==1.1.7', 'pytest==6.0.1', 'requests==2.24.0', 'pybump==1.2.5',
        'tox==3.19.0', 'twine==3.2.0', 'wheel==0.34.2', 'yapf==0.30.0', 'wait-for-it==2.1.0'
    ],
    entry_points={'console_scripts': ['txtraderd=txtrader.daemon:txtraderd']},
    include_package_data=True,
    package_data={'': ['*.tac']},
)
