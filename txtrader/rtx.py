#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
  rtx.py
  ------

  RealTick API interface module

  Copyright (c) 2015 Reliance Systems Inc. <mkrueger@rstms.net>
  Licensed under the MIT license.  See LICENSE for details.

"""
import sys
import os
import types
from uuid import uuid1
import ujson as json
import time
from collections import OrderedDict
from hexdump import hexdump
import pytz
import tzlocal
import datetime
import re
from pprint import pprint
from copy import deepcopy

from txtrader.config import Config
from txtrader.tcpserver import tcpserver
from txtrader import HEADER
from txtrader import REVISION

from logging import getLevelName, DEBUG, INFO, WARNING, ERROR, CRITICAL
import traceback

CALLBACK_METRIC_HISTORY_LIMIT = 1024

TIMEOUT_TYPES = ['DEFAULT', 'ACCOUNT', 'ADDSYMBOL', 'ORDER', 'ORDERSTATUS', 'POSITION', 'TIMER', 'BARCHART']

# default RealTick orders to NYSE and Stock type
RTX_EXCHANGE = 'NYS'
RTX_STYPE = 1

BARCHART_FIELDS = 'DISP_NAME,TRD_DATE,TRDTIM_1,OPEN_PRC,HIGH_1,LOW_1,SETTLE,ACVOL_1'
BARCHART_TOPIC = 'LIVEQUOTE'

DEFAULT_EXECUTION_FIELDS = 'ORDER_ID,ORIGINAL_ORDER_ID,BANK,BRANCH,CUSTOMER,DEPOSIT,AVG_PRICE,BUYORSELL,CURRENCY,CURRENT_STATUS,DISP_NAME,EXCHANGE,EXIT_VEHICLE,FILL_ID,ORDER_RESIDUAL,ORIGINAL_PRICE,ORIGINAL_VOLUME,PRICE,PRICE_TYPE,TIME_STAMP,TIME_ZONE,MARKET_TRD_DATE,TRD_TIME,VOLUME,VOLUME_TRADED,CUSIP'

DEBUG_TRUNCATE_RESULTS = 32

from twisted.python import log
from twisted.python.failure import Failure
from twisted.internet.protocol import Protocol, ReconnectingClientFactory
from twisted.protocols.basic import LineReceiver
from twisted.internet import reactor, defer
from twisted.internet.task import LoopingCall
from twisted.web import server
from socket import gethostname

# set 256MB line buffer
LINE_BUFFER_LENGTH = 0x10000000


class RtxClient(LineReceiver):
    delimiter = b'\n'
    MAX_LENGTH = LINE_BUFFER_LENGTH

    def __init__(self, rtx):
        self.rtx = rtx

    def lineReceived(self, data):

        try:
            self.rtx.gateway_receive(data)
        except Exception as exc:
            self.rtx.error_handler(repr(self), repr(exc))
            traceback.print_exc()
            self.rtx.check_exception_halt(exc, self)

    def connectionMade(self):
        self.rtx.gateway_connect(self)

    def lineLengthExceeded(self, line):
        self.rtx.force_disconnect(f"RtxClient: Line length exceeded: line={repr(line)}")


class RtxClientFactory(ReconnectingClientFactory):
    initialDelay = 15
    maxDelay = 60

    def __init__(self, rtx):
        self.rtx = rtx

    def startedConnecting(self, connector):
        self.rtx.info('RTGW: Started to connect.')

    def buildProtocol(self, addr):
        self.rtx.info('RTGW: Connected.')
        self.resetDelay()
        return RtxClient(self.rtx)

    def clientConnectionLost(self, connector, reason):
        self.rtx.error(f"{self} Lost Connection: {reason}")
        ReconnectingClientFactory.clientConnectionLost(self, connector, reason)
        self.rtx.gateway_connect(None)

    def clientConnectionFailed(self, connector, reason):
        self.rtx.error(f"{self} Connection failed: {reason}")
        ReconnectingClientFactory.clientConnectionFailed(self, connector, reason)
        self.rtx.gateway_connect(None)


class API_Symbol(object):

    def __init__(self, api, symbol, client_id, init_callback):
        self.id = str(uuid1())
        self.api = api
        self.symbol = symbol
        self.clients = set([client_id]) if client_id else set()
        self.callback = init_callback
        self.clear()
        self.register()
        self.api.debug(f"{repr(self)}.__init__(..., {client_id}, {init_callback})")
        self.api_initial_request()

    def __del__(self):
        self.api.debug(f"__del__({self})")
        self.api_cancel_updates()
        self.deregister()

    def register(self):
        self.api.symbols[self.symbol] = self

    def deregister(self):
        if self.symbol in self.api.symbols:
            self.api.symbols.pop(self.symbol)

    def __repr__(self):
        return f"{__class__.__name__}<{hex(id(self))} {self.symbol}>"

    def __str__(self):
        return f"{repr(self)} bid={self.bid} bidsize={self.bid_size} ask={self.ask} asksize={self.ask_size} last={self.last} size={self.size} volume={self.volume} close={self.close} vwap={self.vwap} clients={self.clients}"

    def clear(self):
        self.fullname = ''
        self.cusip = ''
        self.bid = 0.0
        self.bid_size = 0
        self.ask = 0.0
        self.ask_size = 0
        self.last = 0.0
        self.size = 0
        self.volume = 0
        self.open = 0.0
        self.close = 0.0
        self.vwap = 0.0
        self.high = 0.0
        self.low = 0.0
        self.minute_high = 0.0
        self.minute_low = 0.0
        self.last_trade_time = '00:00:00'
        self.last_trade_minute = -1
        self.last_api_minute = -1
        self.rawdata = {}
        self.last_quote = None
        self.last_trade = None
        self.barchart = {}

    def api_initial_request(self):
        # request initial data
        self.api.info(f"Requesting initial API data for {self.symbol}")
        self.cxn_updates = None
        self.cxn_init = self.api.cxn_get('TA_SRV', 'LIVEQUOTE')
        init_callback = RTX_LocalCallback(self.api, self.init_handler, self.init_failed)
        cb = API_Callback(self.api, self.cxn_init.id, 'init_symbol', init_callback, self.api.callback_timeout['ADDSYMBOL'])
        self.cxn_init.request('LIVEQUOTE', '*', f"DISP_NAME='{self.symbol}'", cb)

    def api_request_updates(self):
        # enable live price updates
        self.api.info(f"Adding {self.symbol} to API watchlist")
        service, topic, table, what, where = self.quotes_advise_fields()
        self.cxn_updates = self.api.cxn_get(service, topic)
        self.cxn_updates.advise(table, what, where, self.parse_fields)

    def api_cancel_updates(self):
        # disable live price updates
        self.api.info(f"Removing {self.symbol} from API watchlist")
        if self.cxn_updates:
            service, topic, table, what, where = self.quotes_advise_fields()
            cancel_callback = RTX_LocalCallback(self.api, self.cancel_handler, self.cancel_failed)
            cb = API_Callback(self.api, self.cxn_updates.id, 'unadvise', cancel_callback)
            self.cxn_updates.unadvise(table, what, where, cb)
            self.cxn_updates = None

    def cancel_handler(self, data):
        self.api.debug(f"{self} advise terminated: {data}")

    def cancel_failed(self, error):
        self.api.error_handler(self, f"advise cancel failed: {error}")

    def is_valid(self):
        # if rawdata is present, and it doesn't contain the key 'SYMBOL_ERROR' then the symbol is valid
        ret = None
        if self.rawdata:
            if not 'SYMBOL_ERROR' in self.rawdata:
                ret = True
        return ret

    def export(self, field_filter=None):
        if field_filter:
            ret = {f: self.rawdata[f] for f in field_filter}
        else:
            ret = {
                'symbol': self.symbol,
                'last': self.last,
                'tradetime': self.last_trade_time,
                'size': self.size,
                'volume': self.volume,
                'open': self.open,
                'close': self.close,
                'vwap': self.vwap,
                'fullname': self.fullname,
                'cusip': self.cusip,
            }
            if self.api.enable_high_low:
                ret['high'] = self.high
                ret['low'] = self.low
            if self.api.enable_ticker:
                ret['bid'] = self.bid
                ret['bidsize'] = self.bid_size
                ret['ask'] = self.ask
                ret['asksize'] = self.ask_size
            if self.api.enable_symbol_barchart:
                ret['bars'] = self.barchart_render()
        return ret

    def add_client(self, client):
        self.api.info(f"{self} adding client {client}")
        self.clients.add(client)

    def del_client(self, client):
        self.api.info(f"{self} deleting client {client}")
        self.clients.discard(client)
        if not len(self.clients):
            self.api_cancel_updates()
            self.deregister()

    def update_quote(self):
        quote = f"quote.{self.symbol}:{self.bid} {self.bid_size} {self.ask} {self.ask_size}"
        if quote != self.last_quote:
            self.last_quote = quote
            self.api.WriteAllClients(quote, option_flag='quotes')

    def update_trade(self):
        trade = f"trade.{self.symbol}:{self.last} {self.size} {self.volume}"
        if trade != self.last_trade:
            self.last_trade = trade
            self.api.WriteAllClients(trade, option_flag='trades')

    def init_handler(self, data):
        self.api.debug(f"{self} init_handler({data})")
        # handle response from new symbol initial Request
        self.parse_fields(None, data[0])
        # this is the initial init, so store the rawdata with the full field set
        self.rawdata = {}
        self.update_rawdata(data[0])
        self.cxn_init = None

        # if this is a valid symbol and barchart is enabled, request an initial chart
        if self.api.enable_symbol_barchart and self.is_valid():
            self.barchart_query('.', self.complete_barchart_init, self.barchart_init_failed)
        else:
            self.complete_symbol_init()

    def update_rawdata(self, data):
        self.rawdata.update(data)
        for k, v in self.rawdata.items():
            if str(v).startswith('Error '):
                self.rawdata[k] = ''

    def init_failed(self, error):
        self.api.error(f"{self} init_failed({error})")
        self.api.error_handler(f"{self}", f"Initial {self.symbol} query failed; {error}")

    def barchart_query(self, start, callback, errback):
        self.api.debug(f"{self} barchart_query({repr((start, callback, errback))})")
        self.api.query_bars(self.symbol, 1, start, '.', RTX_LocalCallback(self.api, callback, errback))

    def barchart_init_failed(self, error):
        self.api.error(f"{self} barchart_init_failed({error})")
        self.api.error_handler(f"{self}", 'Initial BARCHART query failed for symbol %s: %s' % (self.symbol, repr(error)))

    def barchart_query_failed(self, error):
        self.api.error(f"{self} barchart_query_failed")
        self.api.error_handler(f"{self}", 'BARCHART query failed for symbol %s: %s' % (self.symbol, repr(error)))

    def complete_barchart_init(self, bars):
        self.api.debug(f"{self} complete_barchart_init([{len(bars)} bars])")
        self.barchart_update(bars)
        self.complete_symbol_init()

    def complete_symbol_init(self):
        self.api.debug(f"{self} complete_symbol_init")
        # call the api symbol init to return data to the requesting client
        if self.api.symbol_init(self):
            # symbol_init returned True indicating a valid symbol, so request api updates
            self.api_request_updates()

    def quotes_advise_fields(self):
        service = 'TA_SRV'
        topic = 'LIVEQUOTE'
        table = 'LIVEQUOTE'
        what = 'TRD_DATE,TRDTIM_1,TRDPRC_1,TRDVOL_1,ACVOL_1,OPEN_PRC,HST_CLOSE,VWAP'
        if self.api.enable_ticker:
            what += ',BID,BIDSIZE,ASK,ASKSIZE'
        if self.api.enable_high_low:
            what += ',HIGH_1,LOW_1'
        where = "DISP_NAME='%s'" % self.symbol
        return (service, topic, table, what, where)

    def parse_fields(self, cxn, data):
        """handle ADVISE updates received from the API"""
        trade_flag = False
        quote_flag = False
        pid = 'API_Symbol(%s)' % self.symbol

        if data == None:
            self.api.force_disconnect('LIVEQUOTE Advise has been terminated by API for %s' % pid)
            return

        self.update_rawdata(data)

        if 'TRDPRC_1' in data:
            self.last = self.api.parse_tql_float(data['TRDPRC_1'], pid, 'TRDPRC_1')
            trade_flag = True
            if 'TRDTIM_1' in data and 'TRD_DATE' in data:
                self.last_trade_time = ' '.join(self.api.format_barchart_date(data['TRD_DATE'], data['TRDTIM_1'], pid))
            else:
                self.api.error_handler(f"{self}", 'TRDPRC_1 without TRD_DATE, TRDTIM_1')

            # don't request a barchart update during the symbol init processing
            if self.api.enable_symbol_barchart and (not self.cxn_init):
                # query a barchart update after each trade
                # TODO: revisit this: can a barchart use ADVISE instead?
                self.barchart_query('-5', self.barchart_update, self.barchart_query_failed)

        if 'HIGH_1' in data:
            self.high = self.api.parse_tql_float(data['HIGH_1'], pid, 'HIGH_1')
            trade_flag = True
        if 'LOW_1' in data:
            self.low = self.api.parse_tql_float(data['LOW_1'], pid, 'LOW_1')
            trade_flag = True
        if 'TRDVOL_1' in data:
            self.size = self.api.parse_tql_int(data['TRDVOL_1'], pid, 'TRDVOL_1')
            trade_flag = True
        if 'ACVOL_1' in data:
            self.volume = self.api.parse_tql_int(data['ACVOL_1'], pid, 'ACVOL_1')
            trade_flag = True
        if 'BID' in data:
            self.bid = self.api.parse_tql_float(data['BID'], pid, 'BID')
            if self.bid and 'BIDSIZE' in data:
                self.bidsize = self.api.parse_tql_int(data['BIDSIZE'], pid, 'BIDSIZE')
            else:
                self.bidsize = 0
            quote_flag = True
        if 'ASK' in data:
            self.ask = self.api.parse_tql_float(data['ASK'], pid, 'ASK')
            if self.ask and 'ASKSIZE' in data:
                self.asksize = self.api.parse_tql_int(data['ASKSIZE'], pid, 'ASKSIZE')
            else:
                self.asksize = 0
            quote_flag = True
        if 'COMPANY_NAME' in data:
            self.fullname = self.api.parse_tql_str(data['COMPANY_NAME'], pid, 'COMPANY_NAME')
        if 'CUSIP' in data:
            self.cusip = self.api.parse_tql_str(data['CUSIP'], pid, 'CUSIP')
        if 'OPEN_PRC' in data:
            self.open = self.api.parse_tql_float(data['OPEN_PRC'], pid, 'OPEN_PRC')
        if 'HST_CLOSE' in data:
            self.close = self.api.parse_tql_float(data['HST_CLOSE'], pid, 'HST_CLOSE')
        if 'VWAP' in data:
            self.vwap = self.api.parse_tql_float(data['VWAP'], pid, 'VWAP')

        if self.api.enable_ticker:
            if quote_flag:
                self.update_quote()
            if trade_flag:
                self.update_trade()

    def barchart_render(self):
        return [key.split(' ') + self.barchart[key] for key in sorted(list(self.barchart.keys()))]

    def barchart_update(self, bardata):
        bars_found = False
        if bardata:
            bars = json.loads(bardata)
            if bars:
                for bar in bars:
                    self.barchart['%s %s' % (bar[0], bar[1])] = bar[2:]
                    bars_found = True
        if not bars_found:
            self.api.error_handler(self.symbol, 'barchart_update: no bars found in %s' % repr(bardata))


class API_Execution(object):

    def __init__(self, api, oid, callback=None):
        self.api = api
        self.oid = oid
        self.callback = callback
        self.api.debug(f"{self}.__init__(..., {self.callback})")
        self.fids = DEFAULT_EXECUTION_FIELDS.split(',')
        self.fields = {}

    def __del__(self):
        self.api.debug(f"__del__({self})")

    def __repr__(self):
        return f"{__class__.__name__}<{hex(id(self))} {self.oid}>"

    def initial_update(self, data):
        self.api.debug(f"{self} initial_update {data}")
        self.update(data, True)
        if self.callback:
            self.callback.complete(self.render())
            self.callback = None

    def update(self, data, init=False):
        self.api.debug(f"{self} update {data} {init}")
        order_id = data.get('ORDER_ID')
        self.symbol = data.get('DISP_NAME')
        self.cusip = data.get('CUSIP')
        if self.symbol and not self.cusip:
            self.cusip = self.api.get_cusip(self.symbol)
            data['CUSIP'] = self.cusip

        unchanged = set(self.fields.keys())
        changed = set()
        added = set()

        if order_id == self.oid:
            for k, v in data.items():
                if k in self.fields:
                    if self.fields[k] == v:
                        unchanged.add(k)
                    else:
                        self.fields[k] = v
                        changed.add(k)
                        unchanged.remove(k)
                else:
                    self.fields[k] = v
                    added.add(k)

            if (changed or added) and (not init):
                self.api.send_execution_update(self.render())
        else:
            self.api.error_handler(self.oid, f"Execution Update ORDER_ID mismatch: {repr(data)}")

    def render(self):
        self.api.debug(f"{self} render")
        result = {f: self.fields.get(f) for f in self.fids}
        if self.api.enable_execution_account_format:
            result['ACCOUNT'] = self.api.make_account(self.fields)
            result.pop('BANK')
            result.pop('BRANCH')
            result.pop('CUSTOMER')
            result.pop('DEPOSIT')

        return result


class API_Update():

    def __init__(self, api, symbol, fields, callback):
        self.api = api
        self.symbol = symbol
        self.fields = fields
        self.callback = callback
        self.api.debug(f"{self}.__init__(..., {callback})")

    def __del__(self):
        self.api.debug(f"__del__({self})")

    def __str__(self):
        return repr(self)

    def __repr__(self):
        return f"{__class__.__name__}<{hex(id(self))} {self.symbol} {len(self.fields)}>"


class API_Order_Update(API_Update):

    def __repr__(self):
        return f"{__class__.__name__}<{hex(id(self))} {self.symbol} {len(self.fields)}>"

    def run_callback(self):
        symbol = self.api.symbols.get(self.symbol)
        if symbol:
            cusip = self.api.symbols[self.symbol].cusip
        else:
            cusip = ''
        self.fields['cusip'] = cusip
        self.fields['raw']['CUSIP'] = cusip
        if self.fields['updates']:
            self.fields['updates'][0]['fields']['CUSIP'] = cusip
        self.callback(self.fields, mapped=True)


class API_Execution_Update(API_Update):

    def __repr__(self):
        return f"{__class__.__name__}<{hex(id(self))} {self.symbol} {len(self.fields)}>"

    def run_callback(self):
        symbol = self.api.symbols.get(self.symbol)
        if symbol:
            cusip = symbol.cusip
        else:
            cusip = ''
        self.fields['CUSIP'] = cusip
        self.callback(self.fields, mapped=True)


class API_Update_Mapper():

    def __init__(self, api, symbol):
        self.api = api
        self.symbol = symbol
        self.updates = []  # updates are API_Update
        self.api.debug(f"{self}.__init__(...)")
        self.register_as_pending(True)

    def __del__(self):
        self.api.debug(f"__del__({self})")

    def __repr__(self):
        return f"{__class__.__name__}<{hex(id(self))} {self.symbol} {self.updates if self.api.log_level==DEBUG else len(self.updates)}>"

    def add_update(self, update):
        self.updates.append(update)
        self.api.debug(f"{self} add_update")
        if len(self.updates) == 1:
            self.api.debug(f"{self} initial update, enabling symbol {self.symbol}")
            cb = RTX_LocalCallback(self.api, self.handle_response, self.handle_failure)
            self.api.symbol_enable(self.symbol, self.api, cb, timeout_type='ORDERSTATUS')

    def handle_response(self, response):
        self.api.debug(f"{self} handle_response {response}")
        while len(self.updates):
            update = self.updates.pop(0)
            self.api.debug(f"{self} sending amended update: {update}")
            update.run_callback()
        # remove the pending list entry (that contains self)
        self.register_as_pending(False)

    def handle_failure(self, error):
        self.api.error(f"{self} handle_failure")
        self.api.error_handler(f"{self}", f"Update Mapping for {self.symbol} failed; {error}")
        self.register_as_pending(False)

    def register_as_pending(self, pending_status):
        current_mapper = self.api.pending_mapper_lookups.get(self.symbol, None)
        if current_mapper == self:
            if pending_status:
                self.api.error(f"{self}: multiple pending mapper registration attempts for {self.symbol}")
            else:
                self.api.output(f'Clearing pending mapper registration for {self.symbol} <{hex(id(self))}>')
                self.api.pending_mapper_lookups.pop(self.symbol)
        elif current_mapper:
            # current exists but is not self
            self.api.error(
                f"{self}: Failed to {'register' if pending_status else 'clear'} pending mapper registration for {self.symbol} because another registration exists for {repr(current_mapper)}"
            )
        else:
            # current is None
            if pending_status:
                self.api.output(f'Registering pending mapper for {self.symbol} <{hex(id(self))}>')
                self.api.pending_mapper_lookups[self.symbol] = self
            else:
                self.api.error(
                    f"{self}: Failed to clear pending mapper registration because no registration exists for for {self.symbol}"
                )


class API_Order(object):

    def __init__(self, api, oid, data, origin, callback=None):
        self.api = api
        self.oid = oid
        self.data = data
        self.origin = origin
        self.callback = callback
        self.api.debug(f"{self}.__init__({self.oid}, {len(self.data)}, {self.origin}, {self.callback})")
        self.updates = []
        self.suborders = {}
        self.fields = {}
        self.identified = False
        self.ticket = 'undefined'
        data['status'] = 'Initialized'
        data['origin'] = origin
        self.update(data, init=True)

    def __del__(self):
        self.api.debug(f"__del__({self})")

    def __repr__(self):
        return f"{__class__.__name__}<{hex(id(self))}>"

    def identify_order_type(self, data):
        if not self.identified:
            if 'TYPE' in data:
                otype = data['TYPE']
                # set ticket flag based on first TYPE encountered
                self.ticket = 'ticket' if otype.startswith('UserSubmitStaged') else 'order'
                self.fields['type'] = otype
                self.identified = True

    def initial_update(self, data):
        self.update(data)
        if self.callback:
            self.callback.complete(self.render())
            self.callback = None

    def update(self, data, init=False):

        field_state = json.dumps(self.fields)

        self.identify_order_type(data)

        if 'ORDER_ID' in data:
            order_id = data['ORDER_ID']
            if order_id in self.suborders:
                if data == self.suborders[order_id]:
                    change = 'dup'
                else:
                    change = 'changed'
            else:
                change = 'new'
            self.suborders[order_id] = data
        else:
            if init:
                order_id = '(init)'
                change = 'new'
            else:
                self.api.error_handler(self.oid, 'Order Update without ORDER_ID: %s' % repr(data))
                order_id = 'unknown'
                change = 'error'

        if 'DISP_NAME' in data and not 'CUSIP' in data:
            data['CUSIP'] = self.api.get_cusip(data['DISP_NAME'])

        # default to display only in debug mode
        display_func = self.api.debug
        if self.api.log_order_updates:
            # if selected, output updates
            display_func = self.api.output
            # handle dups differently
            if change == 'dup':
                if not self.api.log_order_update_dups:
                    # if log dups is not selected, stay at debug default
                    display_func = self.api.debug
        display_func(f"ORDER: {data['TYPE']} {change} OID={self.oid} ORDER_ID={order_id}")

        # only apply new or changed messages to the base order; (don't move order status back in time when refresh happens)

        if change in ['new', 'changed']:
            changes = {}
            for k, v in data.items():
                ov = self.fields.setdefault(k, None)
                self.fields[k] = v
                if v != ov:
                    changes[k] = v

            if changes:
                update_type = data['TYPE'] if 'TYPE' in data else 'Undefined'
                if self.api.log_order_updates:
                    self.api.debug(f"ORDER_CHANGES: {update_type} OID={self.oid} ORDER_ID={order_id} {repr(changes)}")

                    unchanged_fields = {k: v for k, v in data.items() if not k in changes}
                    self.api.debug(f"UNCHANGED_FIELDS: {unchanged_fields}")
                self.updates.append({'id': order_id, 'type': update_type, 'fields': changes, 'time': time.time()})

        if not init:
            if json.dumps(self.fields) != field_state:
                self.api.send_order_update(self.render())

    def update_fill_fields(self):
        if self.fields['TYPE'] in ['UserSubmitOrder', 'ExchangeTradeOrder']:
            if 'VOLUME_TRADED' in self.fields:
                self.fields['filled'] = self.fields['VOLUME_TRADED']
            if 'ORDER_RESIDUAL' in self.fields:
                self.fields['remaining'] = self.fields['ORDER_RESIDUAL']
            if 'AVG_PRICE' in self.fields:
                self.fields['avgfillprice'] = self.fields['AVG_PRICE']

    def render(self):
        # customize fields for standard txTrader order status
        if 'ORIGINAL_ORDER_ID' in self.fields:
            self.fields['permid'] = self.fields['ORIGINAL_ORDER_ID']
        self.fields['symbol'] = self.fields['DISP_NAME']
        self.fields['cusip'] = self.fields['CUSIP']
        self.fields['account'] = self.api.make_account(self.fields)
        self.fields['quantity'] = self.fields['VOLUME']
        self.fields['class'] = self.ticket

        status = self.fields.setdefault('CURRENT_STATUS', 'UNDEFINED')
        otype = self.fields.setdefault('TYPE', 'Undefined')
        #print('render: permid=%s ORDER_ID=%s CURRENT_STATUS=%s TYPE=%s' % (self.fields['permid'], self.fields['ORDER_ID'], status, otype))
        #pprint(self.fields)
        if status == 'PENDING':
            self.fields['status'] = 'Submitted'
        elif status == 'LIVE':
            self.fields['status'] = 'Pending'
            self.update_fill_fields()
        elif status == 'COMPLETED':
            if self.is_filled():
                self.fields['status'] = 'Filled'
                if otype == 'ExchangeTradeOrder':
                    self.update_fill_fields()
            elif otype in ['UserSubmitOrder', 'UserSubmitStagedOrder', 'UserSubmitStatus', 'ExchangeReportStatus']:
                self.fields['status'] = 'Submitted'
                self.update_fill_fields()
            elif otype == 'UserSubmitCancel':
                self.fields['status'] = 'Cancelled'
            elif otype in ['UserSubmitChange', 'AdjustQty']:
                self.fields['status'] = 'Changed'
            elif otype == 'ExchangeAcceptOrder':
                self.fields['status'] = 'Accepted'
            elif otype == 'ExchangeTradeOrder':
                self.update_fill_fields()
            elif otype in ['ClerkReject', 'ExchangeKillOrder']:
                self.fields['status'] = 'Error'
            else:
                self.api.error_handler(self.oid, 'Unknown TYPE: %s' % otype)
                self.fields['status'] = 'Error'
        elif status == 'CANCELLED':
            self.fields['status'] = 'Cancelled'
        elif status == 'DELETED':
            self.fields['status'] = 'Error'
        else:
            self.api.error_handler(self.oid, 'Unknown CURRENT_STATUS: %s' % status)
            self.fields['status'] = 'Error'

        self.fields['updates'] = self.updates
        f = self.fields
        self.fields['text'] = '%s %d %s (%s)' % (f['BUYORSELL'], int(f['quantity']), f['symbol'], f['status'])

        ret = {'raw': {}}
        for k, v in self.fields.items():
            if k.islower():
                ret[k] = v
            else:
                ret['raw'][k] = v
        return ret

    def is_filled(self):
        return bool(
            self.fields['CURRENT_STATUS'] == 'COMPLETED' and self.has_fill_type() and 'ORIGINAL_VOLUME' in self.fields
            and 'VOLUME_TRADED' in self.fields and self.fields['ORIGINAL_VOLUME'] == self.fields['VOLUME_TRADED']
        )

    def is_cancelled(self):
        return bool(
            self.fields['CURRENT_STATUS'] == 'COMPLETED' and 'status' in self.fields and self.fields['status'] == 'Error'
            and 'REASON' in self.fields and self.fields['REASON'] == 'User cancel'
        )

    def has_fill_type(self):
        if self.fields['TYPE'] == 'ExchangeTradeOrder':
            return True
        for update_type in [update['type'] for update in self.updates]:
            if update_type == 'ExchangeTradeOrder':
                return True
        return False


class API_Callback(object):

    def __init__(self, api, id, label, callable, timeout=0):
        """callable is stored and used to return results later"""
        self.api = api
        self.id = id
        self.label = label
        self.callable = callable
        self.started = time.time()
        self.timeout = timeout or api.callback_timeout['DEFAULT']
        self.api.debug(f"{self}.__init__(..., {self.id}, {self.label}, {self.callable}, {self.timeout})")
        self.expire = self.started + timeout
        self.done = False
        self.data = None
        self.expired = False

    def __del__(self):
        self.api.debug(f"__del__({self})")

    def __repr__(self):
        return f"{__class__.__name__}<{hex(id(self))} {self.label}>"

    def __str__(self):
        return repr(self)

    def complete(self, results):
        """complete callback by calling callable function with value of results"""
        self.api.debug(f"{self}.complete({repr(results)[:DEBUG_TRUNCATE_RESULTS]})")
        self.elapsed = time.time() - self.started
        if not self.done:
            ret = self.format_results(results)
            # TODO: fix sendString test
            if self.callable.callback.__name__ == 'sendString':
                ret = '%s.%s: %s' % (self.api.channel, self.label, ret)
            self.callable.callback(ret)
            self.callable = None
            self.done = True
        else:
            self.api.error_handler(
                self.id, '%s completed after timeout: callback=%s elapsed=%.2f' % (self.label, f"{self}", self.elapsed)
            )
            self.api.debug(f"{self} results={repr(results)[:DEBUG_TRUNCATE_RESULTS]}")
        self.api.record_callback_metrics(self.label, int(self.elapsed * 1000), self.expired)

    def check_expire(self):
        if not self.done:
            self.api.debug(
                f"{self} check_expire: {datetime.datetime.fromtimestamp(self.started).time().isoformat()} {round(self.expire - time.time(), 1)}"
            )
            if time.time() > self.expire:
                msg = f"callback expired: {self}"
                self.api.error_handler(self, msg)
                # TODO: fix sendString test
                if self.callable.callback.__name__ == 'sendString':
                    self.callable.callback(f"{self.api.channel}.error: {msg}")
                else:
                    self.callable.errback(Failure(Exception(msg)))
                self.expired = True
                self.done = True

    # TODO: all of these format_* really belong in the api class

    def format_results(self, results):
        self.api.debug(f"{self} format_results {self.label}")
        if self.label == 'account_data':
            results = self.format_account_data(results)
        elif self.label == 'positions':
            results = self.format_positions(results)
        elif self.label == 'orders':
            results = self.format_orders(results)
        elif self.label == 'order_status':
            results = self.format_orders(results, self.id)
        elif self.label == 'tickets':
            results = self.format_tickets(results)
        elif self.label == 'executions':
            results = self.format_executions(results)
        elif self.label == 'order_executions':
            results = self.format_executions(results, oid=self.id)
        elif self.label == 'execution':
            results = self.format_executions(results, xid=self.id)
        elif self.label == 'barchart':
            results = self.api.format_barchart(results)
        elif self.label in ['new_symbol', 'order', 'ticket', 'unadvise', 'add_symbol', 'submit_order', 'request_accounts',
                            'get_order_route', 'set_account', 'create_staged_order_ticket', 'query_bars_failed', 'cancel_order',
                            'global_cancel']:
            results = json.dumps(results)
        elif self.label in ['init_symbol', 'tick', 'accounts', 'order-ack', 'ticket-ack']:
            # no local formatting for these labels
            pass
        else:
            raise ValueError(f"unexpected result type: {self.label}: {results}")

            results = json.dumps(results)

        self.api.debug(f'{self} returning {repr(results)[:DEBUG_TRUNCATE_RESULTS]}')
        return results

    def format_account_data(self, rows):
        data = rows[0] if rows else rows
        if data and 'EXCESS_EQ' in data:
            data['_cash'] = round(float(data['EXCESS_EQ']), 2)
        return json.dumps(data)

    def format_positions(self, rows):
        # Positions should return {'ACCOUNT': {'SYMBOL': QUANTITY, ...}, ...}
        positions = {}
        [positions.setdefault(a, {}) for a in self.api.accounts]
        #print('format_positions: rows=%s' % repr(rows))
        for pos in rows or []:
            if pos:
                #print('format_positions: pos=%s' % repr(pos))
                account = self.api.make_account(pos)
                symbol = pos['DISP_NAME']
                positions[account].setdefault(symbol, 0)
                # if LONG positions exist, add them, if SHORT positions exist, subtract them
                for m, f in [(1, 'LONGPOS'), (1, 'LONGPOS0'), (-1, 'SHORTPOS'), (-1, 'SHORTPOS0')]:
                    if f in pos:
                        positions[account][symbol] += m * int(pos[f])
        return json.dumps(positions)

    def format_orders(self, rows, oid=None):
        return self._format_orders(rows, oid, 'order')

    def format_tickets(self, rows, oid=None):
        return self._format_orders(rows, oid, 'ticket')

    def _format_orders(self, rows, oid, _filter):
        #pprint({'format_orders': rows})
        #print('_format_orders %s %s' % (oid, _filter))
        for row in rows or []:
            if row:
                self.api.handle_order_response(row)
        if oid:
            results = self.api.orders[oid].render() if oid in self.api.orders else None
        else:
            results = {}
            for k, v in self.api.orders.items():
                # return either tickets or orders based on _filter value
                if v.ticket == _filter:
                    results[k] = v.render()
        return json.dumps(results)

    def format_executions(self, rows, xid=None, oid=None):
        for row in rows or []:
            if row:
                self.api.handle_execution_response(row)
        if xid:
            results = self.api.executions[xid].render() if xid in self.api.executions else None
        elif oid:
            results = {k: v.render() for k, v in self.api.executions.items() if v.fields['ORIGINAL_ORDER_ID'] == oid}
        else:
            results = {k: v.render() for k, v in self.api.executions.items()}
        return json.dumps(results)


class RTX_Connection(object):

    def __init__(self, api, service, topic):
        self.api = api
        self.id = str(uuid1())
        self.service = service
        self.topic = topic
        self.log_events = api.log_cxn_events
        self.key = '%s;%s' % (service, topic)
        self.api.debug(f"{self}.__init__(...)")
        self.last_query = ''
        self.api.cxn_register(self)
        self.api.gateway_send('connect %s %s' % (self.id, self.key))
        self.ack_pending = 'CONNECTION PENDING'
        self.ack_callback = None
        self.response_pending = None
        self.response_callback = None
        self.response_rows = None
        self.status_pending = 'OnInitAck'
        self.status_callback = None
        self.update_callback = None
        self.update_handler = None
        self.connected = False
        self.on_connect_action = None
        self.update_ready()

    def __del__(self):
        self.api.debug(f"__del__({self})")

    def __repr__(self):
        return f"{__class__.__name__}<{hex(id(self))} {self.id} {self.key}>"

    def __str__(self):
        return repr(self)

    def update_ready(self):
        self.ready = not (
            self.ack_pending or self.response_pending or self.status_pending or self.status_callback or self.update_callback
            or self.update_handler
        )
        if self.ready:
            self.api.cxn_activate(self)

    def receive(self, _type, data):
        if _type == 'ack':
            self.handle_ack(data)
        elif _type == 'response':
            self.handle_response(data)
        elif _type == 'status':
            self.handle_status(data)
        elif _type == 'update':
            self.handle_update(data)
        else:
            self.api.error_handler(self.id, 'Message Type Unexpected: %s' % data)
        self.update_ready()

    def handle_ack(self, data):
        if self.log_events:
            self.api.info(f"{self} Ack Received: {data}")
        if self.ack_pending:
            if data == self.ack_pending:
                self.ack_pending = None
            else:
                self.api.error_handler(self.id, 'Ack Mismatch: expected %s, got %s' % (self.ack_pending, data))
                self.handle_response_failure()
            if self.ack_callback:
                self.ack_callback.complete(data)
                self.ack_callback = None
        else:
            self.api.error_handler(self.id, 'Ack Unexpected: %s' % data)

    def handle_response(self, data):
        if self.log_events:
            self.api.info('Connection Response: %s %s' % (self, data))
        if self.response_pending:
            self.response_rows.append(data['row'])
            if data['complete']:
                if self.response_callback:
                    self.response_callback.complete(self.response_rows)
                    self.response_callback = None
                self.response_pending = None
                self.response_rows = None
        else:
            self.api.error(f"{self} Response Unexpected: {data}")

    def handle_response_failure(self):
        self.api.error(f"{self} Connection Response_Failure")
        if self.response_callback:
            self.response_callback.complete(None)

    def handle_status(self, data):
        if self.log_events:
            self.api.info('Connection Status: %s %s' % (self, data))
        if self.status_pending and data['msg'] == self.status_pending:
            # if update_handler is set (an Advise is active) then leave status_pending, because we'll
            # get sporadic OnOtherAck status messages mixed in with the update messages
            # in all other cases, clear status_pending, since we only expect the one status message
            if not self.update_handler:
                self.status_pending = None

            if data['status'] == '1':
                # special case for the first status ack of a new connection; we may need to do on_connect_action
                if data['msg'] == 'OnInitAck':
                    self.connected = True
                    if self.on_connect_action:
                        self.ready = True
                        cmd, arg, exa, cba, cbr, exs, cbs, cbu, uhr = self.on_connect_action
                        self.api.debug(f"{self} sending on_connect_action: {self.on_connect_action}")
                        self.send(cmd, arg, exa, cba, cbr, exs, cbs, cbu, uhr)
                        self.on_connect_action = None
                        self.api.debug(f"{self} after on_connect_action send: self.status_pending={self.status_pending}")

                if self.status_callback:
                    self.status_callback.complete(data)
                    self.status_callback = None
            else:
                self.api.error_handler(self.id, 'Status Error: %s' % data)
        else:
            self.api.error_handler(self.id, 'Status Unexpected: %s' % data)
            # if ADVISE is active; call handler function with None to notify caller the advise has been terminated
            if self.update_handler and data['msg'] == 'OnTerminate':
                self.update_handler(self, None)
            self.handle_response_failure()

    def handle_update(self, data):
        if self.log_events:
            self.api.info(f"{self} Connection Update: {data}")
        if self.update_callback:
            self.update_callback.complete(data['row'])
            self.update_callback = None
        else:
            if self.update_handler:
                self.update_handler(self, data['row'])
            else:
                self.api.error_handler(self.id, 'Update Unexpected: %s' % repr(data))

    def query(
        self,
        cmd,
        table,
        what,
        where,
        expect_ack=None,
        ack_callback=None,
        response_callback=None,
        expect_status=None,
        status_callback=None,
        update_callback=None,
        update_handler=None
    ):
        tql = '%s;%s;%s' % (table, what, where)
        self.last_query = '%s: %s' % (cmd, tql)
        ret = self.send(
            cmd, tql, expect_ack, ack_callback, response_callback, expect_status, status_callback, update_callback,
            update_handler
        )

    def request(self, table, what, where, callback):
        return self.query('request', table, what, where, expect_ack='REQUEST_OK', response_callback=callback)

    def advise(self, table, what, where, handler):
        return self.query(
            'advise', table, what, where, expect_ack='ADVISE_OK', expect_status='OnOtherAck', update_handler=handler
        )

    def adviserequest(self, table, what, where, callback, handler):
        return self.query(
            'adviserequest',
            table,
            what,
            where,
            expect_ack='ADVISE_REQUEST_OK',
            response_callback=callback,
            expect_status='OnOtherAck',
            update_handler=handler
        )

    def unadvise(self, table, what, where, callback):
        # force ready state so the unadvise command will be sent
        self.ready = True
        return self.query(
            'unadvise', table, what, where, expect_ack='UNADVISE_OK', expect_status='OnOtherAck', status_callback=callback
        )

    def poke(self, table, what, where, data, ack_callback, callback):
        tql = '%s;%s;%s!%s' % (table, what, where, data)
        self.last_query = 'poke: %s' % tql
        return self.send(
            'poke', tql, expect_ack="POKE_OK", ack_callback=ack_callback, expect_status='OnOtherAck', status_callback=callback
        )

    def execute(self, command, callback):
        self.last_query = 'execute: %s' % command
        return self.send('execute', command, expect_ack="EXECUTE_OK", ack_callback=callback)

    def terminate(self, code, callback):
        self.last_query = 'terminate: %s' % str(code)
        return self.send('terminate', str(code), expect_ack="TERMINATE_OK", ack_callback=callback)

    def send(
        self,
        cmd,
        args,
        expect_ack=None,
        ack_callback=None,
        response_callback=None,
        expect_status=None,
        status_callback=None,
        update_callback=None,
        update_handler=None
    ):
        if self.ready:
            self.cmd = cmd
            if 'request' in cmd:
                self.response_rows = []
            msg = f"{cmd} {self.id} {args}"
            if self.log_events:
                self.api.info(f"{self} send: {msg}")
            ret = self.api.gateway_send(msg)
            self.ack_pending = expect_ack
            self.ack_callback = ack_callback
            self.response_pending = bool(response_callback)
            self.response_callback = response_callback
            self.status_pending = expect_status
            self.status_callback = status_callback
            self.update_callback = update_callback
            self.update_handler = update_handler
        else:
            if self.on_connect_action:
                self.api.error_handler(self.id, f"Failure: on_connect_action already exists: {self.on_connect_action}")
                ret = False
            else:
                if self.log_events:
                    self.api.info(f"{self} storing on_connect_action {cmd}")
                self.on_connect_action = (
                    cmd, args, expect_ack, ack_callback, response_callback, expect_status, status_callback, update_callback,
                    update_handler
                )
                ret = True
        return ret


class RTX_LocalCallback(object):

    def __init__(self, api, callback_handler, errback_handler=None):
        self.api = api
        self.callback_handler = callback_handler
        self.errback_handler = errback_handler
        cbname = self.callback_handler.__name__
        ebname = self.errback_handler.__name__ if self.errback_handler else 'None'
        self.api.debug(f"{self}.__init__(..., {cbname}, {ebname})")

    def __repr__(self):
        return f"{__class__.__name__}<{hex(id(self))}>"

    def __str__(self):
        return repr(self)

    def callback(self, data):
        if self.callback_handler:
            self.callback_handler(data)
        else:
            self.api.error_handler(repr(self), f"Failure: undefined callback_handler: data={data}")

    def errback(self, error):
        if self.errback_handler:
            self.errback_handler(error)
        else:
            self.api.error_handler(repr(self), f"Failure: undefined errback_handler: error={error}")


class RTX(object):

    def __init__(self):
        self.output(HEADER)
        self.output(REVISION)
        self.label = 'RTX Gateway'
        self.channel = 'rtx'
        self.id = 'RTX'
        self.connected = False
        self.initialized = False
        self.clients = set([])
        self.callback_timeout = {}
        self.init_config()
        self.now = None
        self.feed_now = None
        self.trade_minute = -1
        self.feedzone = pytz.timezone(self.config.get('API_TIMEZONE'))
        self.localzone = tzlocal.get_localzone()
        self.current_account = ''
        self.orders = {}
        self.pending_orders = {}
        self.tickets = {}
        self.pending_tickets = {}
        self.openorder_callbacks = []
        self.accounts = None
        self.account_data = {}
        self.pending_account_data_requests = set([])
        self.positions = {}
        self.position_callbacks = []
        self.executions = {}
        self.pending_mapper_lookups = {}
        self.execution_callbacks = []
        self.execution_status_callbacks = []
        self.order_callbacks = []
        self.bardata_callbacks = []
        self.cancel_callbacks = []
        self.order_status_callbacks = []
        self.ticket_callbacks = []
        self.add_symbol_callbacks = []
        self.accountdata_callbacks = []
        self.set_account_callbacks = []
        self.account_request_callbacks = []
        self.initial_account_request_pending = True
        self.initial_order_request_pending = True
        self.initial_execution_request_pending = True
        self.initial_update_mapper_pending = True
        self.timer_callbacks = []
        self.last_connection_status = ''
        self.connection_status = 'Startup'
        self.LastError = -1
        self.next_order_id = -1
        self.last_minute = -1
        self.symbols = {}
        self.barchart = None
        self.primary_exchange_map = {}
        self.gateway_sender = None
        self.gateway_protocol = None
        self.gateway_transport = None
        self.active_cxn = {}
        self.idle_cxn = {}
        self.cx_time = None
        self.seconds_disconnected = 0
        self.callback_metrics = {}
        self.set_order_route(self.config.get('API_ROUTE'), None)
        reactor.connectTCP(self.api_hostname, self.api_port, RtxClientFactory(self))
        self.repeater = LoopingCall(self.EverySecond)
        self.repeater.start(1)

    def __repr__(self):
        return f"{__class__.__name__}<{hex(id(self))}>"

    def init_config(self):
        self.config = Config(self.channel, output=self.output)
        self.host = self.config.get('HOST')
        self.api_hostname = self.config.get('API_HOST')
        self.api_port = int(self.config.get('API_PORT'))
        self.username = self.config.get('USERNAME')
        self.password = self.config.get('PASSWORD')
        self.http_port = int(self.config.get('HTTP_PORT'))
        self.tcp_port = int(self.config.get('TCP_PORT'))
        self.enable_ticker = bool(int(self.config.get('ENABLE_TICKER')))
        self.enable_high_low = bool(int(self.config.get('ENABLE_HIGH_LOW')))
        self.enable_barchart = bool(int(self.config.get('ENABLE_BARCHART')))
        self.enable_symbol_barchart = bool(int(self.config.get('ENABLE_SYMBOL_BARCHART')))
        self.enable_seconds_tick = bool(int(self.config.get('ENABLE_SECONDS_TICK')))
        self.enable_execution_account_format = bool(int(self.config.get('ENABLE_EXECUTION_ACCOUNT_FORMAT')))
        self.halt_on_exception = bool(int(self.config.get('ENABLE_EXCEPTION_HALT')))
        self.gateway_disconnect_timeout = int(self.config.get('GATEWAY_DISCONNECT_TIMEOUT'))
        self.enable_gateway_disconnect_shutdown = bool(int(self.config.get('GATEWAY_DISCONNECT_SHUTDOWN')))
        self.log_api_messages = bool(int(self.config.get('LOG_API_MESSAGES')))
        self.debug_api_messages = bool(int(self.config.get('DEBUG_API_MESSAGES')))
        self.log_cxn_events = bool(int(self.config.get('LOG_CXN_EVENTS')))
        self.log_client_messages = bool(int(self.config.get('LOG_CLIENT_MESSAGES')))
        self.log_http_requests = bool(int(self.config.get('LOG_HTTP_REQUESTS')))
        self.log_http_responses = bool(int(self.config.get('LOG_HTTP_RESPONSES')))
        self.log_response_truncate = int(self.config.get('LOG_RESPONSE_TRUNCATE'))
        self.log_order_updates = bool(int(self.config.get('LOG_ORDER_UPDATES')))
        self.log_order_update_dups = bool(int(self.config.get('LOG_ORDER_UPDATE_DUPS')))
        self.log_execution_updates = bool(int(self.config.get('LOG_EXECUTION_UPDATES')))
        self.log_callback_metrics = bool(int(self.config.get('LOG_CALLBACK_METRICS')))
        self.log_level = int(getLevelName(self.config.get('LOG_LEVEL')))
        self.time_offset = int(self.config.get('TIME_OFFSET'))
        self.enable_auto_reset = bool(int(self.config.get('ENABLE_AUTO_RESET')))
        self.local_reset_time = self.config.get('LOCAL_RESET_TIME')
        self.auto_reset_trigger = False
        self.time_offset = int(self.config.get('TIME_OFFSET'))
        # verify test mode in any of three ways
        if not ('test' in gethostname() or self.config.get('TESTING') or bool(int(os.environ.get('TESTING', 0)))):
            if self.time_offset:
                self.error_handler(self.id, 'TIME_OFFSET disallowed outside of test mode; resetting to 0')
                self.time_offset = 0
            if not self.enable_seconds_tick:
                self.error_handler(self.id, 'SECONDS_TICK disable disallowed outside of test mode; resetting to enabled')
                self.enable_seconds_tick = True
        for t in TIMEOUT_TYPES:
            self.callback_timeout[t] = int(self.config.get('TIMEOUT_%s' % t))

    def check_exception_halt(self, exc, caller):
        if self.halt_on_exception:
            self.force_disconnect(f'{repr(exc)} raised in {caller} with TXTRADER_ENABLE_EXCEPTION_HALT set')

    def flags(self):
        return {
            'TICKER': self.enable_ticker,
            'HIGH_LOW': self.enable_high_low,
            'BARCHART': self.enable_barchart,
            'SYMBOL_BARCHART': self.enable_symbol_barchart,
            'SECONDS_TICK': self.enable_seconds_tick,
            'TIME_OFFSET': self.time_offset,
        }

    def record_callback_metrics(self, label, elapsed, expired):
        m = self.callback_metrics.setdefault(label, {'tot': 0, 'min': 9999, 'max': 0, 'avg': 0, 'exp': 0, 'hst': []})
        total = m['tot']
        m['tot'] += 1
        m['min'] = min(m['min'], elapsed)
        m['max'] = max(m['max'], elapsed)
        m['avg'] = (m['avg'] * total + elapsed) / (total + 1)
        m['exp'] += int(expired)
        m['hst'].append(elapsed)
        if len(m['hst']) > CALLBACK_METRIC_HISTORY_LIMIT:
            del m['hst'][0]

    def cxn_register(self, cxn):
        if self.log_cxn_events:
            self.info('cxn_register: %s' % repr(cxn))
        self.active_cxn[cxn.id] = cxn

    def cxn_activate(self, cxn):
        if self.log_cxn_events:
            self.info('cxn_activate: %s' % repr(cxn))
        if not cxn.key in self.idle_cxn:
            self.idle_cxn[cxn.key] = []
        self.idle_cxn[cxn.key].append(cxn)

    def cxn_get(self, service, topic):
        key = '%s;%s' % (service, topic)
        if key in self.idle_cxn and len(self.idle_cxn[key]):
            cxn = self.idle_cxn[key].pop()
        else:
            cxn = RTX_Connection(self, service, topic)
        if self.log_cxn_events:
            self.info('cxn_get() returning: %s' % repr(cxn))
        return cxn

    def cxn_clear(self):
        if self.log_cxn_events:
            self.debug('{self} cxn_clear')
        self.idle_cxn.clear()
        for cxn in self.active_cxn.values():
            self.warning(f'clearing active {cxn} {cxn.last_query}')
        self.active_cxn.clear()
        for symbol in self.symbols.values():
            if symbol.cxn_init:
                self.warning(f"clearing {symbol.symbol} init {cxn}")
                symbol.cxn_init = None
            if symbol.cxn_updates:
                self.warning(f"clearing {symbol.symbol} updates {cxn}")
                symbol.cxn_updates = None

    def gateway_connect(self, protocol):
        if protocol:
            self.gateway_protocol = protocol
            self.gateway_sender = protocol.sendLine
            self.gateway_transport = protocol.transport
            self.update_connection_status('Pending')
            self.output('Awaiting startup response from RTX gateway at %s:%d...' % (self.api_hostname, self.api_port))
        else:
            self.gateway_sender = None
            self.gateway_protocol = None
            self.gateway_transport = None
            self.connected = False
            self.initialized = False
            self.seconds_disconnected = 0
            self.initial_account_request_pending = False
            self.initial_order_request_pending = False
            self.initial_execution_request_pending = False
            self.initial_update_mapper_pending = False
            self.accounts = None
            self.update_connection_status('Disconnected')
            self.error_handler(self.id, 'API Disconnected')
            self.cxn_clear()
        return self.gateway_receive

    def gateway_send(self, msg):
        if self.debug_api_messages:
            self.output('<--TX[%d]--' % (len(msg)))
            hexdump(msg.encode())
        if self.log_api_messages:
            self.info(f"<-- {msg}")
        if self.gateway_sender:
            self.gateway_sender(('%s\n' % str(msg)).encode())

    def dump_input_message(self, msg):
        self.output('--RX[%d]-->' % (len(msg)))
        hexdump(msg)

    def receive_exception(self, t, e, msg):
        traceback.print_exc()
        self.error_handler(self.id, 'Exception %s %s parsing data from RTGW' % (t, e))
        self.dump_input_message(msg)
        if self.halt_on_exception:
            reactor.callLater(0, reactor.stop)
        return None

    def gateway_receive(self, msg):
        """handle input from rtgw """

        if self.debug_api_messages:
            self.dump_input_message(msg)

        try:
            o = json.loads(msg)
        except Exception as e:
            return self.receive_exception(sys.exc_info()[0], e, msg)

        msg_type = o['type']
        msg_id = o['id']
        msg_data = o['data']

        if self.log_api_messages:
            self.output(f"--> {msg_type} {msg_id} {msg_data}")

        if msg_type == 'system':
            self.handle_system_message(msg_id, msg_data)
        else:
            if msg_id in self.active_cxn:
                c = self.active_cxn[msg_id].receive(msg_type, msg_data)
            else:
                self.error_handler(self.id, f"Message Received on Unknown connection: {repr(msg)}")

        return True

    def handle_system_message(self, id, data):
        if data['msg'] == 'startup':
            self.connected = True
            self.initialized = False
            self.accounts = None
            self.output(f"Received RTX Gateway startup response: {data['item']}")
            self.update_connection_status('Initializing')
            self.setup_local_queries()
        else:
            self.error_handler(self.id, 'Unknown system message: %s' % repr(data))

    def setup_local_queries(self):
        """Upon connection to rtgw, start automatic queries"""
        #what='BANK,BRANCH,CUSTOMER,DEPOSIT'
        self.output("Sending initial Accounts query...")
        what = '*'
        self.rtx_request(
            'ACCOUNT_GATEWAY', 'ORDER', 'ACCOUNT', what, '', 'accounts', self.handle_accounts, self.accountdata_callbacks,
            self.callback_timeout['ACCOUNT'], self.handle_initial_account_failure
        )

        self.output("Sending initial Orders query...")
        self.cxn_get('ACCOUNT_GATEWAY', 'ORDER').advise('ORDERS', '*', '', self.handle_order_update)

        self.rtx_request(
            'ACCOUNT_GATEWAY', 'ORDER', 'ORDERS', '*', '', 'orders', self.handle_initial_orders_response,
            self.openorder_callbacks, self.callback_timeout['ORDERSTATUS'], self.handle_initial_orders_failure
        )

        self.output("Sending initial Executions query...")
        execution_where = "TYPE='ExchangeTradeOrder'"
        self.cxn_get('ACCOUNT_GATEWAY', 'ORDER').advise('ORDERS', '*', execution_where, self.handle_execution_update)
        self.rtx_request(
            'ACCOUNT_GATEWAY', 'ORDER', 'ORDERS', '*', execution_where, 'executions', self.handle_initial_executions_response,
            self.execution_callbacks, self.callback_timeout['ORDERSTATUS'], self.handle_initial_executions_failure
        )

        # on a reconnect, there may be symbols that need an advise
        for symbol in self.symbols.values():
            symbol.api_initial_request()

        self.initial_account_request_pending = True
        self.initial_order_request_pending = True
        self.initial_execution_request_pending = True
        self.initial_update_mapper_pending = True
        self.initialized = False

    def handle_initial_account_failure(self, message):
        self.force_disconnect(f"Initial Account query failed: {repr(message)}")

    def handle_initial_orders_response(self, rows):
        self.output(f"Initial Orders refresh complete. ({len(self.orders)} orders)")
        self.initial_order_request_pending = False

    def handle_initial_orders_failure(self, message):
        self.force_disconnect('Initial Order query failed (%s)' % repr(message))

    def handle_initial_executions_response(self, rows):
        self.output(f"Initial Executions refresh complete. ({len(self.executions)} executions)")
        self.initial_execution_request_pending = False

    def handle_initial_executions_failure(self, message):
        self.force_disconnect('Initial Execution query failed (%s)' % repr(message))

    def debug(self, msg):
        if self.log_level <= DEBUG:
            log.msg(f"DEBUG: {msg}", logLevel=DEBUG)

    def info(self, msg):
        if self.log_level <= INFO:
            log.msg(msg, logLevel=INFO)

    def warning(self, msg):
        if self.log_level <= WARNING:
            log.msg(f"WARNING: {msg}", logLevel=WARNING)

    def error(self, msg):
        if self.log_level <= ERROR:
            log.msg(f"ERROR: {msg}", logLevel=ERROR)

    def critical(self, msg):
        if self.log_level <= CRITICAL:
            log.msg(f"CRITICAL: {msg}", logLevel=CRITICAL)

    def output(self, msg):
        if 'error' in msg.lower() or 'alert' in msg.lower():
            level = ERROR
        else:
            level = INFO
        log.msg(msg, logLevel=level)

    def open_client(self, client):
        self.clients.add(client)

    def close_client(self, client):
        self.clients.discard(client)
        symbols = list(self.symbols.values())
        for symbol in symbols:
            symbol.del_client(client)

    def set_primary_exchange(self, symbol, exchange):
        if exchange:
            self.primary_exchange_map[symbol] = exchange
        else:
            del (self.primary_exchange_map[symbol])
        return self.primary_exchange_map

    def CheckPendingResults(self):
        # check each callback list for timeouts
        for cblist in [self.timer_callbacks, self.position_callbacks, self.ticket_callbacks, self.openorder_callbacks,
                       self.execution_callbacks, self.execution_status_callbacks, self.bardata_callbacks, self.order_callbacks,
                       self.cancel_callbacks, self.add_symbol_callbacks, self.accountdata_callbacks, self.set_account_callbacks,
                       self.account_request_callbacks, self.order_status_callbacks]:
            dlist = []
            for cb in cblist:
                cb.check_expire()
                if cb.done:
                    dlist.append(cb)
            # delete any callbacks that are done
            for cb in dlist:
                cblist.remove(cb)

    def handle_order_update(self, cxn, msg):
        if msg:
            self.handle_order_response(msg)
        else:
            self.force_disconnect('API Order Status ADVISE connection has been terminated; connection has failed')

    def handle_order_response(self, msg):
        #print('---handle_order_response: %s' % repr(msg))
        oid = msg.get('ORIGINAL_ORDER_ID')
        if oid:
            if self.pending_orders and 'CLIENT_ORDER_ID' in msg:
                # this is a newly created order, it has a CLIENT_ORDER_ID
                coid = msg['CLIENT_ORDER_ID']
                if coid in self.pending_orders:
                    self.pending_orders[coid].initial_update(msg)
                    self.orders[oid] = self.pending_orders[coid]
                    del self.pending_orders[coid]
            elif self.pending_orders and (oid in self.pending_orders):
                # this is a change order, ORIGINAL_ORDER_ID will be a key in pending_orders
                self.pending_orders[oid].initial_update(msg)
                del self.pending_orders[oid]
            elif oid in self.orders:
                # this is an existing order, so update it
                self.orders[oid].update(msg)
            else:
                # we've never seen this order, so add it to the collection and update it
                o = API_Order(self, oid, msg, 'realtick')
                self.orders[oid] = o
                o.update(msg)
        else:
            self.error_handler(self.id, 'handle_order_response: ORIGINAL_ORDER_ID not found in %s' % repr(msg))

    def handle_ticket_update(self, cxn, msg):
        return self.handle_ticket_response(msg)

    def handle_ticket_response(self, msg):
        tid = msg['CLIENT_ORDER_ID'] if 'CLIENT_ORDER_ID' in msg else None
        if self.pending_tickets and tid in self.pending_tickets:
            self.pending_tickets[tid].initial_update(msg)
            self.tickets[tid] = self.pending_tickets[tid]
            del self.pending_tickets[tid]

    def handle_execution_update(self, cxn, msg):
        if msg:
            self.handle_execution_response(msg)
        else:
            self.force_disconnect('API Execution Status ADVISE connection has been terminated; connection has failed')

    def handle_execution_response(self, msg):
        oid = msg.get('ORDER_ID')
        if oid:
            if oid in self.executions:
                # this is an existing execution
                e = self.executions[oid]
            else:
                # we've never seen this execution, so add it to the collection
                e = API_Execution(self, oid)
                self.executions[oid] = e
            e.update(msg)
        else:
            self.error_handler(self.id, f"handle_execution_response: ORDER_ID not found in {repr(msg)}")

    def get_cusip(self, symbol):
        ret = ''
        symbol = self.symbols.get(symbol)
        if symbol:
            ret = symbol.cusip
        return ret

    def send_order_update(self, fields, mapped=False):
        """send a rendered order out to clients"""
        self.debug(f"{self} send_order_update({fields})")
        symbol = fields['symbol']
        if not fields.get('cusip'):
            if mapped:
                self.debug(f"{self} order update is still missing CUSIP after mapping, continuing...")
            else:
                self.debug(f"{self} order update is missing CUSIP, deferring until mapped...")
                mapper = self.pending_mapper_lookups.get(symbol)
                if not mapper:
                    mapper = API_Update_Mapper(self, symbol)
                mapper.add_update(API_Order_Update(self, symbol, deepcopy(fields), self.send_order_update))
                return
        _class = fields['class']
        oid = fields['permid']
        account = fields['account']
        _type = fields['raw']['TYPE']
        status = fields['status']
        self.WriteAllClients(f"{_class}.{oid} {account} {_type} {status}", option_flag=f"{_class}-notification")
        self.WriteAllClients(f"{_class}-data {json.dumps(fields)}", option_flag=f"{_class}-data")

    def send_execution_update(self, fields, mapped=False):
        """send a rendered execution out to clients"""
        self.debug(f"{self} send_execution_update({fields})")
        symbol = fields['DISP_NAME']
        if not fields.get('CUSIP'):
            if mapped:
                self.debug(f"{self} execution update is still missing CUSIP after mapping, continuing...")
            else:
                self.debug(f"{self} execution update is missing CUSIP, deferring until mapped...")
                mapper = self.pending_mapper_lookups.get(symbol)
                if not mapper:
                    mapper = API_Update_Mapper(self, symbol)
                mapper.add_update(API_Execution_Update(self, symbol, deepcopy(fields), self.send_execution_update))
                return
        self.debug(f"{self} execution update validated, sending to clients")
        xid = fields['ORDER_ID']
        oid = fields['ORIGINAL_ORDER_ID']
        account = fields['ACCOUNT']
        status = fields['CURRENT_STATUS']
        cusip = fields.get('CUSIP', '')
        volume = fields['VOLUME']
        price = fields['PRICE']
        transaction = fields['BUYORSELL']
        remaining = fields['ORDER_RESIDUAL']

        if self.log_execution_updates:
            self.output(f"FILL: {xid} {cusip} {symbol} {transaction} {volume} {price} {remaining}")

        self.WriteAllClients(f"execution.{xid} {account} {oid} {status}", option_flag='execution-notification')
        self.WriteAllClients(f"execution-data {json.dumps(fields)}", option_flag='execution-data')

    def make_account(self, row):
        return '%s.%s.%s.%s' % (row['BANK'], row['BRANCH'], row['CUSTOMER'], row['DEPOSIT'])

    def handle_accounts(self, rows):
        if isinstance(rows, list) and rows:
            self.accounts = list(set([self.make_account(row) for row in rows]))
            self.accounts.sort()
            self.initial_account_request_pending = False
            self.output(f"Initial Accounts refresh complete. ({len(self.accounts)} accounts)")
            self.WriteAllClients('accounts: %s' % json.dumps(self.accounts))
            for cb in self.account_request_callbacks:
                self.info(f'handle_accounts response={self.accounts}')
                cb.complete(self.accounts)

            for cb in self.set_account_callbacks:
                self.info('set_account: processing deferred response.')
                self.process_set_account(cb.id, cb)
        else:
            self.handle_initial_account_failure('Initial Account query returned no data.')

    def set_account(self, account_name, callback):
        cb = API_Callback(self, account_name, 'set_account', callback)
        if self.accounts:
            self.process_set_account(account_name, cb)
        elif self.initial_account_request_pending:
            self.set_account_callbacks.append(cb)
        else:
            self.error_handler(self.id, 'set_account; no data, but no initial_account_request_pending')
            cb.complete(None)

    def verify_account(self, account_name):
        if account_name in self.accounts:
            ret = True
        else:
            msg = 'account %s not found' % account_name
            self.error_handler(self.id, 'set_account(): %s' % msg)
            ret = False
        return ret

    def process_set_account(self, account_name, callback):
        ret = self.verify_account(account_name)
        if ret:
            self.current_account = account_name
            self.WriteAllClients('current-account: %s' % self.current_account)

        if callback:
            callback.complete(ret)
        else:
            return ret

    def rtx_request(self, service, topic, table, what, where, label, handler, cb_list, timeout, error_handler=None):
        cxn = self.cxn_get(service, topic)
        cb = API_Callback(self, cxn.id, label, RTX_LocalCallback(self, handler, error_handler), timeout)
        cxn.request(table, what, where, cb)
        cb_list.append(cb)

    def is_startup_complete(self):
        startup_complete = False
        if self.initial_account_request_pending:
            self.output('awaiting initial account response...')
        elif self.initial_order_request_pending:
            self.output('awaiting initial order response...')
        elif self.initial_execution_request_pending:
            self.output('awaiting initial execution response...')
        elif self.initial_update_mapper_pending:
            if len(self.pending_mapper_lookups):
                self.output('awaiting initial update mapper lookups...')
            else:
                self.initial_pending_mapper_lookups = False
                self.output(f"Initial update mapping complete.")
                startup_complete = True
        else:
            startup_complete = True
        return startup_complete

    def EverySecond(self):
        if self.connected:
            if not self.initialized:
                if self.is_startup_complete():
                    self.initialized = True
                    self.output('Initialization complete.')
                    self.update_connection_status('Up')

            if self.enable_seconds_tick:
                self.rtx_request(
                    'TA_SRV', 'LIVEQUOTE', 'LIVEQUOTE', 'DISP_NAME,TRDTIM_1,TRD_DATE', "DISP_NAME='$TIME'", 'tick',
                    self.handle_time, self.timer_callbacks, self.callback_timeout['TIMER'], self.handle_time_error
                )
        else:
            self.seconds_disconnected += 1
            if self.seconds_disconnected > self.gateway_disconnect_timeout:
                if self.enable_gateway_disconnect_shutdown:
                    self.force_disconnect('Realtick Gateway connection timed out after %d seconds' % self.seconds_disconnected)
        self.CheckPendingResults()

        if self.enable_auto_reset:
            self.check_auto_reset()

        if not int(time.time()) % 60:
            self.EveryMinute()

    def EveryMinute(self):
        if self.callback_metrics and self.log_callback_metrics:
            self.output('callback_metrics: %s' % json.dumps(self.callback_metrics))

    def check_auto_reset(self):
        if time.strftime('%H:%M') == self.local_reset_time:
            if not self.auto_reset_trigger:
                self.auto_reset_trigger = True
                self.warning(
                    f"auto_shutdown in 1 minute: TXTRADER_ENABLE_AUTO_RESET={self.enable_auto_reset} TXTRADER_LOCAL_RESET_TIME={self.local_reset_time}"
                )
        else:
            if self.auto_reset_trigger:
                self.force_disconnect('auto reset')

    def WriteAllClients(self, msg, option_flag=None):
        # if a client list is given, only write to that list, otherwise default to all clients
        if self.log_client_messages:
            self.info(f"WriteAllClients: {self.channel}.{msg} option_flag={option_flag}")
        msg = str('%s.%s' % (self.channel, msg))
        self.debug(f"WriteAllClients clients=[{','.join([repr(c) for c in self.clients])}]")
        if option_flag:
            # only write to clients with flag set in their options
            client_set = set([c for c in self.clients if (isinstance(c, tcpserver) and c.options.get(option_flag))])
        else:
            # no flag, so write to all tcpserver clients
            client_set = set([c for c in self.clients if isinstance(c, tcpserver)])

        self.debug(f"WriteAllClients: selected=[{','.join([repr(c) for c in client_set])}]")
        for c in client_set:
            c.sendString(msg.encode())

    def error_handler(self, id, msg):
        """report error messages"""
        self.output('ALERT: %s %s' % (id, msg))
        self.WriteAllClients('error: %s %s' % (id, msg))

    def force_disconnect(self, reason):
        self.update_connection_status('Shutdown')
        self.error_handler(self.id, f"Forcing shutdown: {reason}")
        if self.gateway_transport:
            self.gateway_transport.loseConnection()
        for client in self.clients:
            client.transport.loseConnection()
        reactor.callLater(0, reactor.stop)

    def parse_tql_float(self, data, pid, label):
        ret = self.parse_tql_field(data, pid, label)
        return round(float(ret), 2) if ret else 0.0

    def parse_tql_int(self, data, pid, label):
        ret = self.parse_tql_field(data, pid, label)
        return int(ret) if ret else 0

    def parse_tql_str(self, data, pid, label):
        ret = self.parse_tql_field(data, pid, label)
        return str(ret) if ret else ''

    def parse_tql_time(self, data, pid, label):
        """Parse TQL ascii time field returning datetime.time"""
        field = self.parse_tql_field(data, pid, label)
        if field:
            hour, minute, second = [int(i) for i in field.split(':')[0:3]]
            field = datetime.time(hour, minute, second)
        return field

    def parse_tql_date(self, data, pid, label):
        field = self.parse_tql_field(data, pid, label)
        if field:
            year, month, day = [int(i) for i in field.split('-')[0:3]]
            field = datetime.date(year, month, day)
        return field

    def parse_tql_field(self, data, pid, label):
        if str(data).lower().startswith('error '):
            if data.lower() == 'error 0':
                code = 'Field Not Found'
            elif data.lower() == 'error 2':
                code = 'Field No Value'
            elif data.lower() == 'error 3':
                code = 'Field Not Permissioned'
            elif data.lower() == 'error 17':
                code = 'No Record Exists'
            elif data.lower() == 'error 256':
                code = 'Field Reset'
            else:
                code = 'Unknown Field Error'
            self.warning(f'{self} Field Parse Failure: {label} {data}={code}')
            ret = None
        else:
            ret = data
        return ret

    def handle_time(self, rows):
        if rows:
            time_field = rows[0]['TRDTIM_1']
            date_field = rows[0]['TRD_DATE']
            if time_field == 'Error 17':
                # this indicates the $TIME symbol is not found on the server, which is a kludge to determine the login has failed
                self.force_disconnect('Gateway reports $TIME symbol unknown; connection has failed')
            elif str(time_field).lower().startswith('error'):
                self.error_handler(self.id, 'handle_time: time field %s' % time_field)
            else:
                year, month, day = [int(i) for i in date_field.split('-')[0:3]]
                hour, minute, second = [int(i) for i in time_field.split(':')[0:3]]
                self.feed_now = datetime.datetime(year, month, day, hour, minute,
                                                  second) + datetime.timedelta(seconds=self.time_offset)
                self.now = self.localize_time(self.feed_now)
                # don't add time offset
                if minute != self.last_minute:
                    self.last_minute = minute
                    self.WriteAllClients('time: %s %s:00' % (self.now.strftime('%Y-%m-%d'), self.now.strftime('%H:%M')))
        else:
            self.error_handler(self.id, 'handle_time: unexpected null input')

    def localize_time(self, apitime):
        """return API time corrected for local timezone"""
        return self.feedzone.localize(apitime).astimezone(self.localzone)

    def unlocalize_time(self, apitime):
        """reverse localize_time to convert local timezone to API time"""
        return self.localzone.localize(apitime).astimezone(self.feedzone)

    def handle_time_error(self, error):
        #time timeout error is reported as an expired callback
        self.error(f"time_error: {error}")

    def market_order(self, account, route, symbol, quantity, callback):
        return self.submit_order(account, route, 'market', 0, 0, symbol, int(quantity), callback)

    def limit_order(self, account, route, symbol, limit_price, quantity, callback):
        return self.submit_order(account, route, 'limit', float(limit_price), 0, symbol, int(quantity), callback)

    def stop_order(self, account, route, symbol, stop_price, quantity, callback):
        return self.submit_order(account, route, 'stop', 0, float(stop_price), symbol, int(quantity), callback)

    def stoplimit_order(self, account, route, symbol, stop_price, limit_price, quantity, callback):
        return self.submit_order(
            account, route, 'stoplimit', float(limit_price), float(stop_price), symbol, int(quantity), callback
        )

    def stage_market_order(self, tag, account, route, symbol, quantity, callback):
        return self.submit_order(account, route, 'market', 0, 0, symbol, int(quantity), callback, staged=tag)

    def create_order_id(self):
        return str(uuid1())

    def create_staged_order_ticket(self, account, callback):

        if not self.verify_account(account):
            API_Callback(self, 0, 'create_staged_order_ticket',
                         callback).complete({
                             'status': 'Error',
                             'errorMsg': 'account unknown'
                         })
            return

        o = OrderedDict({})
        self.verify_account(account)
        bank, branch, customer, deposit = account.split('.')[:4]
        o['BANK'] = bank
        o['BRANCH'] = branch
        o['CUSTOMER'] = customer
        o['DEPOSIT'] = deposit
        tid = 'T-%s' % self.create_order_id()
        o['CLIENT_ORDER_ID'] = tid
        o['DISP_NAME'] = 'N/A'
        o['STYP'] = RTX_STYPE  # stock
        o['EXIT_VEHICLE'] = 'NONE'
        o['TYPE'] = 'UserSubmitStagedOrder'

        # create callback to return to client after initial order update
        cb = API_Callback(self, tid, 'ticket', callback, self.callback_timeout['ORDER'])
        self.ticket_callbacks.append(cb)
        self.pending_tickets[tid] = API_Order(self, tid, o, 'client', cb)
        fields = ','.join(['%s=%s' % (i, v) for i, v in o.items()])

        acb = API_Callback(
            self, tid, 'ticket-ack', RTX_LocalCallback(self, self.ticket_submit_ack_callback), self.callback_timeout['ORDER']
        )
        cb = API_Callback(
            self, tid, 'ticket', RTX_LocalCallback(self, self.ticket_submit_callback), self.callback_timeout['ORDER']
        )
        self.cxn_get('ACCOUNT_GATEWAY', 'ORDER').poke('ORDERS', '*', '', fields, acb, cb)
        # TODO: add cb and acb to callback lists so they can be tested for timeout

    def ticket_submit_ack_callback(self, data):
        """called when staged order ticket request has been submitted with 'poke' and Ack has returned"""
        self.output('staged order ticket submission acknowledged: %s' % repr(data))

    def ticket_submit_callback(self, data):
        """called when staged order ticket request has been submitted with 'poke' and OnOtherAck has returned"""
        self.output('staged order ticket submitted: %s' % repr(data))

    def submit_order(self, account, route, order_type, price, stop_price, symbol, quantity, callback, staged=None, oid=None):
        if not self.initialized:
            API_Callback(self, 0, 'submit_order', callback).complete({'status': 'Error', 'errorMsg': 'gateway not initialized'})
            return

        if not self.verify_account(account):
            API_Callback(self, 0, 'submit_order', callback).complete({'status': 'Error', 'errorMsg': 'account unknown'})
            return

        #bank, branch, customer, deposit = self.current_account.split('.')[:4]
        self.set_order_route(route, None)
        if type(self.order_route) != dict:
            error = {'status': 'Error', 'errorMsg': f"undefined order route: {self.order_route}"}
            API_Callback(self, 0, 'submit_order', callback).complete(error)
            return

        o = OrderedDict({})
        bank, branch, customer, deposit = account.split('.')[:4]
        o['BANK'] = bank
        o['BRANCH'] = branch
        o['CUSTOMER'] = customer
        o['DEPOSIT'] = deposit

        o['BUYORSELL'] = 'Buy' if quantity > 0 else 'Sell'  # Buy Sell SellShort
        o['quantity'] = quantity
        o['GOOD_UNTIL'] = 'DAY'  # DAY or YYMMDDHHMMSS
        route = list(self.order_route.keys())[0]
        o['EXIT_VEHICLE'] = route

        # if order_route has a value, it is a dict of order route parameters
        if self.order_route[route]:
            for k, v in self.order_route[route].items():
                # encode strategy parameters in 0x01 delimited format
                if k in ['STRAT_PARAMETERS', 'STRAT_REDUNDANT_DATA']:
                    v = ''.join(['%s\x1F%s\x01' % i for i in v.items()])
                o[k] = v

        o['DISP_NAME'] = symbol
        o['STYP'] = RTX_STYPE  # stock

        if symbol in self.primary_exchange_map:
            exchange = self.primary_exchange_map[symbol]
        else:
            exchange = RTX_EXCHANGE
        o['EXCHANGE'] = exchange

        if order_type == 'market':
            o['PRICE_TYPE'] = 'Market'
        elif order_type == 'limit':
            o['PRICE_TYPE'] = 'AsEntered'
            o['PRICE'] = price
        elif order_type == 'stop':
            o['PRICE_TYPE'] = 'Stop'
            o['STOP_PRICE'] = stop_price
        elif type == 'stoplimit':
            o['PRICE_TYPE'] = 'StopLimit'
            o['STOP_PRICE'] = stop_price
            o['PRICE'] = price
        else:
            msg = 'unknown order type: %s' % order_type
            self.error_handler(self.id, msg)
            raise Exception(msg)

        o['VOLUME_TYPE'] = 'AsEntered'
        o['VOLUME'] = abs(quantity)

        if staged:
            o['ORDER_TAG'] = staged
            staging = 'Staged'
        else:
            staging = ''

        if oid:
            o['REFERS_TO_ID'] = oid
            submission = 'Change'
        else:
            oid = self.create_order_id()
            o['CLIENT_ORDER_ID'] = oid
            submission = 'Order'

        o['TYPE'] = 'UserSubmit%s%s' % (staging, submission)

        # create callback to return to client after initial order update
        cb = API_Callback(self, oid, 'order', callback, self.callback_timeout['ORDER'])
        self.order_callbacks.append(cb)
        if oid in self.orders:
            self.pending_orders[oid] = self.orders[oid]
            self.orders[oid].callback = cb
        else:
            self.pending_orders[oid] = API_Order(self, oid, o, 'client', cb)

        fields = ','.join(['%s=%s' % (i, v) for i, v in o.items() if i[0].isupper()])

        acb = API_Callback(
            self, oid, 'order-ack', RTX_LocalCallback(self, self.order_submit_ack_callback), self.callback_timeout['ORDER']
        )
        cb = API_Callback(
            self, oid, 'order', RTX_LocalCallback(self, self.order_submit_callback), self.callback_timeout['ORDER']
        )
        self.cxn_get('ACCOUNT_GATEWAY', 'ORDER').poke('ORDERS', '*', '', fields, acb, cb)

    def order_submit_ack_callback(self, data):
        """called when order has been submitted with 'poke' and Ack has returned"""
        self.output('order submission acknowleded: %s' % repr(data))

    def order_submit_callback(self, data):
        """called when order has been submitted with 'poke' and OnOtherAck has returned"""
        self.output('order submitted: %s' % repr(data))

    def cancel_order(self, oid, callback):
        self.output('cancel_order %s' % oid)

        if not self.initialized:
            API_Callback(self, 0, 'cancel_order', callback).complete({'status': 'Error', 'errorMsg': 'gateway not initialized'})
            return

        cb = API_Callback(self, oid, 'cancel_order', callback, self.callback_timeout['ORDER'])
        order = self.orders[oid] if oid in self.orders else None
        if order:
            if order.fields['status'] == 'Canceled':
                cb.complete({'status': 'Error', 'errorMsg': 'Already canceled.', 'id': oid})
            else:
                msg = OrderedDict({})
                #for fid in ['DISP_NAME', 'STYP', 'ORDER_TAG', 'EXIT_VEHICLE']:
                #    if fid in order.fields:
                #        msg[fid] = order.fields[fid]
                msg['TYPE'] = 'UserSubmitCancel'
                msg['REFERS_TO_ID'] = oid
                fields = ','.join(['%s=%s' % (i, v) for i, v in msg.items()])
                self.cxn_get('ACCOUNT_GATEWAY', 'ORDER').poke('ORDERS', '*', '', fields, None, cb)
                self.cancel_callbacks.append(cb)
        else:
            cb.complete({'status': 'Error', 'errorMsg': 'Order not found', 'id': oid})

    def symbol_enable(self, symbol, client, callback, timeout_type='ADDSYMBOL'):
        self.info('symbol_enable(%s,%s,%s)' % (symbol, client, callback))
        if not symbol in self.symbols:
            cb = API_Callback(self, symbol, 'new_symbol', callback, self.callback_timeout[timeout_type])
            self.add_symbol_callbacks.append(cb)
            API_Symbol(self, symbol, client, cb)
        else:
            self.symbols[symbol].add_client(client)
            # todo: get field list from client and pass to export
            API_Callback(self, symbol, 'add_symbol', callback).complete(self.symbols[symbol].export())
        self.debug(f'{self} symbols={self.symbols}')

    def symbol_init(self, symbol):
        ret = symbol.is_valid()
        if ret:
            # return the symbol data to the requesting client
            ret = symbol.export()
        else:
            # delete invalid symbol from api dict and return None
            self.symbols.pop(symbol.symbol)
        if symbol.callback:
            symbol.callback.complete(ret)
        return ret

    def symbol_disable(self, symbol, client):
        self.info(f"symbol_disable({symbol}, {client})")
        self.debug(f"self.symbols={self.symbols}")
        if symbol in self.symbols:
            self.symbols[symbol].del_client(client)
            self.debug(f"returning True: self.symbols={self.symbols}")
            return True
        else:
            self.debug(f"returning False: self.symbols={self.symbols}")
            return False

    # TODO: change function names to clarify that updating the status to 'Up' doesn't do that until the conditions are met
    def update_connection_status(self, status):
        self.connection_status = status
        if status != self.last_connection_status:
            self.last_connection_status = status
            self.output(f"connection-status-changed: {status}")
            self.WriteAllClients(f"connection-status-changed: {status}")

    def request_accounts(self, callback):
        cb = API_Callback(self, 0, 'request_accounts', callback, self.callback_timeout['ACCOUNT'])
        if self.accounts:
            cb.complete(self.accounts)
        elif self.initial_account_request_pending:
            self.account_request_callbacks.append(cb)
        else:
            self.error(f"{self} request_accounts; no data, but no account_request_pending")
            cb.complete(None)

    def request_positions(self, callback):
        cxn = self.cxn_get('ACCOUNT_GATEWAY', 'ORDER')
        cb = API_Callback(self, 0, 'positions', callback, self.callback_timeout['POSITION'])
        cxn.request('POSITION', '*', '', cb)
        self.position_callbacks.append(cb)

    def request_tickets(self, callback):
        self._request_orders(callback, 'tickets')

    def request_orders(self, callback):
        self._request_orders(callback, 'orders')

    def _request_orders(self, callback, label):
        cxn = self.cxn_get('ACCOUNT_GATEWAY', 'ORDER')
        cb = API_Callback(self, 0, label, callback, self.callback_timeout['ORDERSTATUS'])
        cxn.request('ORDERS', '*', '', cb)
        self.openorder_callbacks.append(cb)

    def request_order(self, oid, callback):
        cb = API_Callback(self, oid, 'order_status', callback, self.callback_timeout['ORDERSTATUS'])
        self.cxn_get('ACCOUNT_GATEWAY', 'ORDER').request('ORDERS', '*', "ORIGINAL_ORDER_ID='%s'" % oid, cb)
        self.order_status_callbacks.append(cb)

    def request_executions(self, callback):
        cb = API_Callback(self, 0, 'executions', callback, self.callback_timeout['ORDERSTATUS'])
        self.cxn_get('ACCOUNT_GATEWAY', 'ORDER').request('ORDERS', '*', "TYPE='ExchangeTradeOrder'", cb)
        self.execution_callbacks.append(cb)

    def request_order_executions(self, oid, callback):
        cb = API_Callback(self, oid, 'order_executions', callback, self.callback_timeout['ORDERSTATUS'])
        self.cxn_get('ACCOUNT_GATEWAY',
                     'ORDER').request('ORDERS', '*', f"TYPE='ExchangeTradeOrder',ORIGINAL_ORDER_ID='{oid}'", cb)
        self.execution_callbacks.append(cb)

    def request_execution(self, xid, callback):
        cb = API_Callback(self, xid, 'execution', callback, self.callback_timeout['ORDERSTATUS'])
        self.cxn_get('ACCOUNT_GATEWAY', 'ORDER').request('ORDERS', '*', f"TYPE='ExchangeTradeOrder',ORDER_ID='{xid}'", cb)
        self.execution_status_callbacks.append(cb)

    def request_account_data(self, account, fields, callback):
        cxn = self.cxn_get('ACCOUNT_GATEWAY', 'ORDER')
        cb = API_Callback(self, 0, 'account_data', callback, self.callback_timeout['ACCOUNT'])
        try:
            bank, branch, customer, deposit = account.split('.')[:4]
        except ValueError as ex:
            # the parse failed, so pass invalid account values so the system will return a null
            bank, branch, customer, deposit = ['.', '.', '.', '.']
        tql_where = "BANK='%s',BRANCH='%s',CUSTOMER='%s',DEPOSIT='%s'" % (bank, branch, customer, deposit)
        if fields:
            fields = ','.join(fields)
        else:
            fields = '*'
        cxn.request('DEPOSIT', fields, tql_where, cb)
        self.accountdata_callbacks.append(cb)

    def request_global_cancel(self):
        self.rtx_request(
            'ACCOUNT_GATEWAY', 'ORDER', 'ORDERS', 'ORDER_ID,ORIGINAL_ORDER_ID,CURRENT_STATUS,TYPE',
            "CURRENT_STATUS={'LIVE','PENDING'}", 'global_cancel', self.handle_global_cancel, self.openorder_callbacks,
            self.callback_timeout['ORDER']
        )

    def handle_global_cancel(self, rows):
        rows = json.loads(rows)
        for row in rows:
            if row['CURRENT_STATUS'] in ['LIVE', 'PENDING']:
                self.cancel_order(row['ORIGINAL_ORDER_ID'], RTX_LocalCallback(self, self.global_cancel_callback))

    def global_cancel_callback(self, data):
        data = json.loads(data)
        self.output('global cancel: %s' % repr(data))

    def _fail_query_bars(self, msg, callback):
        self.error_handler(self.id, msg)
        API_Callback(self, 0, 'query_bars_failed', callback).complete(None)
        return None

    def query_bars(self, symbol, interval, bar_start, bar_end, callback):

        if not self.enable_barchart:
            return self._fail_query_bars('ALERT: query_bars unimplemented', callback)

        if not symbol in self.symbols:
            return self._fail_query_bars('query_bars failed: symbol %s not active' % symbol, callback)

        # intraday n-minute bars; given stop date, number of days, minutes_per_bar
        if str(interval).startswith('D'):
            table = 'DAILY'
            interval = 0
        elif str(interval).startswith('W'):
            table = 'DAILY'
            interval = 1
        elif str(interval).startswith('M'):
            table = 'DAILY'
            interval = 2
        else:
            table = 'INTRADAY'
            interval = int(interval)

        session_start = datetime.datetime.strptime(self.symbols[symbol].rawdata['STARTTIME'], '%H:%M:%S')
        session_stop = datetime.datetime.strptime(self.symbols[symbol].rawdata['STOPTIME'], '%H:%M:%S')
        #print('barchart session_start=%s session_stop=%s' % (session_start, session_stop))

        # if start time is a negative integer, use it as an offset from the end time
        # limit start and end to the session start and stop times
        if str(bar_start).startswith('-'):
            offset = int(str(bar_start))
            bar_end = self.feed_now + datetime.timedelta(minutes=1)
            if bar_end.time() > session_stop.time():
                bar_end = datetime.datetime(bar_end.year, bar_end.month, bar_end.day, session_stop.hour, session_stop.minute, 0)
            if table == 'DAILY':
                delta = [
                    datetime.timedelta(days=offset),
                    datetime.timedelta(weeks=offset),
                    datetime.timedelta(days=offset * 30)
                ][interval]
            else:
                delta = datetime.timedelta(minutes=offset * interval)
            bar_start = bar_end + delta
            if bar_start.time() < session_start.time():
                bar_start = datetime.datetime(
                    bar_start.year, bar_start.month, bar_start.day, session_start.hour, session_start.minute, 0
                )
            #print('offset bar start: start=%s end=%s' % (repr(bar_start), repr(bar_end)))
        else:
            # implement defaults for bar_start, bar_end
            if bar_start == '.':
                bar_start = self.feed_now.date().isoformat()
            elif re.match('^\d\d\d\d-\d\d-\d\d \d\d:\d\d:\d\d$', bar_start):
                # bar_start provided with time; adjust timezone
                bar_start = self.unlocalize_time(datetime.datetime.strptime(bar_start, '%Y-%m-%d %H:%M:%S')).isoformat(' ')[:19]
            elif not re.match('^\d\d\d\d-\d\d-\d\d$', bar_start):
                return self._fail_query_bars('query_bars: bad parameter format bar_start=%s' % bar_start, callback)

            if bar_end == '.':
                bar_end = bar_start[:10]
            elif re.match('^\d\d\d\d-\d\d-\d\d \d\d:\d\d:\d\d$', bar_end):
                bar_end = self.unlocalize_time(datetime.datetime.strptime(bar_end, '%Y-%m-%d %H:%M:%S')).isoformat(' ')[:19]
            elif not re.match('^\d\d\d\d-\d\d-\d\d$', bar_end):
                return self._fail_query_bars('query_bars: bad parameter format bar_end=%s' % bar_end, callback)

            if len(bar_start) == 10:
                bar_start += session_start.time().strftime(' %H:%M:%S')

            if len(bar_end) == 10:
                bar_end += session_stop.time().strftime(' %H:%M:%S')

            #print('+++ bar_start=%s bar_end=%s' % (repr(bar_start), repr(bar_end)))
            bar_start = datetime.datetime.strptime(bar_start, '%Y-%m-%d %H:%M:%S')
            bar_end = datetime.datetime.strptime(bar_end, '%Y-%m-%d %H:%M:%S')

        # limit bar_start and bar_end to stay within session start, stop
        if bar_start.time() < session_start.time() or table == 'DAILY':
            bar_start = datetime.datetime(
                bar_start.year, bar_start.month, bar_start.day, session_start.hour, session_start.minute, 0
            )

        if bar_end.time() > session_stop.time() or table == 'DAILY':
            bar_end = datetime.datetime(bar_end.year, bar_end.month, bar_end.day, session_stop.hour, session_stop.minute, 0)

        where = ','.join(
            [
                "DISP_NAME='%s'" % symbol,
                "BARINTERVAL=%d" % interval,
                "STARTDATE='%s'" % bar_start.strftime('%Y/%m/%d'),
                "CHART_STARTTIME='%s'" % bar_start.strftime('%H:%M'),
                "STOPDATE='%s'" % bar_end.strftime('%Y/%m/%d'),
                "CHART_STOPTIME='%s'" % bar_end.strftime('%H:%M'),
            ]
        )

        #print('barchart where=%s' % repr(where))

        cb = API_Callback(self, '%s;%s' % (table, where), 'barchart', callback, self.callback_timeout['BARCHART'])
        self.cxn_get('TA_SRV', BARCHART_TOPIC).request(table, BARCHART_FIELDS, where, cb)
        self.bardata_callbacks.append(cb)

    def format_barchart(self, rows):
        #pprint({'format_barchart': rows})
        bars = None
        if type(rows) == list and len(rows) == 1:
            row = rows[0]
            # DAILY bars have no time values, so spoof for the parser
            if row['TRDTIM_1'] == 'Error 17':
                symbol = self.symbols[row['DISP_NAME']]
                session_start = symbol.rawdata['STARTTIME']
                row['TRDTIM_1'] = [session_start for t in row['TRD_DATE']]
            types = {k: type(v) for k, v in row.items()}
            #print('types = %s' % repr(types))
            if types == {'DISP_NAME': str, 'TRD_DATE': list, 'TRDTIM_1': list, 'OPEN_PRC': list, 'HIGH_1': list, 'LOW_1': list,
                         'SETTLE': list, 'ACVOL_1': list}:
                bars = [
                    self.format_barchart_date(row['TRD_DATE'][i], row['TRDTIM_1'][i], self.id) + [
                        self.parse_tql_float(row['OPEN_PRC'][i], self.id, 'OPEN_PRC'),
                        self.parse_tql_float(row['HIGH_1'][i], self.id, 'HIGH_1'),
                        self.parse_tql_float(row['LOW_1'][i], self.id, 'LOW_1'),
                        self.parse_tql_float(row['SETTLE'][i], self.id, 'SETTLE'),
                        self.parse_tql_int(row['ACVOL_1'][i], self.id, 'ACVOL_1')
                    ] for i in range(len(row['TRD_DATE']))
                ]
        if not bars:
            self.error_handler(self, 'barchart data format failed: %s' % repr(rows))
        return json.dumps(bars)

    def format_barchart_date(self, bdate, btime, pid):
        """return date and time as tuple ('yyyy-mm-dd', 'hh:mm:ss') or ('', '')"""
        bar_date = self.parse_tql_date(bdate, pid, 'TRD_DATE')
        bar_time = self.parse_tql_time(btime, pid, 'TRDTIM_1')
        if bar_date and bar_time:
            bartime = datetime.datetime.combine(bar_date, bar_time)
            bartime = self.localize_time(bartime)
            ret = bartime.isoformat()[:19].split('T')
        else:
            ret = ['', '']
        return ret

    def query_connection_status(self):
        return self.connection_status

    def set_order_route(self, route, callback):
        if type(route) == str:
            if route.startswith('{'):
                route = json.loads(route)
            elif route.startswith('"'):
                route = {json.loads(route): None}
            else:
                route = {route: None}
        if (type(route) == dict) and (len(route.keys()) == 1) and (type(list(route.keys())[0]) == str):
            self.order_route = route
            if callback:
                self.get_order_route(callback)
        else:
            if callback:
                callback.errback(Failure(Exception('cannot set order route %s' % route)))
            else:
                self.error_handler(None, 'Cannot set order route %s' % repr(route))

    def get_order_route(self, callback):
        API_Callback(self, 0, 'get_order_route', callback).complete(self.order_route)
