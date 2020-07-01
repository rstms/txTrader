# -*- coding: utf-8 -*-
"""
  conftest.py
  -----------

   TxTrader unit/regression test configuration script 

   Copyright (c) 2016 Reliance Systems Inc. <mkrueger@rstms.net>
   Licensed under the MIT license.  See LICENSE for details.
      
"""

import pytest
import subprocess

def pytest_runtest_setup(item):
   assert subprocess.call('ps fax | egrep [d]efunct', shell=True)

def pytest_addoption(parser):
    parser.addoption("--runstaged", action="store_true", default=False, help="run staged order tests")
    parser.addoption("--runalgo", action="store_true", default=False, help="run algo order tests")
    parser.addoption("--runbars", action="store_true", default=True, help="run barchart tests")

def pytest_collection_modifyitems(config, items):
    def modify(option, reason, tag):
        if not config.getoption(option):
            marker = pytest.mark.skip(reason=reason)
            for item in items:
                if tag in item.keywords:
                    item.add_marker(marker)
    modify('--runstaged', 'need --runstaged option to run', 'staged')
    modify('--runalgo', 'need --runalgo option to run', 'algo')
    modify('--runbars', 'need --runbars option to run', 'bars')
