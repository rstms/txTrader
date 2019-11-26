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
from pprint import pprint
import pytest
import re
import datetime

FILL_TIMEOUT = 30


TEST_ALGO_ROUTE='{"TEST-ATM-ALGO":{"STRAT_ID":"BEST","BOOKING_TYPE":"3","STRAT_TIME_TAGS":"168;126","STRAT_PARAMETERS":{"99970":"2","99867":"N","847":"BEST","90057":"BEST","91000":"4.1.95"},"ORDER_FLAGS_3":"0","ORDER_CLONE_FLAG":"1","STRAT_TARGET":"ATDL","STRATEGY_NAME":"BEST","STRAT_REDUNDANT_DATA":{"UseStartTime":"false","UseEndTime":"false","cConditionalType":"{NULL}"},"STRAT_TIME_ZONE":"America/New_York","STRAT_TYPE":"COWEN_ATM_US_EQT","STRAT_STRING_40":"BEST","UTC_OFFSET":"-240"}}'

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
    print('test_init checking api')
    assert api 
    print('waiting 1 second...')
    time.sleep(1)
    print('done')

def test_stock_prices(api):

    s = api.add_symbol('IBM')
    assert s

    p = api.query_symbol('IBM')
    assert p

    assert type(p) == dict
    print(repr(p))

    tdata = [
        ('symbol', unicode, True),
        ('fullname', unicode, True),
        ('last', float, True),
        ('size', int, True),
        ('volume', int, True),
        ('open', float, True),
        ('high', float, True),
        ('low', float, True),
        ('close', float, True),
        ('vwap', float, True),
        ('tradetime', unicode, True),
    ]
    #('bars', list, True),

    for key, _type, required in tdata:
      assert key in p.keys()
      assert type(p[key]) == _type
      if required:
        assert not p[key] == None

    r = api.query_symbol_data('IBM')
    assert r
    dump('raw data for IBM', r)

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
    #account = api.account
    #print('account=%s' % account)
    #api.set_account(account)
    print('buying IBM')
    oid = _market_order(api, 'IBM', 100)
    o = api.query_order(oid)
    assert o
    assert type(o) == dict
    assert 'permid' in o.keys()
    oid = o['permid']
    assert 'status' in o.keys()
    dump('market_order(IBM,100)', o)

    print('selling IBM')
    oid = _market_order(api, 'IBM', -100)
    o = api.query_order(oid)
    assert o
    assert type(o) == dict
    assert 'permid' in o.keys()
    assert 'status' in o.keys()
    dump('market_order(IBM,-100)', o)

def test_set_order_route(api):
    print()
    oldroute = api.get_order_route()
    assert type(oldroute) == dict
    assert oldroute.keys() == ['DEMOEUR']
    r0 = 'DEMO'
    r1 = {'DEMO':None} 
    r2 = {'DEMO': {'key1':'value1', 'key2':'value2'}}
    r3 = TEST_ALGO_ROUTE
    for rin, rout in [ (r0, r1), (r1, r1), (r2, r2), (json.dumps(r0), r1), (json.dumps(r1), r1), (json.dumps(r2), r2), (r3, json.loads(r3))]: 
        print('set_order_route(%s)' % repr(rin))
        assert api.set_order_route(rin) == rout
        assert api.get_order_route() == rout
    assert api.set_order_route(oldroute) == oldroute

def test_partial_fill(api):
    print()
    oldroute = api.get_order_route()
    assert api.set_order_route('DEMO')
    assert api.get_order_route() == {'DEMO': None}
    quantity = 1000
    symbol = 'COWN'
    print('buying %d %s' % (quantity, symbol))
    p = api.add_symbol(symbol)
    assert p
    d = api.query_symbol_data(symbol)
    #pprint(d)
    now =datetime.datetime.now().strftime('%H:%M:%S')
    during_trading_hours = bool(d['STARTTIME'] <= now <= d['STOPTIME'])
    o = api.market_order(symbol, quantity)
    assert o
    assert 'permid' in o.keys()
    assert 'status' in o.keys()
    assert not o['status'] == 'Filled'
    oid = o['permid']
    print('oid=%s' % oid)
    partial_fills = 0
    while o['status'] != 'Filled':
        o = api.query_order(oid)
        #o={'status':'spoofed','TYPE':'spoofed'}
        #pprint(o)
        status = o['status']
        filled = o['filled'] if 'filled' in o.keys() else 0
        remaining = o['remaining'] if 'remaining' in o.keys() else 0
        if (int(filled) > 0) and (int(remaining) > 0) and (int(filled) < quantity):
            partial_fills += 1    
        average_price = o['avgfillprice'] if 'avgfillprice' in o.keys() else None
        print('status=%s filled=%s remaining=%s average_price=%s type=%s' % (status, filled, remaining, average_price, o['type']))
        assert not (status=='Filled' and filled < quantity)
        if not during_trading_hours and status == 'Error':
            print('test verification disabled - simulated market is closed')
            partial_fills = -1
            break
        assert status in ['Submitted', 'Pending', 'Filled']
        time.sleep(1)
    assert partial_fills
    o = api.market_order(symbol, quantity*-1)
    assert api.set_order_route(oldroute)

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

def _verify_barchart_enabled(api):
    v = api.version()
    assert v
    assert type(v)==dict
    assert type(v['flags'])==dict
    assert 'BARCHART' in v['flags']
    return v['flags']['BARCHART']==True

def test_symbol_bars(api):
    if 'TSLA' in api.query_symbols():
        assert api.del_symbol('TSLA')
    assert api.add_symbol('TSLA')
    assert 'TSLA' in api.query_symbols()
    bars = api.query_symbol_bars('TSLA')
    assert type(bars) == list
    print(repr(bars))
    if _verify_barchart_enabled(api):
        assert type(bars[0]) == list
        for bar in bars:
           print('%s' % repr(bar))
           for i in range(len(bar)):
               assert type(bar[i]) in [[str, unicode], [str,unicode], [float], [float], [float], [float], [int]][i]
               assert re.match('^\d\d\d\d-\d\d-\d\d$', bar[0]) 
               assert re.match('^\d\d:\d\d:\d\d$', bar[1]) 
    else:
        print('barchart disabled')
        assert bars == []

def test_query_accounts(api):
    test_account = api.account

    accounts = api.query_accounts()

    assert type(accounts) == list
    assert accounts

    for a in accounts:
        assert type(a) == str or type(a) == unicode 

    assert test_account in accounts
    ret = api.set_account(test_account)
    assert ret

    ret =  api.query_account('b.b.b.INVALID_ACCOUNT')
    assert ret == None

    ret = api.query_account(test_account, 'INVALID_FIELD')
    assert ret == None

    ret = api.query_account(test_account, 'INVALID_FIELD_1,INVALID_FIELD_2')
    assert ret == None

    #print('query_account(%s)...' % a)
    data = api.query_account(test_account)
  #print('account[%s]: %s' % (a, repr(data)))
    assert data
    assert type(data)==dict

    fields = [k for k in data.keys() if not k.startswith('_')]

    if testmode == 'RTX':
        field = 'EXCESS_EQ'
    elif testmode == 'TWS':
        field = 'LiquidationValue'

    # txtrader is expected to set the value _cash to the correct field 
    assert '_cash' in data.keys()
    assert float(data['_cash']) == round(float(data[field]),2)
    
    sdata = api.query_account(test_account, field) 
    assert sdata
    assert type(sdata)==dict
    assert field in sdata.keys()

    rfields = ','.join(fields[:3])
    print('requesting fields: %s' % rfields)
    sdata = api.query_account(test_account, rfields)
    print('got %s' % repr(sdata))
    assert sdata
    assert type(sdata)==dict
    for field in rfields.split(','):
      assert field in sdata.keys()
    assert set(rfields.split(',')) == set(sdata.keys())
    

  #print('account[%s]: %s' % (a, repr(sdata)))

def _wait_for_fill(api, oid, return_on_error=False):
    print('Waiting for order %s to fill...' % oid)
    done = False
    last_status = ''
    count = 0
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
            count += 1
            assert count < FILL_TIMEOUT
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
    print('Sending market_order(%s, %d)...' % (symbol, quantity))
    o = api.market_order(symbol, quantity)
    print('market_order returned %s' % repr(o))
    assert o 
    assert 'permid' in o.keys()
    assert 'status' in o.keys()
    oid = o['permid']
    assert type(oid) == str or type(oid) == unicode
    print('market_order(%s,%s) returned oid=%s status=%s' % (symbol, quantity, oid, o['status']))
    _wait_for_fill(api, oid, return_on_error)  
    return oid

def test_trades(api):

    account = api.account

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

    t = api.stage_market_order('TEST.%s' % str(time.time()), 'GOOG', 10)
    assert t
    assert type(t) == dict
    assert 'permid' in t.keys()
    oid = t['permid']
    print('Created staged order %s, awaiting user execution from RealTick' % oid)
    _wait_for_fill(api, oid)


@pytest.mark.staged
def test_staged_trade_cancel(api):
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
    assert 'REASON' in t['raw']
    assert t['raw']['REASON'].lower().startswith('user cancel')
    print('detected user cancel of %s' % oid)

#@pytest.mark.staged
def test_staged_trade_execute(api):
    trade_symbol = 'AAPL'
    trade_quantity = 10
    t = api.stage_market_order('TEST.%s' % str(time.time()), trade_symbol, trade_quantity)
    assert t
    assert type(t) == dict
    assert 'permid' in t.keys()
    oid = t['permid']
    status = t['status']
    print('Created staged order %s with status %s, waiting 5 seconds, then changing order to auto-execute' % (oid, status))

    tickets = api.query_tickets()
    assert oid in tickets.keys()
    orders = api.query_orders()
    assert not oid in orders.keys()

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
    tickets = api.query_tickets()
    assert tickets != None
    assert not oid in tickets.keys()

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
    ALGO ORDER fields per 2018-07-24 email from Raymond Tsui (rtsui@ezsoft.com)

"""
@pytest.mark.algo
def test_algo_order(api):
    print()

    ret = api.get_order_route()
    assert type(ret) == dict
    assert len(ret.keys()) == 1
    oldroute = ret.keys()[0] 
    assert type(oldroute) == str or type(oldroute) == unicode
    assert ret[oldroute] == None
    assert oldroute in ['DEMO', 'DEMOEUR']

    algo_order_parameters = {
      "STRAT_ID": "BEST",
      "BOOKING_TYPE": 3,
      "STRAT_TIME_TAGS": "168;126",
      "STRAT_PARAMETERS": {
        "99970": "2",
        "99867": "N",
        "847": "BEST",
        "90057": "BEST",
        "91000": "4.1.95"
      },
      "ORDER_FLAGS_3": 0,
      "ORDER_CLONE_FLAG": 1,
      "STRAT_TARGET": "ATDL",
      "STRATEGY_NAME": "BEST",
      "STRAT_REDUNDANT_DATA": {
        "UseStartTime": "false",
        "UseEndTime": "false",
        "cConditionalType": "{NULL}"
      },
      "STRAT_TIME_ZONE": "America/New_York",
      "STRAT_TYPE": "COWEN_ATM_US_EQT",
      "STRAT_STRING_40": "BEST",
      "UTC_OFFSET": "-240"
    }
    route = 'TEST-ATM-ALGO'
    p = {route: algo_order_parameters}

    ret = api.set_order_route(p)
    assert ret

    assert api.get_order_route() == p

    oid = _market_order(api, 'INTC', 100)

    assert api.query_order(oid)['status'] == 'Filled'

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
def test_bars(api): 
    assert api.add_symbol('SPY')
    sbar = '2017-08-29 09:30:00' 
    ebar = '2017-08-29 09:40:00' 
    bars = api.query_bars('SPY', 1, sbar, ebar) 
    if _verify_barchart_enabled(api):
        assert bars 
        assert type(bars) == list 
        for bar in bars:
            assert type(bar) == list  
            b_date, b_time, b_open, b_high, b_low, b_close, b_volume = bar
            assert type(b_date) in (str, unicode) 
            assert re.match('^\d\d\d\d-\d\d-\d\d$', b_date) 
            assert type(b_time) in (str, unicode)
            assert re.match('^\d\d:\d\d:\d\d$', b_time) 
            assert type(b_open) == float
            assert type(b_high) == float
            assert type(b_low) == float
            assert type(b_close) == float
            assert type(b_volume) == int 
            print('%s %s %.2f %.2f %.2f %.2f %d' % (b_date, b_time, b_open, b_high, b_low, b_close, b_volume))
    else:
        assert not bars 
        print('bars=%s' % repr(ret))

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
    assert help == None
