#!/usr/bin/env python

from txtrader.client import API

def test_output():
  api=API('rtx')
  print api.help()
  account = api.query_accounts()[0]
  print 'set_account: %s' % api.set_account(account)

  print api.add_symbol('IBM')

if __name__=='__main__':
  test_output()
