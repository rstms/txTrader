# -*- coding: utf-8 -*-
"""
  test-txtrader.py
  --------------

  TxTrader unit/regression test script

  Copyright (c) 2016 Reliance Systems Inc. <mkrueger@rstms.net>
  Licensed under the MIT license.  See LICENSE for details.

"""
from txtrader.client import API
import subprocess
import os
import signal
import time

import simplejson as json
import pprint
import pytest

testmode = 'RTX'

from server_test import Server

@pytest.fixture(scope='module')
def api():
    with Server() as s:
        yield s.init()

def dump(label, o):
    print('%s:\n%s' % (label, json.dumps(o, indent=2, separators=(',', ':'))))

def test_init(api):
    print()
    assert api 
    print('waiting 1 second...')
    time.sleep(1)
    print('done')

def test_accounts(api):
    print()
    a = api.query_accounts()
    assert type(a) is list
    assert len(a)
    print('accounts=%s' % repr(a))
    account = a[0]
    assert api.set_account(account)
    info = api.query_account(account)
    assert info
    print('account[%s] info:' % account)
    pp = pprint.PrettyPrinter(indent=2)
    pp.pprint(info)

def test_stock_prices(api):
    #a = api.query_accounts()
    #assert api.set_account(a[0])
    s = api.add_symbol('IBM')
    assert s
    s = api.add_symbol('FNORD')
    assert not s
    s = api.query_symbol('IBM')
    assert s
    dump('Symbol data for IBM', s)

    l = api.query_symbols()
    assert l
    dump('symbol list', l)
    assert l == ['IBM']

    s = api.add_symbol('TSLA')
    assert s
    dump('add TSLA', s)
    s = api.add_symbol('GOOG')
    assert s
    dump('add GOOG', s)
    s = api.add_symbol('AAPL')
    assert s
    dump('add AAPL', s)

    l = api.query_symbols()
    assert set(l) == set(['IBM', 'TSLA', 'GOOG', 'AAPL'])
    dump('symbol list', l)

    s = api.del_symbol('TSLA')
    assert s
    dump('del TSLA', s)

    l = api.query_symbols()
    assert set(l) == set(['IBM', 'GOOG', 'AAPL'])
    dump('symbol list', l)

    print(repr(l))

def test_buy_sell(api):
    print()
    print('buying IBM')
    o = api.market_order('IBM', 100)
    assert o
    assert type(o) == dict
    assert 'permid' in o.keys()
    assert 'status' in o.keys()
    dump('market_order(IBM,100)', o)

    print('selling IBM')

    o = api.market_order('IBM', -100)
    assert o
    assert type(o) == dict
    assert 'permid' in o.keys()
    assert 'status' in o.keys()
    dump('market_order(IBM,100)', o)

def test_status(api):
    assert api.status() == 'Up'

def test_uptime(api):
    uptime = api.uptime()
    assert uptime
    print('uptime: %s' % repr(uptime))
    assert type(uptime) == str or type(uptime) == unicode

def test_version(api):
    assert api.version()

def test_symbol_price(api):
    symbols = api.query_symbols()
    assert type(symbols)==list
    if 'AAPL' in symbols:
        ret = api.del_symbol('AAPL')
        assert ret
    symbols = api.query_symbols()
    assert type(symbols) == list
    assert 'AAPL' not in symbols
    price = api.query_symbol('AAPL')
    assert not price

    ret = api.add_symbol('AAPL')
    assert ret

    p = api.query_symbol('AAPL')
    assert p 
    assert type(p) == dict
    assert p['symbol'] == 'AAPL'


def test_query_accounts(api):
    accounts = api.query_accounts()
    assert type(accounts) == list
    assert accounts

    for a in accounts:
        assert type(a) == str or type(a) == unicode 

    a = accounts[0]
    ret = api.set_account(a)
    assert ret

    #print('query_account(%s)...' % a)
    data = api.query_account(a)
  #print('account[%s]: %s' % (a, repr(data)))
    assert data
    assert type(data)==dict

    if testmode == 'TWS':
        field = 'LiquidationValue'
    elif testmode == 'RTX':
        field = 'CASH_BALANCE'

    sdata = api.query_account(a, field) 
    assert sdata
    assert type(sdata)==dict
    assert set(sdata.keys()) == set([field])
  #print('account[%s]: %s' % (a, repr(sdata)))

def _wait_for_fill(api, oid, return_on_error=False):
    print('waiting for fill...')
    done = False
    last_status = ''
    while not done:
        o = api.query_order(oid)
        if last_status != o['status']:
            last_status = o['status']   
            print('order status: %s' % o['status'])
        if return_on_error and o['status'] == 'Error':
            return
        assert o['status'] != 'Error'
        if o['status'] == 'Filled':
            done = True
        else:
            time.sleep(1)

def _position(api, account):
    pos = api.query_positions()
    assert type(pos) == dict
    assert account in pos.keys()
    if account in pos:
        p=pos[account]
        assert type(p) == dict
    else: 
        p={}
    return p

def _market_order(api, symbol, quantity, return_on_error=False):
    o = api.market_order(symbol, quantity)
    assert o 
    assert 'permid' in o.keys()
    assert 'status' in o.keys()
    oid = o['permid']
    assert type(oid) == str or type(oid) == unicode
    print('market_order(%s,%s) returned oid=%s status=%s' % (symbol, quantity, oid, o['status']))
    _wait_for_fill(api, oid, return_on_error)  
    return oid

def test_trades(api):
    account = api.query_accounts()[0]
    api.set_account(account)

    oid = _market_order(api, 'AAPL',1)

    p = _position(api, account)
    if 'AAPL' in p.keys() and p['AAPL']!=0:
        oid = _market_order(api, 'AAPL', -1 * p['AAPL'])
        ostat = api.query_order(oid)
        assert ostat
        assert type(ostat) == dict
        assert 'permid' in ostat.keys()

    p = _position(api, account)
    assert not 'AAPL' in p.keys()  or p['AAPL']==0

    oid = _market_order(api, 'AAPL', 100)

    p = _position(api, account)
    assert p
    assert type(p) == dict
    assert 'AAPL' in p.keys()
 
    assert p['AAPL'] == 100

    oid = _market_order(api, 'AAPL',-10)

    p = _position(api, account)
    assert 'AAPL' in p.keys()
   
    assert p['AAPL'] == 90

@pytest.mark.staged
def test_staged_trades(api):
    account = api.query_accounts()[0]
    api.set_account(account)

    t = api.stage_market_order('TEST.%s' % str(time.time()), 'GOOG', 10)
    assert t
    assert type(t) == dict
    assert 'permid' in t.keys()
    oid = t['permid']
    print('Created staged order %s, awaiting user execution from RealTick' % oid)
    _wait_for_fill(api, oid)


@pytest.mark.staged
def test_staged_trade_cancel(api):
    account = api.query_accounts()[0]
    api.set_account(account)
    t = api.stage_market_order('TEST.%s' % str(time.time()), 'INTC', 10)
    assert t
    assert type(t) == dict
    assert 'permid' in t.keys()
    oid = t['permid']
    print('Created staged order %s, awaiting user cancellation from RealTick' % oid)
    _wait_for_fill(api, oid, True)
    t = api.query_order(oid)
    assert t
    assert type(t)==dict
    assert 'status' in t.keys()
    assert t['status'] == 'Error'
    assert 'REASON' in t.keys()
    assert t['REASON'].lower().startswith('user cancel')
    print('detected user cancel of %s' % oid)

@pytest.mark.staged
def test_staged_trade_execute(api):
    account = api.query_accounts()[0]
    api.set_account(account)
    trade_symbol = 'AAPL'
    trade_quantity = 10
    t = api.stage_market_order('TEST.%s' % str(time.time()), trade_symbol, trade_quantity)
    assert t
    assert type(t) == dict
    assert 'permid' in t.keys()
    oid = t['permid']
    status = t['status']
    print('Created staged order %s with status %s, waiting 5 seconds, then changing order to auto-execute' % (oid, status))
    time.sleep(5)
    status = api.query_order(oid)['status']
    print('cancelling order %s with status=%s...' % (oid, status))
    r = api.cancel_order(oid)
    print('cancel returned %s' % repr(r))
    assert r
    _wait_for_fill(api, oid, True)
    o = api.query_order(oid)
    print('order: %s' % o)
    print('cancel confirmed oid=%s, status=%s' % (oid, o['status']))
    t = api.market_order(trade_symbol, trade_quantity)
    assert t
    assert type(t)==dict
    new_oid = t['permid']
    assert new_oid != oid
    print('submitted trade as new order %s' % new_oid)
    _wait_for_fill(api, new_oid)
    print('detected execution of %s' % new_oid)
    o = api.query_order(new_oid)
    assert o['status']=='Filled'

def test_query_orders(api):
    orders = api.query_orders()
    assert orders != None
    assert type(orders) == dict

def test_trade_and_query_orders(api):
    oid = _market_order(api, 'AAPL',1)
    orders = api.query_orders()
    assert orders != None
    assert type(orders) == dict
    assert oid in orders.keys()
    assert type(orders[oid]) == dict
    assert orders[oid]['permid'] == oid
    assert 'status' in orders[oid]

def test_query_executions(api):
    execs = api.query_executions()
    assert type(execs) == dict
    assert execs != None

def test_trade_and_query_executions_and_query_order(api):
    oid = _market_order(api, 'AAPL',1)
    oid = str(oid)
    #print('oid: %s' % oid)
    execs = api.query_executions()
    #print('execs: %s' % repr(execs))
    assert type(execs) == dict
    assert execs != None
    found=None
    for k,v in execs.items():
        #print('----------------')
        #print('k=%s' % k)
        #print('v=%s' % repr(v))
        #print('%s %s %s' % (found, v['permid'], oid))
        if str(v['permid']) == oid:
            found = k
            break
    assert found
    assert str(execs[k]['permid']) == oid

    o = api.query_order(oid)
    assert o
    assert oid == o['permid']
    assert 'status' in o
    assert o['status']=='Filled'

"""
    STRAT_PARAMETERS fields per 2017-09-29 email from Raymond Tsui (rtsui@ezsoft.com)

        847=15      (type?)
        9000=15     (version?) 
        9007=1      Volume Min
        9008=2      Volume Max
        9039=0.03   iWouldPrice (>=0)
        9088=1      Execution Style (1=Passive, 2=Neutral, 3=Aggressive, 4=Custom)
        9076=4      MinDarkFill
        9043=0      MOO Allowed (0=unchecked, 1=checked)
        9011=0      MOC Allowed (0=unchedked, 1=checked)
"""
 
@pytest.mark.algo
def test_algo_order(api):
    print()

    account = api.query_accounts()[0]
    api.set_account(account)
    ret = api.get_order_route()
    assert type(ret) == dict
    assert len(ret.keys()) == 1
    oldroute = ret.keys()[0] 
    assert type(oldroute) == str or type(oldroute) == unicode
    assert ret[oldroute] == None
    assert oldroute in ['DEMO', 'DEMOEUR']

    algo_order_parameters = {
        'STRAT_ID': 'ABRAXAS',
        'BOOKING_TYPE': '0',
        'STRAT_PARAMETERS': {
            '847': '15',
            '9000': '15',
            '9007': '1',
            '9008': '2',
            '9039': '0.03',
            '9088': '1',
            '9076': '4',
            '9043': '0',
            '9011': '0',
        },
        'STRAT_TIME_TAGS': '-1:-2',
        'ORDER_FLAGS_3': 0,
        'STRAT_TARGET': 'ATDL',
        'STRATEGY_NAME': 'Abraxas',
        'SETTLE_TYPE_SYNTHETIC': -1,
        'STRAT_TYPE': 'BNYCONVERGEX_BNYAlgos_from_RT_US_timefix',
        'STRAT_STRING_40': 'ABRAXAS',
        'DEST_ROUTE': 'TEST-CVGX-USALGO-ATD'
    }
    route = 'TEST-CVGX-USALGO-ATD'
    p = {route: algo_order_parameters}

    ret = api.set_order_route(p)
    assert ret

    assert api.get_order_route() == p

    oid = _market_order(api, 'INTC', 100)

    assert api.query_order('oid')['status'] == 'Filled'

    assert api.set_order_route(oldroute)

def test_trade_submission_error_bad_symbol(api):
    o = api.market_order('BADSYMBOL', 100)
    assert o
    assert o['status'] == 'Error'
    #print('order: %s' % repr(o))

def test_trade_submission_error_bad_quantity(api):
    o = api.market_order('AAPL', 0)
    assert o
    if o['status'] != 'Error':
        oid = o['permid']
        _wait_for_fill(api, oid, True)
        o = api.query_order(oid)
    assert o['status'] == 'Error'
    #print('order: %s' % repr(o))

#TODO: test other order types

#    def json_limit_order(self, args, d):
#        """limit_order('symbol', price, quantity) => {'field':, data, ...} 
#    def json_stop_order(self, args, d): 
#        """stop_order('symbol', price, quantity) => {'field':, data, ...} 
#    def json_stoplimit_order(self, args, d): 
#        """stoplimit_order('symbol', stop_price, limit_price, quantity) => {'field':, data, ...} 

@pytest.mark.bars
def dont_test_bars(api): 
    sbar = '2017-07-06 09:30:00' 
    ebar = '2017-07-06 09:40:00' 
    ret = api.query_bars('SPY', 1, sbar, ebar) 
    assert ret 
    assert type(ret) == list 
    assert ret[0]=='OK' 
    bars = ret[1] 
    assert bars 
    assert type(bars) == list 
    for bar in bars:
        assert type(bar) == dict
        assert 'date' in bar
        assert 'open' in bar
        assert 'high' in bar
        assert 'low' in bar
        assert 'close' in bar
        assert 'volume' in bar
        #print('%s %s %s %s %s %s' % (bar['date'], bar['open'], bar['high'], bar['low'], bar['close'], bar['volume']))

def test_cancel_order(api):
    ret = api.cancel_order('000')
    assert ret

def test_global_cancel(api):
    ret = api.global_cancel()
    assert ret

def json_gateway_logon(api):
    ret = api.gateway_logon('user', 'passwd')
    assert ret

def test_gateway_logoff(api):
    ret = api.gateway_logoff()
    assert ret

def test_set_primary_exchange(api):
    if testmode == 'RTX':
        exchange = 'NAS'
    elif testmode == 'TWS':
        exchange = 'NASDAQ'
    assert api.set_primary_exchange('MSFT', exchange)
    assert api.add_symbol('MSFT')
    assert api.query_symbol('MSFT')

def test_help(api):
    help = api.help()
    assert type(help) == dict
