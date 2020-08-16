# -*- coding: utf-8 -*-
"""
  test-txtrader.py
  --------------

  TxTrader unit/regression test script

  Copyright (c) 2016 Reliance Systems Inc. <mkrueger@rstms.net>
  Licensed under the MIT license.  See LICENSE for details.

"""
from txtrader_client import API
import subprocess
import os
import signal
import time

import ujson as json
from pprint import pprint, pformat
import pytest
import re
import datetime

WAIT_FOR_FILL = False
FILL_TIMEOUT = 30

TEST_ALGO_ROUTE = '{"TEST-ATM-ALGO":{"STRAT_ID":"BEST","BOOKING_TYPE":"3","STRAT_TIME_TAGS":"168;126","STRAT_PARAMETERS":{"99970":"2","99867":"N","847":"BEST","90057":"BEST","91000":"4.1.95"},"ORDER_FLAGS_3":"0","ORDER_CLONE_FLAG":"1","STRAT_TARGET":"ATDL","STRATEGY_NAME":"BEST","STRAT_REDUNDANT_DATA":{"UseStartTime":"false","UseEndTime":"false","cConditionalType":"{NULL}"},"STRAT_TIME_ZONE":"America/New_York","STRAT_TYPE":"COWEN_ATM_US_EQT","STRAT_STRING_40":"BEST","UTC_OFFSET":"-240"}}'

TEST_MODE = 'RTX'
TEST_HOST = os.environ['TXTRADER_HOST']
TEST_PORT = int(os.environ['TXTRADER_HTTP_PORT'])


def _listening(host, port, timeout=15):
    return not bool(os.system(f'wait-for-it -s {host}:{port} -t {timeout}'))


def _wait_api_status(TEST_MODE, timeout=15):
    start = time.time()
    status = None
    last_status = None
    api = None
    while status != 'Up':
        try:
            if not api:
                api = API(TEST_MODE)
                print(f'new api connection: {api}')
        except Exception as ex:
            print(f'Connection raised {ex}, retrying...')
            api = None
            time.sleep(1)
        else:
            assert api
            try:
                status = api.status()
            except Exception as ex:
                print(f'status query on {api} raised {ex}, retrying...')
                api = None
                time.sleep(1)
            else:
                if last_status != status:
                    print(f"status={status}")
                    last_status = status
        assert (time.time() - start) < timeout, 'timeout waiting for initialization'
        time.sleep(1)
    return api


@pytest.fixture(scope='module')
def api():
    print('fixture: creating api connection')
    assert _listening(TEST_HOST, TEST_PORT)
    api = _wait_api_status(TEST_MODE)
    return api


def dump(label, o):
    print('%s:\n%s' % (label, pformat(json.dumps(o))))


def test_init(api):
    print()
    print('test_init checking api')
    assert api
    assert api.status() == 'Up'
    print('waiting 1 second...')
    time.sleep(1)
    print('done')


def test_shutdown_and_reconnect():
    print('\nconnecting...')
    api = _wait_api_status(TEST_MODE)
    assert api
    assert api.status() == 'Up'
    shutdown_time = time.time()
    shutdown = time.time()
    print('shutting down api')
    try:
        api.shutdown('testing shutdown request')
        print('waiting for shutdown...')
        time.sleep(5)
        print('waiting for restart...')
    except Exception as ex:
        print(f'shutdown raised {ex}')
        assert False
    assert _listening(TEST_HOST, TEST_PORT, 60), 'timeout waiting for restart'
    try:
        api = _wait_api_status(TEST_MODE, 90)
    except Exception as ex:
        print(f'restart raised {ex}')
        assert False
    assert api
    assert api.status() == 'Up'


def test_stock_prices(api):

    slist = set(api.query_symbols())

    s = api.add_symbol('IBM')
    assert s

    p = api.query_symbol('IBM')
    assert p

    assert type(p) == dict
    print(repr(p))

    tdata = [
        ('symbol', str, True),
        ('fullname', str, True),
        ('last', float, True),
        ('size', int, True),
        ('volume', int, True),
        ('open', float, True),
        ('high', float, True),
        ('low', float, True),
        ('close', float, True),
        ('vwap', float, True),
        ('tradetime', str, True),
        ('cusip', str, True),
    ]
    #('bars', list, True),

    for key, _type, required in tdata:
        assert key in p
        assert type(p[key]) == _type
        if required:
            assert not p[key] == None

    r = api.query_symbol_data('IBM')
    assert r
    dump('raw data for IBM', r)

    l = api.query_symbols()
    assert l
    dump('symbol list', l)
    assert 'IBM' in l

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
    assert set(['IBM', 'TSLA', 'GOOG', 'AAPL']).issubset(set(l))
    dump('symbol list', l)

    s = api.del_symbol('TSLA')
    assert s
    dump('del TSLA', s)

    l = api.query_symbols()
    if not 'TSLA' in slist:
        assert not 'TSLA' in l
    assert set(['IBM', 'GOOG', 'AAPL']).issubset(set(l))
    dump('symbol list', l)

    print(repr(l))


def test_buy_sell(api):
    print()
    account = api.account
    print('account=%s' % account)
    api.set_account(account)
    print('buying IBM')
    oid = _market_order(api, 'IBM', 100)
    o = api.query_order(oid)
    assert o
    assert type(o) == dict
    assert 'permid' in o
    oid = o['permid']
    assert 'status' in o
    dump('market_order(IBM,100)', o)

    print('selling IBM')
    oid = _market_order(api, 'IBM', -100)
    o = api.query_order(oid)
    assert o
    assert type(o) == dict
    assert 'permid' in o
    assert 'status' in o
    dump('market_order(IBM,-100)', o)


def test_set_order_route(api):
    print()
    oldroute = api.get_order_route()
    assert type(oldroute) == dict
    assert list(oldroute.keys()) == ['DEMOEUR']
    r0 = 'DEMO'
    r1 = {'DEMO': None}
    r2 = {'DEMO': {'key1': 'value1', 'key2': 'value2'}}
    r3 = TEST_ALGO_ROUTE
    for rin, rout in [(r0, r1), (r1, r1), (r2, r2), (json.dumps(r0), r1), (json.dumps(r1), r1), (json.dumps(r2), r2),
                      (r3, json.loads(r3))]:
        print('set_order_route(%s)' % repr(rin))
        assert api.set_order_route(rin) == rout
        assert api.get_order_route() == rout
    assert api.set_order_route(oldroute) == oldroute


def test_partial_fill(api):
    print()
    account = api.account
    route = 'DEMO'
    oldroute = api.get_order_route()
    assert api.set_order_route(route)
    assert api.get_order_route() == {route: None}
    quantity = 1000
    symbol = 'COWN'
    print('buying %d %s' % (quantity, symbol))
    p = api.add_symbol(symbol)
    assert p
    d = api.query_symbol_data(symbol)
    #pprint(d)
    now = datetime.datetime.now().strftime('%H:%M:%S')
    during_trading_hours = bool(d['STARTTIME'] <= now <= d['STOPTIME'])
    o = api.market_order(account, route, symbol, quantity)
    assert o
    assert 'permid' in o
    assert 'status' in o
    assert not o['status'] == 'Filled'
    oid = o['permid']
    print('oid=%s' % oid)
    partial_fills = 0
    while o['status'] != 'Filled':
        o = api.query_order(oid)
        #o={'status':'spoofed','TYPE':'spoofed'}
        #pprint(o)
        status = o['status']
        filled = o['filled'] if 'filled' in o else 0
        remaining = o['remaining'] if 'remaining' in o else 0
        if (int(filled) > 0) and (int(remaining) > 0) and (int(filled) < quantity):
            partial_fills += 1
        average_price = o['avgfillprice'] if 'avgfillprice' in o else None
        print(
            'status=%s filled=%s remaining=%s average_price=%s type=%s' % (status, filled, remaining, average_price, o['type'])
        )
        assert not (status == 'Filled' and filled < quantity)
        if not during_trading_hours and status == 'Error':
            print('test verification disabled - simulated market is closed')
            partial_fills = -1
            break
        assert status in ['Submitted', 'Pending', 'Filled']
        time.sleep(1)
    assert partial_fills
    o = api.market_order(account, route, symbol, quantity * -1)
    assert api.set_order_route(oldroute)


def test_status(api):
    assert api.status() == 'Up'


def test_uptime(api):
    uptime = api.uptime()
    assert uptime
    print('uptime: %s' % repr(uptime))
    assert type(uptime) == str


def test_version(api):
    assert api.version()


def test_symbol_price(api):
    orig_symbols = api.query_symbols()

    assert type(orig_symbols) == list
    if 'AAPL' in orig_symbols:
        ret = api.del_symbol('AAPL')
        assert ret
    symbols = api.query_symbols()
    assert type(symbols) == list
    if not 'AAPL' in orig_symbols:
        assert not 'AAPL' in symbols
    price = api.query_symbol('AAPL')
    #assert not price
    assert price

    ret = api.add_symbol('AAPL')
    assert ret

    p = api.query_symbol('AAPL')
    assert p
    assert type(p) == dict
    assert p['symbol'] == 'AAPL'


def _verify_barchart_enabled(api, option):
    v = api.version()
    assert option in ['SYMBOL_BARCHART', 'BARCHART']
    assert v
    assert type(v) == dict
    assert type(v['flags']) == dict
    assert option in v['flags']
    return v['flags'][option] == True


def test_symbol_bars(api):
    if 'TSLA' in api.query_symbols():
        assert api.del_symbol('TSLA')
    assert api.add_symbol('TSLA')
    assert 'TSLA' in api.query_symbols()
    bars = api.query_symbol_bars('TSLA')
    assert type(bars) == list
    print(repr(bars))
    if _verify_barchart_enabled(api, 'SYMBOL_BARCHART'):
        assert type(bars[0]) == list
        for bar in bars:
            print('%s' % repr(bar))
            for i in range(len(bar)):
                assert type(bar[i]) in [[str], [str], [float], [float], [float], [float], [int]][i]
                assert re.match('^\\d\\d\\d\\d-\\d\\d-\\d\\d$', bar[0])
                assert re.match('^\\d\\d:\\d\\d:\\d\\d$', bar[1])
    else:
        print('barchart disabled')
        assert bars == []


def test_query_accounts(api):
    test_account = api.account

    accounts = api.query_accounts()

    assert type(accounts) == list
    assert accounts

    for a in accounts:
        assert type(a) == str or type(a) == str

    assert test_account in accounts
    ret = api.set_account(test_account)
    assert ret

    ret = api.query_account('b.b.b.INVALID_ACCOUNT')
    assert ret == None

    ret = api.query_account(test_account, 'INVALID_FIELD')
    assert ret == None

    ret = api.query_account(test_account, 'INVALID_FIELD_1,INVALID_FIELD_2')
    assert ret == None

    #print('query_account(%s)...' % a)
    data = api.query_account(test_account)
    #print('account[%s]: %s' % (a, repr(data)))
    assert data
    assert type(data) == dict

    fields = [k for k in data if not k.startswith('_')]

    if TEST_MODE == 'RTX':
        field = 'EXCESS_EQ'
    elif TEST_MODE == 'TWS':
        field = 'LiquidationValue'

    # txtrader is expected to set the value _cash to the correct field
    assert '_cash' in data
    assert float(data['_cash']) == round(float(data[field]), 2)

    sdata = api.query_account(test_account, field)
    assert sdata
    assert type(sdata) == dict
    assert field in sdata

    rfields = ','.join(fields[:3])
    print('requesting fields: %s' % rfields)
    sdata = api.query_account(test_account, rfields)
    print('got %s' % repr(sdata))
    assert sdata
    assert type(sdata) == dict
    for field in rfields.split(','):
        assert field in sdata
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
            if WAIT_FOR_FILL:
                assert count < FILL_TIMEOUT
                time.sleep(1)
            else:
                if o['status'] == 'Pending':
                    print("fill wait disabled, returning")
                    done = True


def _position(api, account):
    pos = api.query_positions()
    assert type(pos) == dict
    assert account in pos
    if account in pos:
        p = pos[account]
        assert type(p) == dict
    else:
        p = {}
    return p


def _market_order(api, symbol, quantity, return_on_error=False):
    print('Sending market_order(%s, %d)...' % (symbol, quantity))
    account = api.account
    route = 'DEMOEUR'
    o = api.market_order(account, route, symbol, quantity)
    print('market_order returned %s' % repr(o))
    assert o
    assert 'permid' in o
    assert 'status' in o
    oid = o['permid']
    assert type(oid) == str
    print('market_order(%s,%s) returned oid=%s status=%s' % (symbol, quantity, oid, o['status']))
    _wait_for_fill(api, oid, return_on_error)
    return oid


def test_trades(api):

    account = api.account
    route = 'DEMOEUR'

    oid = _market_order(api, 'AAPL', 1)

    p = _position(api, account)
    if 'AAPL' in p and p['AAPL'] != 0:
        oid = _market_order(api, 'AAPL', -1 * p['AAPL'])
        ostat = api.query_order(oid)
        assert ostat
        assert type(ostat) == dict
        assert 'permid' in ostat

    p = _position(api, account)
    if WAIT_FOR_FILL:
        assert not 'AAPL' in p or p['AAPL'] == 0
    else:
        print('not testing order results')

    oid = _market_order(api, 'AAPL', 100)

    p = _position(api, account)
    assert p
    assert type(p) == dict
    assert 'AAPL' in p

    if WAIT_FOR_FILL:
        assert p['AAPL'] == 100
    else:
        print('not testing order results')

    oid = _market_order(api, 'AAPL', -10)

    p = _position(api, account)
    assert 'AAPL' in p

    if WAIT_FOR_FILL:
        assert p['AAPL'] == 90
    else:
        print('not testing order results')


@pytest.mark.staged
def test_staged_trades(api):

    account = api.account
    route = 'DEMOEUR'
    t = api.stage_market_order('TEST.%s' % str(time.time()), account, route, 'GOOG', 10)
    assert t
    assert type(t) == dict
    assert 'permid' in t
    oid = t['permid']
    print('Created staged order %s, awaiting user execution from RealTick' % oid)
    _wait_for_fill(api, oid)


@pytest.mark.staged
def test_staged_trade_cancel(api):
    account = api.account
    route = 'DEMOEUR'
    t = api.stage_market_order('TEST.%s' % str(time.time()), account, route, 'INTC', 10)
    assert t
    assert type(t) == dict
    assert 'permid' in t
    oid = t['permid']
    print('Created staged order %s, awaiting user cancellation from RealTick' % oid)
    _wait_for_fill(api, oid, True)
    t = api.query_order(oid)
    assert t
    assert type(t) == dict
    assert 'status' in t
    assert t['status'] == 'Error'
    assert 'REASON' in t['raw']
    assert t['raw']['REASON'].lower().startswith('user cancel')
    print('detected user cancel of %s' % oid)


#@pytest.mark.staged
def test_staged_trade_execute(api):
    account = api.account
    route = 'DEMOEUR'
    trade_symbol = 'AAPL'
    trade_quantity = 10
    t = api.stage_market_order('TEST.%s' % str(time.time()), account, route, trade_symbol, trade_quantity)
    assert t
    assert type(t) == dict
    assert 'permid' in t
    oid = t['permid']
    status = t['status']
    print('Created staged order %s with status %s, waiting 5 seconds, then changing order to auto-execute' % (oid, status))

    tickets = api.query_tickets()
    assert oid in tickets
    orders = api.query_orders()
    assert not oid in orders

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
    t = api.market_order(account, route, trade_symbol, trade_quantity)
    assert t
    assert type(t) == dict
    new_oid = t['permid']
    assert new_oid != oid
    print('submitted trade as new order %s' % new_oid)
    _wait_for_fill(api, new_oid)
    print('detected execution of %s' % new_oid)
    o = api.query_order(new_oid)
    if WAIT_FOR_FILL:
        assert o['status'] == 'Filled'
    else:
        print('not testing order results')


def test_query_orders(api):
    orders = api.query_orders()
    assert orders != None
    assert type(orders) == dict


def test_trade_and_query_orders(api):
    oid = _market_order(api, 'AAPL', 1)
    orders = api.query_orders()
    assert orders != None
    assert type(orders) == dict
    assert oid in orders
    assert type(orders[oid]) == dict
    assert orders[oid]['permid'] == oid
    assert 'status' in orders[oid]
    tickets = api.query_tickets()
    assert tickets != None
    assert not oid in tickets


def test_query_executions(api):
    execs = api.query_executions()
    assert type(execs) == dict
    assert execs != None


def test_trade_and_query_executions_and_query_order(api):
    oid = _market_order(api, 'AAPL', 10)
    oid = str(oid)
    print('oid: %s' % oid)
    execs = api.query_executions()
    print('execs: %s' % repr(execs.keys()))
    assert type(execs) == dict
    assert execs != None
    xid = None
    start_time = time.time()
    while not xid:
        execs = api.query_executions()
        for k, v in execs.items():
            # NOTE: new execution format includes ORIGINAL_ORDER_ID which matches the permid of the associated order
            if str(v['ORIGINAL_ORDER_ID']) == oid:
                xid = k
            print('----------------')
            print('k=%s' % k)
            print('v=%s' % repr(v))
            print('%s %s %s' % (xid, v['ORIGINAL_ORDER_ID'], oid))
        assert (time.time() - start_time) < 10, "timeout waiting for execution results"

    assert xid
    assert str(execs[xid]['ORIGINAL_ORDER_ID']) == oid

    o = api.query_order(oid)
    assert o
    assert oid == o['permid']
    assert 'status' in o
    if WAIT_FOR_FILL:
        assert o['status'] == 'Filled'


"""
    ALGO ORDER fields per 2018-07-24 email from Raymond Tsui (rtsui@ezsoft.com)

"""


@pytest.mark.algo
def test_algo_order(api):
    print()

    ret = api.get_order_route()
    assert type(ret) == dict
    assert len(ret.keys()) == 1
    oldroute = list(ret.keys())[0]
    assert type(oldroute) == str
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
    account = api.account
    route = 'DEMOEUR'
    o = api.market_order(account, route, 'BADSYMBOL', 100)
    assert o
    assert o['status'] == 'Error'
    #print('order: %s' % repr(o))


def test_trade_submission_error_bad_quantity(api):
    account = api.account
    route = 'DEMOEUR'
    o = api.market_order(account, route, 'AAPL', 0)
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
    if _verify_barchart_enabled(api, 'BARCHART'):
        assert bars
        assert type(bars) == list
        for bar in bars:
            assert type(bar) == list
            b_date, b_time, b_open, b_high, b_low, b_close, b_volume = bar
            assert type(b_date) == str
            assert re.match('^\\d\\d\\d\\d-\\d\\d-\\d\\d$', b_date)
            assert type(b_time) == str
            assert re.match('^\\d\\d:\\d\\d:\\d\\d$', b_time)
            assert type(b_open) == float
            assert type(b_high) == float
            assert type(b_low) == float
            assert type(b_close) == float
            assert type(b_volume) == int
            print('%s %s %.2f %.2f %.2f %.2f %d' % (b_date, b_time, b_open, b_high, b_low, b_close, b_volume))
    else:
        assert not bars
        print('bars=%s' % repr(bars))


def test_cancel_order(api):
    ret = api.cancel_order('000')
    assert ret


def test_global_cancel(api):
    ret = api.global_cancel()
    assert ret


@pytest.mark.skip
def json_gateway_logon(api):
    ret = api.gateway_logon('user', 'passwd')
    assert ret


@pytest.mark.skip
def test_gateway_logoff(api):
    ret = api.gateway_logoff()
    assert ret


@pytest.mark.skip
def test_set_primary_exchange(api):
    if TEST_MODE == 'RTX':
        exchange = 'NAS'
    elif TEST_MODE == 'TWS':
        exchange = 'NASDAQ'
    assert api.set_primary_exchange('MSFT', exchange)
    assert api.add_symbol('MSFT')
    assert api.query_symbol('MSFT')


def test_help(api):
    help = api.help()
    assert help
