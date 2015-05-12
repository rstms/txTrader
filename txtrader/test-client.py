# -*- coding: utf-8 -*-
"""
  test-client.py
  --------------

  TxTrader unit test script

  Copyright (c) 2015 Reliance Systems Inc. <mkrueger@rstms.net>
  Licensed under the MIT license.  See LICENSE for details.

"""


from txtrader.client import API

def test_add_symbol():
  #gw=API('rccg')
  #assert gw.add_symbol('USA')
  #assert not gw.add_symbol('fnord')

  gw=API('tws')
  accounts=gw.query_accounts()
  assert gw.set_account(accounts[0])
  assert gw.add_symbol('TSLA')
  assert not gw.add_symbol('fnord')

if __name__=='__main__':
  test_add_symbol()
