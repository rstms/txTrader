#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
  webserver.py
  ------------

  TxTrader JSON over HTTP server module - Implement user interface functions.

  Copyright (c) 2017 Reliance Systems Inc. <mkrueger@rstms.net>
  Licensed under the MIT license.  See LICENSE for details.

"""

from twisted.web import http
from twisted.web.server import Site, NOT_DONE_YET
from twisted.web.resource import Resource
from twisted.internet import reactor, endpoints, defer


from pprint import pprint
import sys
import datetime
import json
from txtrader.version import VERSION

class webserver(object):
    def __init__(self, api):
        self.started = datetime.datetime.now()
        self.api = api
        self.output = api.output
        self.root = Resource()
        self.commands = [name[5:]
                         for name in dir(self) if name.startswith('json_')]
        for route in self.commands:
            self.root.putChild(route, Leaf(
                self, getattr(self, 'json_%s' % route)))

    def json_shutdown(self, args, d):
        """shutdown() 

        Request server shutdown
        """
        # self.output('shutdown()')
        reactor.callLater(1, reactor.stop)
        d.callback('shutdown requested')

    def json_status(self, args, d):
        """status() => 'status string'

        return string describing current API connection status
        """
        d.callback(self.api.query_connection_status())

    def json_uptime(self, args, d):
        """uptime() => 'uptime string'

        Return string showing start time and elapsed time for current server instance
        """
        uptime = datetime.datetime.now() - self.started
        d.callback('started %s (elapsed %s)' % (self.started.strftime(
            '%Y-%m-%d %H:%M:%S'), uptime.strftime('%H:%M:%S')))

    def json_version(self, args, d):
        """version() => 'version string'

        Return string containing release version of current server instance
        """
        ret = {}
        ret['txtrader'] = VERSON
        ret['python'] = sys.version
        #ret['pip'] = check_output('pip list', shell=True)
        d.callback(ret)

    def json_add_symbol(self, args, d):
        """add_symbol('symbol')

        Request subscription to a symbol for price updates and order entry
        """
        symbol = str(args['symbol']).upper()
        self.api.symbol_enable(symbol, self, d)

    def json_del_symbol(self, args, d):
        """del_symbol('symbol')

        Delete subscription to a symbol for price updates and order entry
        """
        symbol = str(args['symbol']).upper()
        d.callback(self.api.symbol_disable(symbol, self))

    def json_query_symbols(self, args, d):
        """query_symbols() => ['symbol', ...]

        Return the list of active symbols
        """
        d.callback(self.api.symbols.keys())

    def json_query_symbol(self, args, d):
        """query_symbol('symbol') => {'fieldname': data, ...}

        Return dict containing current data for given symbol
        """
        symbol = str(args['symbol']).upper()
        ret = None
        if symbol in self.api.symbols.keys():
            ret = self.api.symbols[symbol].export()
        d.callback(ret)

    def json_query_accounts(self, args, d):
        """query_accounts() => ['account_name', ...]

        Return array of account names
        """
        self.api.request_accounts(d)

    def json_set_account(self, args, d):
        """set_account('account')

        Select current active trading account.
        """
        account = str(args['account']).upper()
        self.api.set_account(account, d)

    def json_query_account(self, args, d):
        """query_account(account, fields) => {'key': (value, currency), ...}

        Query account data for account. fields is list of fields to select; None=all fields
        """
        account = str(args['account']).upper()
        if 'fields' in args:
            fields = [str(f) for f in args['fields']]
        else:
            fields = None
        self.api.request_account_data(account, fields, d)

    def json_query_positions(self, args, d):
        """query_positions() => {'account': {'fieldname': data, ...}, ...}

        Return dict keyed by account containing dicts of position data fields
        """
        self.api.request_positions(d)

    def json_query_order(self, args, d):
        """query_order('id') => {'fieldname': data, ...}

        Return dict containing order status fields for given order id
        """
        oid = str(args['id'])
        if oid in self.api.orders.keys():
            ret = self.api.orders[oid]
        else:
            ret = {oid: {'status:': 'Undefined'}}
        d.callback(ret)

    def json_query_orders(self, args, d):
        """query_orders() => {'order_id': {'field': data, ...}, ...}

        Return dict keyed by order id containing dicts of order data fields
        """
        self.api.request_orders(d)

    def json_query_executions(self, args, d):
        """query_executions() => {'exec_id': {'field': data, ...}, ...}

        Return dict keyed by execution id containing dicts of execution report data fields
        """
        self.api.request_executions(d)

    def json_market_order(self, args, d):
        """market_order('symbol', quantity) => {'field':, data, ...}

        Submit a market order, returning dict containing new order fields
        """
        symbol = str(args['symbol']).upper()
        quantity = int(args['quantity'])
        self.api.market_order(symbol, quantity, d)

    def json_limit_order(self, args, d):
        """limit_order('symbol', price, quantity) => {'field':, data, ...}

        Submit a limit order, returning dict containing new order fields
        """
        symbol = str(args['symbol']).upper()
        price = float(args['price'])
        quantity = int(args['quantity'])
        self.api.limit_order(symbol, price, quantity, d)

    def json_stop_order(self, args, d):
        """stop_order('symbol', price, quantity) => {'field':, data, ...}

        Submit a stop order, returning dict containing new order fields
        """
        symbol = str(args['symbol']).upper()
        price = float(args['price'])
        quantity = int(args['quantity'])
        self.api.stop_order(symbol, price, quantity, d)

    def json_stoplimit_order(self, args, d):
        """stoplimit_order('symbol', stop_price, limit_price, quantity) => {'field':, data, ...}

        Submit a stop-limit order, returning dict containing new order fields
        """
        symbol = str(args['symbol']).upper()
        stop_price = float(args['stop_price'])
        limit_price = float(args['limit_price'])
        quantity = int(args['quantity'])
        self.api.stoplimit_order(symbol, stop_price, limit_price, quantity, d)
        return ret

    def json_query_bars(self, args, d):
        """query_bars('symbol', bar_period, 'start', 'end')
              => ['Status: OK', [time, open, high, low, close, volume], ...]

        Return array containing status strings and lists of bar data if successful
        """
        symbol = str(args['symbol']).upper()
        period = int(args['period'])
        start = str(args['start'])
        end = str(args['end'])
        self.api.query_bars(symbol, period, start, end, d)

    def json_cancel_order(self, args, d):
        """cancel_order('id')

        Request cancellation of a pending order
        """
        oid = str(args['id'])
        self.api.cancel_order(oid, d)

    def json_global_cancel(self, args, d):
        """global_cancel()

        Request cancellation of all pending orders
        """
        self.api.request_global_cancel()
        d.callback('global cancel requested')

    def json_gateway_logon(self, args, d):
        """gateway_logon('username', 'password')

        logon to gateway
        """
        username = str(args['username'])
        password = str(args['password'])
        #self.api.gateway_logon(username, password)
        d.callback('gateway logon unavailable')

    def json_gateway_logoff(self, args, d):
        """gateway_logoff()

        Logoff from gateway
        """
        # self.api.gateway_logoff()
        d.callback('gateway logon unavailable')

    def json_set_primary_exchange(self, args, d):
        """set_primary_exchange(symbol, exchange)

        Set primary exchange for symbol (default is SMART), delete mapping if exchange is None.
        """
        symbol = str(args['symbol']).upper()
        exchange = str(args['exchange'])

        d.callback(self.api.set_primary_exchange(symbol, exchange))

    def json_help(self, args, d):
        help = {}
        for command in self.commands:
            help[command] = getattr(self, 'json_%s' % command).__doc__
        d.callback(help)


class Leaf(Resource):
    def __init__(self, root, cmdfunc):
        Resource.__init__(self)
        self.root = root
        self.cmdfunc = cmdfunc
        self.isLeaf = True

    def render(self, request):
        self.request = request
        user = self.request.getUser()
        password = self.request.getPassword()
        if user == self.root.api.username and password == self.root.api.password:
            return Resource.render(self, request)
        else:
            request.setResponseCode(http.UNAUTHORIZED)
            return json.dumps({'status': 'Unauthorized'})

    def render_POST(self, request):
        # pprint(request.__dict__)
        data = json.loads(request.content.getvalue())
        self.root.output('%s:%d POST %s %s' % (
            request.client.host, request.client.port, request.path, repr(data)))
        d = defer.Deferred()
        d.addCallback(self.api_result, request)
        d.addErrback(self.api_error)
        self.cmdfunc(data, d)
        return NOT_DONE_YET

    def api_result(self, result, request):
        request.write(json.dumps(result))
        request.finish()

    def api_error(self, failure):
        self.root.output('ERROR: API errback: %s' % repr(failure))
        return failure


def webServerFactory(api):
    return Site(webserver(api).root)


if __name__ == '__main__':

    # class API(object):
    #    def __init__(self):
    #        self.username = 'testo'
    #        self.password = 'mesto'
    #
    #    def output(self, msg):
    #        print('API: %s' % msg)

    from txtrader.tws import TWS
    api = TWS()

    endpoint = endpoints.TCP4ServerEndpoint(reactor, 50070)
    endpoint.listen(webServerFactory(api))
    reactor.run()
