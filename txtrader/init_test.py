# -*- coding: utf-8 -*-
"""
  init-test.py
  --------------

  TxTrader unit/regression test script

  Copyright (c) 2016 Reliance Systems Inc. <mkrueger@rstms.net>
  Licensed under the MIT license.  See LICENSE for details.

"""
import txtrader.rtx

import subprocess
import os
import signal
import time

import simplejson as json
from pprint import pprint
import pytest
import re
import datetime

@pytest.fixture(scope='module')
def api():
    with Server() as s:
        yield s.init()


def my_gethostname_test():
    return 'txtrader-test-host'

def my_gethostname_prod():
    return 'txtrader-prod-host'


class my_log():
    def __init__(self):
        pass

    def msg(self, msg):
        print('msg: %s' % msg)

    def err(self, msg):
        print('err: %s' % msg)

def test_init_with_time_offset():
    print()
    os.environ['TXTRADER_TIME_OFFSET']='900'
    txtrader.rtx.gethostname = my_gethostname_test
    txtrader.rtx.log = my_log()
    rtx=txtrader.rtx.RTX()
    assert rtx.time_offset
    txtrader.rtx.gethostname = my_gethostname_prod
    rtx=txtrader.rtx.RTX()
    assert not rtx.time_offset
