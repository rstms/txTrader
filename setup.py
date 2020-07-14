# -*- coding: utf-8 -*-
"""
  setup.py
  --------

  TxTrader setup script

  Copyright (c) 2020 Reliance Systems Inc. <mkrueger@rstms.net>
  Licensed under the MIT license.  See LICENSE for details.

"""

from setuptools import setup, find_packages

if sys.version_info < (3, 8):
    sys.exit('Python < 3.8 is not supported')

from txtrader.version import VERSION, LABEL

setup(
    name='txTrader',
    version=VERSION,
    description=LABEL,
    author='Matt Krueger',
    author_email='mkrueger@rstms.net',
    url='https://github.com/rstms/txTrader',
    license='MIT',
    packages=find_packages(exclude=('tests', 'docs')),
    install_requires=['twisted', 'ujson', 'hexdump', 'pytz', 'tzlocal', 'Click'],
    tests_require=['pytest', 'requests'],
    entry_points={'console_scripts': ['txtraderd=txtrader.daemon:txtraderd']},
    include_package_data=True,
    package_data={'': ['*.tac']},
)
