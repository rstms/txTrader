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
from datetime import datetime
import ujson as json
from txtrader.version import HEADER

class webserver(object):
    def __init__(self, api):
        self.started = datetime.now()
        self.api = api
        self.output = api.output
        self.root = Resource()
        self.commands = [name[5:]
                         for name in dir(self) if name.startswith('json_')]
        for route in self.commands:
            self.root.putChild(route, Leaf(
                self, getattr(self, 'json_%s' % route)))

    def render(self, d, data):
        d.callback(json.dumps(data))

    def json_shutdown(self, args, d):
        """shutdown(message) 

        Request server shutdown
        """
        message = str(args['message'])
        self.output('ALERT: shutdown: %s' % message)

        # self.output('shutdown()')
        reactor.callLater(1, reactor.stop)
        self.render(d, 'shutdown requested')

    def json_status(self, args, d):
        """status() => 'status string'

        return string describing current API connection status
        """
        self.render(d, self.api.query_connection_status())

    def json_uptime(self, args, d):
        """uptime() => 'uptime string'

        Return string showing start time and elapsed time for current server instance
        """
        uptime = datetime.now() - self.started
        self.render(d, 'started %s (elapsed %s)' % (self.started.strftime('%Y-%m-%d %H:%M:%S'), str(uptime)))


    def json_time(self, args, d):
        """time() => 'time string'

        Return formatted timestamp string (YYYY-MM-DD HH:MM:SS) matching latest datafeed time update
        """
        t = self.api.now
        self.render(d, '%s' % (t.strftime('%Y-%m-%d %H:%M:%S') if t else t))

    def json_version(self, args, d):
        """version() => 'version string'

        Return string containing release version of current server instance
        """
        ret = {}
        ret['txtrader'] = HEADER
        ret['python'] = sys.version
        ret['flags'] = self.api.flags()
        #ret['pip'] = check_output('pip list', shell=True)
        self.render(d, ret)

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
        self.render(d, self.api.symbol_disable(symbol, self))

    def json_query_symbols(self, args, d):
        """query_symbols() => ['symbol', ...]

        Return the list of active symbols
        """
        self.render(d, self.api.symbols.keys())

    def json_query_symbol(self, args, d):
        """query_symbol('symbol') => {'fieldname': data, ...}

        Return dict containing current data for given symbol
        """
        symbol = str(args['symbol']).upper()
        ret = None
        if symbol in self.api.symbols.keys():
            ret = self.api.symbols[symbol].export()
        self.render(d, ret)

    def json_query_symbol_data(self, args, d):
        """query_symbol_data('symbol') => {'fieldname': data, ...}

        Return dict containing rawdata for given symbol
        """
        symbol = str(args['symbol']).upper()
        ret = None
        if symbol in self.api.symbols.keys():
            ret = self.api.symbols[symbol].rawdata
        self.render(d, ret)

    def json_query_symbol_bars(self, args, d):
        """query_symbol_bars('symbol') => [[barchart data], ...]

        Return array of current live bar data for given symbol
        """
        symbol = str(args['symbol']).upper()
        ret = None
        if symbol in self.api.symbols.keys():
            api_symbol = self.api.symbols[symbol]
            ret = api_symbol.barchart_render()
        self.render(d, ret)

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
            fields = args['fields']
            fields = [str(f) for f in fields.split(',')] if ',' in fields else [fields]
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

        Return dict containing order/ticket status fields for given order id
        """
        oid = str(args['id'])
        self.api.request_order(oid, d)

    def json_query_orders(self, args, d):
        """query_orders() => {'order_id': {'field': data, ...}, ...}

        Return dict keyed by order id containing dicts of order data fields
        """
        self.api.request_orders(d)

    def json_query_tickets(self, args, d):
        """query_tickets() => {'order_id': {'field': data, ...}, ...}

        Return dict keyed by order id containing dicts of staged order ticket data fields
        """
        self.api.request_tickets(d)

    def json_query_executions(self, args, d):
        """query_executions() => {'exec_id': {'field': data, ...}, ...}

        Return dict keyed by execution id containing dicts of execution report data fields
        """
        self.api.request_executions(d)

    def json_market_order(self, args, d):
        """market_order('account', 'symbol', quantity) => {'field':, data, ...}

        Submit a market order, returning dict containing new order fields
        """
        account = str(args['account'])
        route = args['route']
        symbol = str(args['symbol']).upper()
        quantity = int(args['quantity'])
        self.api.market_order(account, route, symbol, quantity, d)

    def json_limit_order(self, args, d):
        """limit_order('account', 'symbol', price, quantity) => {'field':, data, ...}

        Submit a limit order, returning dict containing new order fields
        """
        account = str(args['account'])
        route = args['route']
        symbol = str(args['symbol']).upper()
        price = float(args['limit_price'])
        quantity = int(args['quantity'])
        self.api.limit_order(account, route, symbol, price, quantity, d)

    def json_stop_order(self, args, d):
        """stop_order('account', 'symbol', price, quantity) => {'field':, data, ...}

        Submit a stop order, returning dict containing new order fields
        """
        account = str(args['account'])
        route = args['route']
        symbol = str(args['symbol']).upper()
        price = float(args['stop_price'])
        quantity = int(args['quantity'])
        self.api.stop_order(account, route, symbol, price, quantity, d)

    def json_stoplimit_order(self, args, d):
        """stoplimit_order('account', 'symbol', stop_price, limit_price, quantity) => {'field':, data, ...}

        Submit a stop-limit order, returning dict containing new order fields
        """
        account = str(args['account'])
        route = args['route']
        symbol = str(args['symbol']).upper()
        stop_price = float(args['stop_price'])
        limit_price = float(args['limit_price'])
        quantity = int(args['quantity'])
        self.api.stoplimit_order(account, route, symbol, stop_price, limit_price, quantity, d)

    def json_query_bars(self, args, d):
        """query_bars('symbol', bar_period, 'start', 'end')
              => ['Status: OK', [time, open, high, low, close, volume], ...]

        Return array containing status strings and lists of bar data if successful
        """
        symbol = str(args['symbol']).upper()
        period = str(args['period']).upper()
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
        self.render(d, 'global cancel requested')

    def json_gateway_logon(self, args, d):
        """gateway_logon('username', 'password')

        logon to gateway
        """
        username = str(args['username'])
        password = str(args['password'])
        #self.api.gateway_logon(username, password)
        self.render(d, 'gateway logon unavailable')

    def json_gateway_logoff(self, args, d):
        """gateway_logoff()

        Logoff from gateway
        """
        # self.api.gateway_logoff()
        self.render(d, 'gateway logon unavailable')

    def json_set_primary_exchange(self, args, d):
        """set_primary_exchange(symbol, exchange)

        Set primary exchange for symbol (default is SMART), delete mapping if exchange is None.
        """
        symbol = str(args['symbol']).upper()
        exchange = str(args['exchange'])

        self.render(d, self.api.set_primary_exchange(symbol, exchange))

    def json_stage_market_order(self, args, d):
        """stage_market_order('tag', 'account', 'symbol', quantity) => {'fieldname': data, ...}

        Submit a staged market order (displays as staged in GUI, requiring manual aproval), returning dict containing new order fields
        """
        account = str(args['account'])
        tag = str(args['tag'])
        route = args['route']
        symbol = str(args['symbol']).upper()
        quantity = int(args['quantity'])
        self.api.stage_market_order(tag, account, route, symbol, quantity, d)

    def json_get_order_route(self, args, d):
        """get_order_route() => {'route_name', None | {parameter_name: parameter_value, ...}}

        Return current order route as a dict
        """
        self.api.get_order_route(d)

    def json_set_order_route(self, args, d):
        """set_order_route(route) => True if success, else False

        Set order route data given route {'route_name': {parameter: value, ...} (JSON string will be parsed into a route dict)}
        """
        route = args['route']
        self.api.set_order_route(route, d)

    def json_help(self, args, d):
        """help() => {'command': 'command(parameters) => return', ...}

        Return dict containing brief documentation for each command
        """
        help = {}
        for command in self.commands:
            help[command] = getattr(self, 'json_%s' % command).__doc__
        self.render(d, help)

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

    def render_GET(self, request):
        data = {}
        # get only supports a single value for each named parameter
        for key, value in request.args.iteritems():
          data[key]=value[0]
        self.root.output('RX GET %s:%d %s %s' % (request.client.host, request.client.port, request.path, repr(data)))
        request.setHeader('Content-type', 'application/json')
        d = defer.Deferred()
        d.addCallback(request.write)
        d.addCallback(lambda ign: request.finish())
        d.addErrback(self.api_timeout, request)
        d.addErrback(lambda ign: request.finish())
        self.cmdfunc(data, d)
        return NOT_DONE_YET

    def api_timeout(self, failure, request):
        self.root.output('WARNING: API timeout errback: %s' % repr(failure))
        request.setResponseCode(504)
        return failure

    def render_POST(self, request):
        # pprint(request.__dict__)
        data = json.loads(request.content.getvalue())
        self.root.output('RX POST %s:%d %s %s' % (request.client.host, request.client.port, request.path, repr(data)))
        request.setHeader('Content-type', 'application/json')
        d = defer.Deferred()
        d.addCallback(request.write)
        d.addCallback(lambda ign: request.finish())
        d.addErrback(self.api_error, request)
        d.addErrback(lambda ign: request.finish())
        self.cmdfunc(data, d)
        return NOT_DONE_YET

    def api_error(self, failure, request):
        self.root.output('ALERT: API errback: %s' % repr(failure))
        request.setResponseCode(500)
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
