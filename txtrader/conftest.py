# -*- coding: utf-8 -*-
"""
  conftest.py
  -----------

   TxTrader unit/regression test configuration script 

   Copyright (c) 2016 Reliance Systems Inc. <mkrueger@rstms.net>
   Licensed under the MIT license.  See LICENSE for details.
      
"""

import pytest

def pytest_addoption(parser):

    parser.addoption("--runstaged", action="store_true", default=False, help="run staged order tests")
    parser.addoption("--runbars", action="store_true", default=False, help="run barchart tests")

def pytest_collection_modifyitems(config, items):

    if not config.getoption("--runstaged"):
        skip_staged = pytest.mark.skip(reason="need --runstaged option to run")
        for item in items:
            if "slow" in item.keywords:
                item.add_marker(skip_staged)

    if not config.getoption("--runbars"):
        skip_bars= pytest.mark.skip(reason="need --runbars option to run")
        for item in items:
            if "barchart" in item.keywords:
                item.add_marker(skip_bars)
