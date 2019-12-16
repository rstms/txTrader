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

from txtrader.config import Config

CALLBACK_METRIC_HISTORY_LIMIT = 1024

TIMEOUT_TYPES = ['DEFAULT', 'ACCOUNT', 'ADDSYMBOL', 'ORDER', 'ORDERSTATUS', 'POSITION', 'TIMER', 'BARCHART']

# default RealTick orders to NYSE and Stock type
RTX_EXCHANGE='NYS'
RTX_STYPE=1

# allow disable of tick requests for testing

ENABLE_CXN_DEBUG = False

DISCONNECT_SECONDS = 30 
SHUTDOWN_ON_DISCONNECT = True 

BARCHART_FIELDS = 'DISP_NAME,TRD_DATE,TRDTIM_1,OPEN_PRC,HIGH_1,LOW_1,SETTLE,ACVOL_1'
BARCHART_TOPIC = 'LIVEQUOTE'

from twisted.python import log
from twisted.python.failure import Failure
from twisted.internet.protocol import Protocol, ReconnectingClientFactory
from twisted.protocols.basic import LineReceiver 
from twisted.internet import reactor, defer
from twisted.internet.task import LoopingCall
from twisted.web import server
from socket import gethostname

class RtxClient(LineReceiver):
    delimiter = '\n'
    # set 16MB line buffer
    MAX_LENGTH = 0x1000000
    def __init__(self, rtx):
        self.rtx = rtx

    def connectionMade(self):
        self.rtx.gateway_connect(self)

    def lineReceived(self, data):
        self.rtx.gateway_receive(data)

    def lineLengthExceeded(self, line):
        self.rtx.force_disconnect('RtxClient: Line length exceeded: line=%s' % repr(line))

class RtxClientFactory(ReconnectingClientFactory):
    initialDelay = 15
    maxDelay = 60
    def __init__(self, rtx):
        self.rtx = rtx

    def startedConnecting(self, connector):
        self.rtx.output('RTGW: Started to connect.')
    
    def buildProtocol(self, addr):
        self.rtx.output('RTGW: Connected.')
        self.resetDelay()
        return RtxClient(self.rtx)

    def clientConnectionLost(self, connector, reason):
        self.rtx.output('RTGW: Lost connection.  Reason: %s' % reason)
        ReconnectingClientFactory.clientConnectionLost(self, connector, reason)
        self.rtx.gateway_connect(None)

    def clientConnectionFailed(self, connector, reason):
        self.rtx.output('Connection failed. Reason: %s' % reason)
        ReconnectingClientFactory.clientConnectionFailed(self, connector, reason)
        self.rtx.gateway_connect(None)

class API_Symbol(object):
    def __init__(self, api, symbol, client_id, init_callback):
        self.api = api
        self.api.symbols[symbol]=self
        self.id = str(uuid1())
        self.output = api.output
        self.clients = set([client_id])
        self.callback = init_callback
        self.symbol = symbol
        self.fullname = ''
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
        self.last_quote = ''
        self.output('API_Symbol %s %s created for client %s' % (self, symbol, client_id))
        self.barchart = {}

        # request initial symbol data
        self.cxn_updates = None
        self.cxn_init = api.cxn_get('TA_SRV', 'LIVEQUOTE')
        cb = API_Callback(self.api, self.cxn_init.id, 'init_symbol', RTX_LocalCallback(self.api, self.init_handler, self.init_failed), self.api.callback_timeout['ADDSYMBOL'])
        self.cxn_init.request('LIVEQUOTE', '*', "DISP_NAME='%s'" % symbol, cb)

    def __str__(self):
        return 'API_Symbol(%s bid=%s bidsize=%d ask=%s asksize=%d last=%s size=%d volume=%d close=%s vwap=%s clients=%s' % (self.symbol, self.bid, self.bid_size, self.ask, self.ask_size, self.last, self.size, self.volume, self.close, self.vwap, self.clients)

    def __repr__(self):
        return str(self)

    def export(self):
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
        }
        if self.api.enable_high_low: 
          ret['high'] = self.high
          ret['low'] = self.low
        if self.api.enable_ticker:
          ret['bid'] = self.bid
          ret['bidsize'] = self.bid_size
          ret['ask'] = self.ask
          ret['asksize'] = self.ask_size
        #if self.api.enable_barchart:
        #  ret['bars'] = self.barchart_render()
        return ret

    def add_client(self, client):
        self.output('API_Symbol %s %s adding client %s' %
                    (self, self.symbol, client))
        self.clients.add(client)

    def del_client(self, client):
        self.output('API_Symbol %s %s deleting client %s' %
                    (self, self.symbol, client))
        self.clients.discard(client)
        if not self.clients:
            self.output('Removing %s from watchlist' % self.symbol)
            if self.cxn_updates:
                service, topic, table, what, where = self.quotes_advise_fields()
                cb = API_Callback(self.api, self.cxn_updates.id, 'unadvise', RTX_LocalCallback(self.api, self.cancel_quotes_advise))
                self.cxn_updates.unadvise(table, what, where, cb)
                self.cxn_updates = None

    def cancel_quotes_advise(self, data):
        self.output('quotes_advise terminated: %s' % repr(data))

    def update_quote(self):
        quote = 'quote.%s:%s %d %s %d' % (
            self.symbol, self.bid, self.bid_size, self.ask, self.ask_size)
        if quote != self.last_quote:
            self.last_quote = quote
            self.api.WriteAllClients(quote)

    def update_trade(self):
        self.api.WriteAllClients('trade.%s:%s %d %d' % (
            self.symbol, self.last, self.size, self.volume))

    def init_handler(self, data):
        data = json.loads(data)
        self.parse_fields(None, data[0])
        self.rawdata = data[0]
        for k,v in self.rawdata.items():
            if str(v).startswith('Error '):
                self.rawdata[k]=''
        self.cxn_init = None
  
        # if this is a valid symbol
        if self.api.enable_barchart:
 	    self.barchart_query('.', self.complete_barchart_init, self.barchart_init_failed)
        elif self.api.symbol_init(self):
            self.complete_symbol_init()

    def init_failed(self, error):
        self.api.error_handler(repr(self), 'ERROR: Initial query failed for symbol %s', self.symbol)

    def barchart_query(self, start, callback, errback):
        self.api.query_bars(self.symbol, 1, start, '.', RTX_LocalCallback(self.api, callback, errback))
        
    def barchart_init_failed(self, error):
        self.api.error_handler(repr(self), 'ERROR: Initial BARCHART query failed for symbol %s', self.symbol)

    def complete_barchart_init(self, bars):
        self.barchart_update(bars)
        if self.api.symbol_init(self):
            self.complete_symbol_init()

    def complete_symbol_init(self):
        # enable live price updates 
        self.output('Adding %s to watchlist' % self.symbol)
        service, topic, table, what, where = self.quotes_advise_fields()
        self.cxn_updates = self.api.cxn_get(service, topic)
        self.cxn_updates.advise(table, what, where, self.parse_fields)

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
        trade_flag = False
        quote_flag = False
        pid = 'API_Symbol(%s)' % self.symbol
 
        if data == None:
            self.api.force_disconnect('LIVEQUOTE Advise has been terminated by API for %s' % pid)
            return

        if 'TRDPRC_1' in data.keys():
            self.last = self.api.parse_tql_float(data['TRDPRC_1'], pid, 'TRDPRC_1')
            trade_flag = True
            if 'TRDTIM_1' in data.keys() and 'TRD_DATE' in data.keys():
                self.last_trade_time = ' '.join(self.api.format_barchart_date(data['TRD_DATE'], data['TRDTIM_1']))
            else:
                self.api.error_handler(repr(self), 'ERROR: TRDPRC_1 without TRD_DATE, TRDTIM_1')
           
            # don't request an update during the symbol init processing
            if self.api.enable_barchart and (not self.cxn_init):
                # query a barchart update after each trade
 	        self.barchart_query('-5', self.barchart_update)

        if 'HIGH_1' in data.keys():
            self.high = self.api.parse_tql_float(data['HIGH_1'], pid, 'HIGH_1')
            trade_flag = True
        if 'LOW_1' in data.keys():
            self.low = self.api.parse_tql_float(data['LOW_1'], pid, 'LOW_1')
            trade_flag = True
        if 'TRDVOL_1' in data.keys():
            self.size = self.api.parse_tql_int(data['TRDVOL_1'], pid, 'TRDVOL_1')
            trade_flag = True
        if 'ACVOL_1' in data.keys():
            self.volume = self.api.parse_tql_int(data['ACVOL_1'], pid, 'ACVOL_1')
            trade_flag = True
        if 'BID' in data.keys():
            self.bid = self.api.parse_tql_float(data['BID'], pid, 'BID')
            if self.bid and 'BIDSIZE' in data.keys():
                self.bidsize = self.api.parse_tql_int(data['BIDSIZE'], pid, 'BIDSIZE')
            else:
                self.bidsize = 0
            quote_flag = True
        if 'ASK' in data.keys():
            self.ask = self.api.parse_tql_float(data['ASK'], pid, 'ASK')
            if self.ask and 'ASKSIZE' in data.keys():
              self.asksize = self.api.parse_tql_int(data['ASKSIZE'], pid, 'ASKSIZE')
            else:
                self.asksize = 0
            quote_flag = True
        if 'COMPANY_NAME' in data.keys():
            self.fullname = self.api.parse_tql_str(data['COMPANY_NAME'], pid, 'COMPANY_NAME')
        if 'OPEN_PRC' in data.keys():
            self.open = self.api.parse_tql_float(data['OPEN_PRC'], pid, 'OPEN_PRC')
        if 'HST_CLOSE' in data.keys():
            self.close = self.api.parse_tql_float(data['HST_CLOSE'], pid, 'HST_CLOSE')
        if 'VWAP' in data.keys():
            self.vwap = self.api.parse_tql_float(data['VWAP'], pid, 'VWAP')

        if self.api.enable_ticker:
            if quote_flag:
                self.update_quote()
            if trade_flag:
                self.update_trade()

    def barchart_render(self):
        return [key.split(' ') + self.barchart[key] for key in sorted(self.barchart.keys())]

    def barchart_update(self, bars):
        for bar in json.loads(bars):
            print('===barchart_update %s' % (repr(bar)))
            self.barchart['%s %s' % (bar[0], bar[1])] = bar[2:]        


class API_Order(object):
    def __init__(self, api, oid, data, origin, callback=None):
        #pprint({'new API_Order id=%s origin=%s' % (oid, origin): data})
        self.api = api
        self.oid = oid
        self.callback = callback
        self.updates = []
        self.suborders = {}
        self.fields = {}
        self.identified = False
        self.ticket = 'undefined'
        data['status'] = 'Initialized'
        data['origin'] = origin
        self.update(data, init=True)

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
            if order_id in self.suborders.keys():
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

        if self.api.log_order_updates:
            self.api.output('ORDER_UPDATE: OID=%s ORDER_ID=%s %s' % (self.oid, order_id, change))

        # only apply new or changed messages to the base order; (don't move order status back in time when refresh happens)

        if change in ['new', 'changed']:
            changes={} 
            for k,v in data.items():
                ov = self.fields.setdefault(k,None)
                self.fields[k]=v
                if v!=ov:
                    changes[k]=v

            if changes:
                if self.api.log_order_updates:
                    self.api.output('ORDER_CHANGES: OID=%s ORDER_ID=%s %s' % (self.oid, order_id, repr(changes)))
                #if order_id != self.oid:
                update_type = data['TYPE'] if 'TYPE' in data else 'Undefined'
                self.updates.append({'id': order_id, 'type':  update_type, 'fields': changes, 'time': time.time() })

        if not init:
            if json.dumps(self.fields) != field_state:
                self.api.send_order_status(self)

    def update_fill_fields(self):
        if self.fields['TYPE'] in ['UserSubmitOrder', 'ExchangeTradeOrder']:
            if 'VOLUME_TRADED' in self.fields:
                self.fields['filled'] =self.fields['VOLUME_TRADED']
            if 'ORDER_RESIDUAL' in self.fields:
                self.fields['remaining']=self.fields['ORDER_RESIDUAL']
            if 'AVG_PRICE' in self.fields: 
                self.fields['avgfillprice']=self.fields['AVG_PRICE']

    def render(self):
        # customize fields for standard txTrader order status 
        if 'ORIGINAL_ORDER_ID' in self.fields:
            self.fields['permid']=self.fields['ORIGINAL_ORDER_ID']
        self.fields['symbol']=self.fields['DISP_NAME']
        self.fields['account']=self.api.make_account(self.fields)
        self.fields['quantity']=self.fields['VOLUME']
        self.fields['class'] = self.ticket

        status = self.fields.setdefault('CURRENT_STATUS', 'UNDEFINED')
        otype = self.fields.setdefault('TYPE', 'Undefined')
        #print('render: permid=%s ORDER_ID=%s CURRENT_STATUS=%s TYPE=%s' % (self.fields['permid'], self.fields['ORDER_ID'], status, otype))
        #pprint(self.fields)
        if status=='PENDING': 
            self.fields['status'] = 'Submitted'
        elif status=='LIVE':
            self.fields['status'] = 'Pending'
            self.update_fill_fields()
        elif status=='COMPLETED':
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
        elif status=='CANCELLED':
            self.fields['status'] = 'Cancelled'
        elif status=='DELETED':
            self.fields['status'] = 'Error'
        else:
            self.api.error_handler(self.oid, 'Unknown CURRENT_STATUS: %s' % status)
            self.fields['status'] = 'Error'
            
        self.fields['updates'] = self.updates
        f = self.fields 
        self.fields['text'] = '%s %d %s (%s)' % (f['BUYORSELL'], int(f['quantity']), f['symbol'], f['status'])

        ret = {'raw':{}}
        for k,v in self.fields.iteritems():
            if k.islower():
                ret[k]=v
            else:
                ret['raw'][k]=v
        return ret

    def is_filled(self):
        return bool(self.fields['CURRENT_STATUS']=='COMPLETED' and
            self.has_fill_type() and
            'ORIGINAL_VOLUME' in self.fields and
            'VOLUME_TRADED' in self.fields and 
            self.fields['ORIGINAL_VOLUME'] == self.fields['VOLUME_TRADED'])

    def is_cancelled(self):
        return bool(self.fields['CURRENT_STATUS']=='COMPLETED' and
            'status' in self.fields and self.fields['status'] == 'Error' and
            'REASON' in self.fields and self.fields['REASON'] == 'User cancel')
 
    def has_fill_type(self):
        if self.fields['TYPE']=='ExchangeTradeOrder':
            return True
        for update_type in [update['type'] for update in self.updates]:
            if update_type =='ExchangeTradeOrder':
                return True
        return False

class API_Callback(object):
    def __init__(self, api, id, label, callable, timeout=0):
        """callable is stored and used to return results later"""
        #api.output('API_Callback.__init__%s' % repr((self, api, id, label, callable, timeout)))
        self.api = api
        self.id = id
        self.label = label
        self.started = time.time()
        self.timeout = timeout or api.callback_timeout['DEFAULT']
        self.expire = self.started + timeout
        self.callable = callable
        self.done = False
        self.data = None
        self.expired = False

    def complete(self, results):
        """complete callback by calling callable function with value of results"""
        self.elapsed = time.time() - self.started
        if not self.done:
            ret = self.format_results(results)
            if self.callable.callback.__name__ == 'sendString':
                ret = '%s.%s: %s' % (self.api.channel, self.label, ret)
            #self.api.output('API_Callback.complete(%s)' % repr(ret))
            self.callable.callback(ret)
            self.callable = None
            self.done = True
        else:
            self.api.error_handler(self.id, '%s completed after timeout: callback=%s elapsed=%.2f' % (self.label, repr(self), self.elapsed))
            self.api.output('results=%s' % repr(results))
        self.api.record_callback_metrics(self.label, int(self.elapsed * 1000), self.expired)

    def check_expire(self):
        #SElf.api.output('API_Callback.check_expire() %s' % self)
        if not self.done:
            if time.time() > self.expire:
                msg = 'error: callback expired: %s' % repr((self.id, self.label, self))
                self.api.WriteAllClients(msg)
                if self.callable.callback.__name__ == 'sendString':
                    self.callable.callback('%s.error: %s callback expired', (self.api.channel, self.label))
                else:
                    self.callable.errback(Failure(Exception(msg)))
                self.expired = True
                self.done = True

    # TODO: all of these format_* really belong in the api class

    def format_results(self, results):
        #print('format_results: label=%s results=%s' % (self.label, results))
        if self.label == 'account_data':
            results = self.format_account_data(results)
        elif self.label == 'positions':
            results = self.format_positions(results)
        elif self.label == 'orders':
            results = self.format_orders(results)
        elif self.label == 'tickets':
            results = self.format_tickets(results)
        elif self.label=='executions':
            results = self.format_executions(results)
        elif self.label == 'order_status':
            results = self.format_orders(results, self.id)
        elif self.label == 'barchart':
            results = self.api.format_barchart(results)

        return json.dumps(results)

    def format_account_data(self, rows):
        data = rows[0] if rows else rows
        if data and 'EXCESS_EQ' in data:
            data['_cash'] = round(float(data['EXCESS_EQ']),2)
        return data

    def format_positions(self, rows):
        # Positions should return {'ACCOUNT': {'SYMBOL': QUANTITY, ...}, ...}
        positions = {}
        [positions.setdefault(a, {}) for a in self.api.accounts]
	#print('format_positions: rows=%s' % repr(rows))
        for pos in rows:
            if pos:
	        #print('format_positions: pos=%s' % repr(pos))
                account = self.api.make_account(pos)
                symbol = pos['DISP_NAME']
                positions[account].setdefault(symbol, 0)
                # if LONG positions exist, add them, if SHORT positions exist, subtract them
                for m,f in [(1,'LONGPOS'), (1, 'LONGPOS0'), (-1, 'SHORTPOS'), (-1, 'SHORTPOS0')]:
                    if f in pos:
                        positions[account][symbol] += m * int(pos[f])
        return positions

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
            results={}
            for k,v in self.api.orders.items():
                # don't return staged order tickets
                if v.ticket == _filter:
                    results[k] = v.render()
        return results

    def format_executions(self, rows):
        for row in rows:
            if row:
                self.api.handle_order_response(row)
        results={}
        for k,v in self.api.orders.items():
            if v.is_filled():
                results[k]=v.fields
                results[k]['updates']=v.updates
        return results


class RTX_Connection(object):
    def __init__(self, api, service, topic, enable_logging=False):
        self.api = api
        self.id = str(uuid1())
        self.service = service
        self.topic = topic
        self.key = '%s;%s' % (service, topic)
        self.last_query = ''
        self.api.output('RTX_Connection init %s' % repr(self))
        self.api.cxn_register(self)
        self.api.gateway_send('connect %s %s' % (self.id, self.key))
        self.ack_pending = 'CONNECTION PENDING'
        self.log = enable_logging
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
        self.api.output('RTX_Connection delete %s' % repr(self))

    def __repr__(self):
        return self.__str__()

    def __str__(self):
        return '<RTX_Connection instance at %s %s %s %s>' % (hex(id(self)), self.id, self.key, self.last_query)

    def update_ready(self):
        self.ready = not(
            self.ack_pending or self.response_pending or self.status_pending or self.status_callback or self.update_callback or self.update_handler)
        #self.api.output('update_ready() %s %s' % (self.id, self.ready))
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
        if self.log:
            self.api.output('Ack Received: %s %s' % (self.id, data))
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
        if self.log:
            self.api.output('Connection Response: %s %s' % (self, data))
        if self.response_pending:
            self.response_rows.append(data['row'])
            if data['complete']:
                if self.response_callback:
                    self.response_callback.complete(self.response_rows)
                    self.response_callback = None
                self.response_pending = None
                self.response_rows = None
        else:
            self.api.error_handler(id, 'Response Unexpected: %s' % data)

    def handle_response_failure(self):
        if self.response_callback:
            self.response_callback.complete(None)

    def handle_status(self, data):
        if self.log:
            self.api.output('Connection Status: %s %s' % (self, data))
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
                        self.api.output('%s sending on_connect_action: %s' % (repr(self), repr(self.on_connect_action)))
                        self.send(cmd, arg, exa, cba, cbr, exs, cbs, cbu, uhr)
                        self.on_connect_action = None
                        print('after on_connect_action send: self.status_pending=%s' % self.status_pending)

                if self.status_callback:
                    self.status_callback.complete(data)
                    self.status_callback = None
            else:
                self.api.error_handler(self.id, 'Status Error: %s' % data)
        else:
            self.api.error_handler(self.id, 'Status Unexpected: %s' % data)
            # if ADVISE is active; call handler function with None to notifiy caller the advise has been terminated
            if self.update_handler and data['msg']=='OnTerminate':
                self.update_handler(self, None)
            self.handle_response_failure()

    def handle_update(self, data):
        if self.log:
            self.api.output('Connection Update: %s %s' % (self, repr(d)))
        if self.update_callback:
            self.update_callback.complete(data['row'])
            self.update_callback = None
        else:
            if self.update_handler:
                self.update_handler(self, data['row'])
            else:
                self.api.error_handler(self.id, 'Update Unexpected: %s' % repr(data))

    def query(self, cmd, table, what, where, expect_ack=None, ack_callback=None, response_callback=None, expect_status=None, status_callback=None, update_callback=None, update_handler=None):
        tql='%s;%s;%s' % (table, what, where)
        self.last_query='%s: %s' % (cmd, tql)
        ret = self.send(cmd, tql, expect_ack, ack_callback, response_callback, expect_status, status_callback, update_callback, update_handler)

    def request(self, table, what, where, callback):
        return self.query('request', table, what, where, expect_ack='REQUEST_OK', response_callback=callback)

    def advise(self, table, what, where, handler):
        return self.query('advise', table, what, where, expect_ack='ADVISE_OK', expect_status='OnOtherAck', update_handler=handler)

    def adviserequest(self, table, what, where, callback, handler):
        return self.query('adviserequest', table, what, where, expect_ack='ADVISE_REQUEST_OK', response_callback=callback, expect_status='OnOtherAck', update_handler=handler)

    def unadvise(self, table, what, where, callback):
        # force ready state so the unadvise command will be sent
        self.ready = True
        return self.query('unadvise', table, what, where, expect_ack='UNADVISE_OK', expect_status='OnOtherAck', status_callback=callback)

    def poke(self, table, what, where, data, ack_callback, callback):
        tql = '%s;%s;%s!%s' % (table, what, where, data)
        self.last_query = 'poke: %s' % tql
        return self.send('poke', tql, expect_ack="POKE_OK", ack_callback=ack_callback, expect_status='OnOtherAck', status_callback=callback)

    def execute(self, command, callback):
        self.last_query = 'execute: %s' % command
        return self.send('execute', command, expect_ack="EXECUTE_OK", ack_callback=callback)

    def terminate(self, code, callback):
        self.last_query = 'terminate: %s' % str(code) 
        return self.send('terminate', str(code), expect_ack="TERMINATE_OK", ack_callback=callback)

    def send(self, cmd, args, expect_ack=None, ack_callback=None, response_callback=None, expect_status=None, status_callback=None, update_callback=None, update_handler=None):
        if self.ready:
            self.cmd = cmd
            if 'request' in cmd:
                self.response_rows = []
            ret = self.api.gateway_send('%s %s %s' % (cmd, self.id, args))
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
                self.api.error_handler(self.id, 'Failure: on_connect_action already exists: %s' % repr(self.on_connect_action))
                ret = False
            else:
                self.api.output('%s storing on_connect_action (%s)...' % (self, cmd))
                self.on_connect_action = (cmd, args, expect_ack, ack_callback, response_callback, expect_status, status_callback, update_callback, update_handler)
                ret = True
        return ret


class RTX_LocalCallback(object):
    def __init__(self, api, callback_handler, errback_handler=None):
        self.api = api
        self.callable = callback_handler
        self.errback_handler = errback_handler

    def callback(self, data):
        if self.callable:
            self.callable(data)
        else:
            self.api.error_handler(repr(self), 'Failure: undefined callback_handler for Connection: %s data=%s' % (repr(self), repr(data)))

    def errback(self, error):
        if self.errback_handler:
            self.errback_handler(error)
        else:
            self.api.error_handler(repr(self), 'Failure: undefined errback_handler for Connection: %s error=%s' % (repr(self), repr(error)))

class RTX(object):
    def __init__(self):
        self.label = 'RTX Gateway'
        self.channel = 'rtx'
        self.id = 'RTX'
        self.output('RTX init')
        self.config = Config(self.channel)
        self.api_hostname = self.config.get('API_HOST')
        self.api_port = int(self.config.get('API_PORT'))
        self.username = self.config.get('USERNAME')
        self.password = self.config.get('PASSWORD')
        self.http_port = int(self.config.get('HTTP_PORT'))
        self.tcp_port = int(self.config.get('TCP_PORT'))
        self.enable_ticker = bool(int(self.config.get('ENABLE_TICKER')))
        self.enable_high_low= bool(int(self.config.get('ENABLE_HIGH_LOW')))
        self.enable_barchart = bool(int(self.config.get('ENABLE_BARCHART')))
        self.enable_seconds_tick = bool(int(self.config.get('ENABLE_SECONDS_TICK')))
        self.log_api_messages = bool(int(self.config.get('LOG_API_MESSAGES')))
        self.debug_api_messages = bool(int(self.config.get('DEBUG_API_MESSAGES')))
        self.log_client_messages = bool(int(self.config.get('LOG_CLIENT_MESSAGES')))
        self.log_order_updates = bool(int(self.config.get('LOG_ORDER_UPDATES')))
        self.time_offset = int(self.config.get('TIME_OFFSET'))
        self.callback_timeout = {}
        for t in TIMEOUT_TYPES:
            self.callback_timeout[t] = int(self.config.get('TIMEOUT_%s' % t))
            self.output('callback_timeout[%s] = %d' % (t, self.callback_timeout[t]))
        self.now = None
        self.feed_now = None
        self.trade_minute = -1
        self.feedzone = pytz.timezone(self.config.get('API_TIMEZONE'))
        self.localzone = tzlocal.get_localzone()
        self.current_account = ''
        self.clients = set([])
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
        self.execution_callbacks = []
        self.order_callbacks = []
        self.bardata_callbacks = []
        self.cancel_callbacks = []
        self.order_status_callbacks = []
        self.ticket_callbacks = []
        self.add_symbol_callbacks = []
        self.accountdata_callbacks = []
        self.set_account_callbacks = []
        self.account_request_callbacks = []
        self.account_request_pending = True
        self.timer_callbacks = []
        self.connected = False
        self.last_connection_status = ''
        self.connection_status = 'Initializing'
        self.LastError = -1
        self.next_order_id = -1
        self.last_minute = -1
        self.symbols = {}
        self.barchart = None
        self.primary_exchange_map = {}
        self.gateway_sender = None
        self.active_cxn = {}
        self.idle_cxn = {}
        self.cx_time = None
        self.seconds_disconnected = 0
        self.callback_metrics = {}
        self.set_order_route(self.config.get('API_ROUTE'), None)
        reactor.connectTCP(self.api_hostname, self.api_port, RtxClientFactory(self))
        self.repeater = LoopingCall(self.EverySecond)
        self.repeater.start(1)

    def flags(self):
        return {
          'TICKER': self.enable_ticker,
          'HIGH_LOW': self.enable_high_low,
          'BARCHART': self.enable_barchart,
          'SECONDS_TICK': self.enable_seconds_tick,
          'TIME_OFFSET': self.time_offset,
        }

    def record_callback_metrics(self, label, elapsed, expired):
        m = self.callback_metrics.setdefault(label, {'tot':0, 'min': 9999, 'max': 0, 'avg': 0, 'exp': 0, 'hst': []})
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
        if ENABLE_CXN_DEBUG:
            self.output('cxn_register: %s' % repr(cxn))
        self.active_cxn[cxn.id] = cxn

    def cxn_activate(self, cxn):
        if ENABLE_CXN_DEBUG:
            self.output('cxn_activate: %s' % repr(cxn))
        if not cxn.key in self.idle_cxn.keys():
            self.idle_cxn[cxn.key] = []
        self.idle_cxn[cxn.key].append(cxn)

    def cxn_get(self, service, topic):
        key = '%s;%s' % (service, topic)
        if key in self.idle_cxn.keys() and len(self.idle_cxn[key]):
            cxn = self.idle_cxn[key].pop()
        else:
            cxn = RTX_Connection(self, service, topic)
        if ENABLE_CXN_DEBUG:
            self.output('cxn_get() returning: %s' % repr(cxn))
        return cxn

    def gateway_connect(self, protocol):
        if protocol:
            self.gateway_sender = protocol.sendLine
            self.gateway_transport = protocol.transport
            self.update_connection_status('Connecting')
        else:
            self.gateway_sender = None
            self.connected = False
            self.seconds_disconnected = 0
            self.account_request_pending = False
            self.accounts = None
            self.update_connection_status('Disconnected')
            self.error_handler(self.id, 'error: API Disconnected')

        return self.gateway_receive

    def gateway_send(self, msg):
        if self.debug_api_messages:
            self.output('<--TX[%d]--' % (len(msg)))
            hexdump(msg)
        if self.log_api_messages:
            self.output('<-- %s' % repr(msg))
        if self.gateway_sender:
            self.gateway_sender('%s\n' % str(msg))

    def dump_input_message(self, msg):
        self.output('--RX[%d]-->' % (len(msg)))
        hexdump(msg)

    def receive_exception(self, t, e, msg):
        self.error_handler(self.id, 'Exception %s %s parsing data from RTGW' % (t, e))
        self.dump_input_message(msg)
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
            self.output('--> %s %s %s' % (msg_type, msg_id, msg_data))

        if msg_type == 'system':
            self.handle_system_message(msg_id, msg_data)
        else:
            if msg_id in self.active_cxn.keys():
                c = self.active_cxn[msg_id].receive(msg_type, msg_data)
            else:
                self.error_handler(self.id, 'Message Received on Unknown connection: %s' % repr(msg))

        return True

    def handle_system_message(self, id, data):
        if data['msg'] == 'startup':
            self.connected = True
            self.accounts = None
            self.update_connection_status('Startup')
            self.output('Connected to %s' % data['item'])
            self.setup_local_queries()
        else:
            self.error_handler(self.id, 'Unknown system message: %s' % repr(data))

    def setup_local_queries(self):
        """Upon connection to rtgw, start automatic queries"""
        #what='BANK,BRANCH,CUSTOMER,DEPOSIT'
        what='*'
        self.rtx_request('ACCOUNT_GATEWAY', 'ORDER', 'ACCOUNT', what, '',
                         'accounts', self.handle_accounts, self.accountdata_callbacks, self.callback_timeout['ACCOUNT'],
                         self.handle_initial_account_failure)

        self.cxn_get('ACCOUNT_GATEWAY', 'ORDER').advise('ORDERS', '*', '', self.handle_order_update)
        
        self.rtx_request('ACCOUNT_GATEWAY', 'ORDER', 'ORDERS', '*', '',
                        'orders', self.handle_initial_orders_response, self.openorder_callbacks, self.callback_timeout['ORDERSTATUS'])

    def handle_initial_account_failure(self, message):
        self.force_disconnect('Initial account query failed (%s)' % repr(message))

    def handle_initial_orders_response(self, rows):
        self.output('Initial Orders refresh complete.')

    def output(self, msg):
        if 'error' in msg:
            log.err(msg)
        else:
            log.msg(msg)

    def open_client(self, client):
        self.clients.add(client)

    def close_client(self, client):
        self.clients.discard(client)
        symbols = self.symbols.values()
        for ts in symbols:
            if client in ts.clients:
                ts.del_client(client)
                if not ts.clients:
                    del(self.symbols[ts.symbol])

    def set_primary_exchange(self, symbol, exchange):
        if exchange:
            self.primary_exchange_map[symbol] = exchange
        else:
            del(self.primary_exchange_map[symbol])
        return self.primary_exchange_map

    def CheckPendingResults(self):
        # check each callback list for timeouts
        for cblist in [self.timer_callbacks, self.position_callbacks, self.ticket_callbacks, self.openorder_callbacks, self.execution_callbacks, self.bardata_callbacks, self.order_callbacks, self.cancel_callbacks, self.add_symbol_callbacks, self.accountdata_callbacks, self.set_account_callbacks, self.account_request_callbacks, self.order_status_callbacks]:
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
        oid = msg['ORIGINAL_ORDER_ID'] if 'ORIGINAL_ORDER_ID' in msg else None
        ret = None
        if oid:
            if self.pending_orders and 'CLIENT_ORDER_ID' in msg:
                # this is a newly created order, it has a CLIENT_ORDER_ID
                coid = msg['CLIENT_ORDER_ID']
                if coid in self.pending_orders:
                    self.pending_orders[coid].initial_update(msg)
                    self.orders[oid] = self.pending_orders[coid]
                    del self.pending_orders[coid]
            elif self.pending_orders and (oid in self.pending_orders.keys()):
                # this is a change order, ORIGINAL_ORDER_ID will be a key in pending_orders
                self.pending_orders[oid].initial_update(msg)
                del self.pending_orders[oid]
            elif oid in self.orders.keys():
                # this is an existing order, so update it
                self.orders[oid].update(msg)
            else:
                # we've never seen this order, so add it to the collection and update it
                o = API_Order(self, oid, msg, 'realtick')
                self.orders[oid]=o
                o.update(msg)
        else:
            self.error_handler(self.id, 'handle_order_update: ORIGINAL_ORDER_ID not found in %s' % repr(msg))
            #self.output('error: handle_order_update: ORIGINAL_ORDER_ID not found in %s' % repr(msg))

    def handle_ticket_update(self, cxn, msg):
        return self.handle_ticket_response(msg)

    def handle_ticket_response(self, msg):
        tid = msg['CLIENT_ORDER_ID'] if 'CLIENT_ORDER_ID' in msg else None
        if self.pending_tickets and tid in self.pending_tickets.keys():
            self.pending_tickets[tid].initial_update(msg)
            self.tickets[tid] = self.pending_tickets[tid]
            del self.pending_tickets[tid]

    def send_order_status(self, order):
        fields = order.render()
        self.WriteAllClients('%s.%s %s %s %s' % (order.ticket, fields['permid'], fields['account'], fields['raw']['TYPE'], fields['status']))

    def make_account(self, row):
        return '%s.%s.%s.%s' % (row['BANK'], row['BRANCH'], row['CUSTOMER'], row['DEPOSIT'])

    def handle_accounts(self, rows):
        rows = json.loads(rows)
        if rows:
            self.accounts = list(set([self.make_account(row) for row in rows]))
            self.accounts.sort()
            self.account_request_pending = False
            self.WriteAllClients('accounts: %s' % json.dumps(self.accounts))
            self.update_connection_status('Up')
            for cb in self.account_request_callbacks:
                cb.complete(self.accounts)

            for cb in self.set_account_callbacks:
                self.output('set_account: processing deferred response.')
                self.process_set_account(cb.id, cb)
        else:
            self.handle_initial_account_failure('initial account query returned no data')

    def set_account(self, account_name, callback):
        cb = API_Callback(self, account_name, 'set-account', callback)
        if self.accounts:
            self.process_set_account(account_name, cb)
        elif self.account_request_pending:
            self.set_account_callbacks.append(cb)
        else:
            self.error_handler(self.id, 'set_account; no data, but no account_request_pending')
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

    def EverySecond(self):
        if self.connected:
            if self.enable_seconds_tick:
                self.rtx_request('TA_SRV', 'LIVEQUOTE', 'LIVEQUOTE', 'DISP_NAME,TRDTIM_1,TRD_DATE',
                                 "DISP_NAME='$TIME'", 'tick', self.handle_time, self.timer_callbacks, 
                                 self.callback_timeout['TIMER'], self.handle_time_error)
        else:
            self.seconds_disconnected += 1
            if self.seconds_disconnected > DISCONNECT_SECONDS:
                if SHUTDOWN_ON_DISCONNECT:
                    self.force_disconnect('Realtick Gateway connection timed out after %d seconds' % self.seconds_disconnected)
        self.CheckPendingResults()

        if not int(time.time()) % 60:
            self.EveryMinute()

    def EveryMinute(self):
        if self.callback_metrics:
            self.output('callback_metrics: %s' % json.dumps(self.callback_metrics))   

    def WriteAllClients(self, msg):
        if self.log_client_messages:
            self.output('WriteAllClients: %s.%s' % (self.channel, msg))
        msg = str('%s.%s' % (self.channel, msg))
        for c in self.clients:
            c.sendString(msg)

    def error_handler(self, id, msg):
        """report error messages"""
        self.output('ALERT: %s %s' % (id, msg))
        self.WriteAllClients('error: %s %s' % (id, msg))

    def force_disconnect(self, reason):
        self.update_connection_status('Disconnected')
        self.error_handler(self.id, 'API Disconnect: %s' % reason)
        reactor.stop()

    def parse_tql_float(self, data, pid, label):
        ret = self.parse_tql_field(data, pid, label)
        return round(float(ret),2) if ret else 0.0

    def parse_tql_int(self, data, pid, label):
        ret = self.parse_tql_field(data, pid, label)
        return int(ret) if ret else 0

    def parse_tql_str(self, data, pid, label):
        ret = self.parse_tql_field(data, pid, label)
        return str(ret) if ret else ''

    def parse_tql_time(self, data, pid, label):
        """Parse TQL ascii time field returning as number of seconds since midnight"""
        field = self.parse_tql_field(data, pid, label)
        hour, minute, second = [int(i) for i in field.split(':')[0:3]]
        ret = hour * 3600 + minute * 60 + second
        return int(ret) if ret else 0

    def parse_tql_field(self, data, pid, label):
        if str(data).lower().startswith('error '):
            if data.lower()=='error 0':
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
            self.error_handler(pid, 'Field Parse Failure: %s=%s (%s)' % (label, repr(data), code))
            ret = None
        else:
            ret = data
        return ret

    def handle_time(self, rows):
        rows = json.loads(rows)
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
                self.feed_now = datetime.datetime(year,month,day,hour,minute,second) + datetime.timedelta(seconds=self.time_offset)
                self.now = self.localize_time(self.feed_now)
		# don't add time offset
                if minute != self.last_minute:
                    self.last_minute = minute
                    self.WriteAllClients('time: %s %s:00' % (self.now.strftime('%Y-%m-%d'), self.now.strftime('%H:%M')))
        else:
            self.error_handler(self.id, 'handle_time: unexpected null input')

    def localize_time(self, feedtime):
        """return API time corrected for local timezone"""
        return self.feedzone.localize(feedtime).astimezone(self.localzone)
  
    def unlocalize_time(self, apitime):
        """reverse localize_time to convert local timezone to API time"""
        return self.localzone.localize(apitime).astimezone(self.feedzone)

    def handle_time_error(self, error):
        #time timeout error is reported as an expired callback
        self.output('time_error: %s' % repr(error))

    def connect(self):
        self.update_connection_status('Connecting')
        self.output('Awaiting startup response from RTX gateway at %s:%d...' % (self.api_hostname, self.api_port))

    def market_order(self, account, route, symbol, quantity, callback):
        return self.submit_order(account, route, 'market', 0, 0, symbol, int(quantity), callback)

    def limit_order(self, account, route, symbol, limit_price, quantity, callback):
        return self.submit_order(account, route, 'limit', float(limit_price), 0, symbol, int(quantity), callback)

    def stop_order(self, account, route, symbol, stop_price, quantity, callback):
        return self.submit_order(account, route, 'stop', 0, float(stop_price), symbol, int(quantity), callback)

    def stoplimit_order(self, account, route, symbol, stop_price, limit_price, quantity, callback):
        return self.submit_order(account, route, 'stoplimit', float(limit_price), float(stop_price), symbol, int(quantity), callback)

    def stage_market_order(self, tag, account, route, symbol, quantity, callback):
        return self.submit_order(account, route, 'market', 0, 0, symbol, int(quantity), callback, staged=tag)

    def create_order_id(self):
        return str(uuid1())

    def create_staged_order_ticket(self, account, callback):

        if not self.verify_account(account):
          API_Callback(self, 0, 'create-staged-order-ticket', callback).complete({'status': 'Error', 'errorMsg': 'account unknown'})
          return

        o=OrderedDict({})
        self.verify_account(account)
        bank, branch, customer, deposit = account.split('.')[:4]
        o['BANK']=bank
        o['BRANCH']=branch
        o['CUSTOMER']=customer
        o['DEPOSIT']=deposit
        tid = 'T-%s' % self.create_order_id() 
        o['CLIENT_ORDER_ID']=tid
        o['DISP_NAME']='N/A'
        o['STYP']=RTX_STYPE # stock
        o['EXIT_VEHICLE']='NONE'
        o['TYPE']='UserSubmitStagedOrder'

        # create callback to return to client after initial order update
        cb = API_Callback(self, tid, 'ticket', callback, self.callback_timeout['ORDER'])
        self.ticket_callbacks.append(cb)
        self.pending_tickets[tid]=API_Order(self, tid, o, 'client', cb)
        fields= ','.join(['%s=%s' %(i,v) for i,v in o.iteritems()])

        acb = API_Callback(self, tid, 'ticket-ack', RTX_LocalCallback(self, self.ticket_submit_ack_callback), self.callback_timeout['ORDER'])
        cb = API_Callback(self, tid, 'ticket', RTX_LocalCallback(self, self.ticket_submit_callback), self.callback_timeout['ORDER'])
        self.cxn_get('ACCOUNT_GATEWAY', 'ORDER').poke('ORDERS', '*', '', fields, acb, cb)
        # TODO: add cb and acb to callback lists so they can be tested for timeout

    def ticket_submit_ack_callback(self, data):
        """called when staged order ticket request has been submitted with 'poke' and Ack has returned""" 
        self.output('staged order ticket submission acknowledged: %s' % repr(data))

    def ticket_submit_callback(self, data):
        """called when staged order ticket request has been submitted with 'poke' and OnOtherAck has returned""" 
        self.output('staged order ticket submitted: %s' % repr(data))

    def submit_order(self, account, route, order_type, price, stop_price, symbol, quantity, callback, staged=None, oid=None):

        if not self.verify_account(account):
          API_Callback(self, 0, 'submit-order', callback).complete({'status': 'Error', 'errorMsg': 'account unknown'})
          return
        #bank, branch, customer, deposit = self.current_account.split('.')[:4]
        self.set_order_route(route, None)
        if type(self.order_route) != dict:
          API_Callback(self, 0, 'submit-order', callback).complete({'status': 'Error', 'errorMsg': 'undefined order route: %s' % repr(self.order_route)})
          return

        o=OrderedDict({})
        bank, branch, customer, deposit = account.split('.')[:4]
        o['BANK']=bank
        o['BRANCH']=branch
        o['CUSTOMER']=customer
        o['DEPOSIT']=deposit

        o['BUYORSELL']='Buy' if quantity > 0 else 'Sell' # Buy Sell SellShort
        o['quantity'] = quantity
        o['GOOD_UNTIL']='DAY' # DAY or YYMMDDHHMMSS
        route = self.order_route.keys()[0]
        o['EXIT_VEHICLE']=route
        
        # if order_route has a value, it is a dict of order route parameters
        if self.order_route[route]:
            for k,v in self.order_route[route].items():
                # encode strategy parameters in 0x01 delimited format
                if k in ['STRAT_PARAMETERS', 'STRAT_REDUNDANT_DATA']:
                    v = ''.join(['%s\x1F%s\x01' % i for i in v.items()])
                o[k]=v

        o['DISP_NAME']=symbol
        o['STYP']=RTX_STYPE # stock

        if symbol in self.primary_exchange_map.keys():
            exchange = self.primary_exchange_map[symbol]
        else:
            exchange = RTX_EXCHANGE
        o['EXCHANGE']=exchange
        
        if order_type == 'market':
            o['PRICE_TYPE'] = 'Market'
        elif order_type=='limit':
            o['PRICE_TYPE']='AsEntered' 
            o['PRICE']=price
        elif order_type=='stop':
            o['PRICE_TYPE']='Stop' 
            o['STOP_PRICE']=stop_price
        elif type=='stoplimit':
            o['PRICE_TYPE']='StopLimit' 
            o['STOP_PRICE']=stop_price
            o['PRICE']=price
        else:
            msg = 'unknown order type: %s' % order_type
            self.error_handler(self.id, msg)
            raise Exception(msg)

        o['VOLUME_TYPE']='AsEntered'
        o['VOLUME']=abs(quantity)
        
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
            o['CLIENT_ORDER_ID']=oid
            submission = 'Order'
            
        o['TYPE'] = 'UserSubmit%s%s' % (staging, submission)

        # create callback to return to client after initial order update
        cb = API_Callback(self, oid, 'order', callback, self.callback_timeout['ORDER'])
        self.order_callbacks.append(cb)
        if oid in self.orders:
            self.pending_orders[oid]=self.orders[oid]
            self.orders[oid].callback = cb
        else:
            self.pending_orders[oid]=API_Order(self, oid, o, 'client', cb)

        fields= ','.join(['%s=%s' %(i,v) for i,v in o.iteritems() if i[0].isupper()])

        acb = API_Callback(self, oid, 'order-ack', RTX_LocalCallback(self, self.order_submit_ack_callback), self.callback_timeout['ORDER'])
        cb = API_Callback(self, oid, 'order', RTX_LocalCallback(self, self.order_submit_callback), self.callback_timeout['ORDER'])
        self.cxn_get('ACCOUNT_GATEWAY', 'ORDER').poke('ORDERS', '*', '', fields, acb, cb)

    def order_submit_ack_callback(self, data):
        """called when order has been submitted with 'poke' and Ack has returned""" 
        self.output('order submission acknowleded: %s' % repr(data))

    def order_submit_callback(self, data):
        """called when order has been submitted with 'poke' and OnOtherAck has returned""" 
        self.output('order submitted: %s' % repr(data))

    def cancel_order(self, oid, callback):
        self.output('cancel_order %s' % oid)
        cb = API_Callback(self, oid, 'cancel_order', callback, self.callback_timeout['ORDER'])
        order = self.orders[oid] if oid in self.orders else None
        if order:
            if order.fields['status'] == 'Canceled':
                cb.complete({'status': 'Error', 'errorMsg': 'Already canceled.', 'id': oid})
            else:
                msg=OrderedDict({})
                #for fid in ['DISP_NAME', 'STYP', 'ORDER_TAG', 'EXIT_VEHICLE']:
                #    if fid in order.fields:
                #        msg[fid] = order.fields[fid]
                msg['TYPE']='UserSubmitCancel'
                msg['REFERS_TO_ID']=oid
                fields= ','.join(['%s=%s' %(i,v) for i,v in msg.iteritems()])
                self.cxn_get('ACCOUNT_GATEWAY', 'ORDER').poke('ORDERS', '*', '', fields, None, cb)
                self.cancel_callbacks.append(cb)
        else:
            cb.complete({'status': 'Error', 'errorMsg': 'Order not found', 'id': oid})

    def symbol_enable(self, symbol, client, callback):
        self.output('symbol_enable(%s,%s,%s)' % (symbol, client, callback))
        if not symbol in self.symbols.keys():
            cb = API_Callback(self, symbol, 'add-symbol', callback, self.callback_timeout['ADDSYMBOL'])
            API_Symbol(self, symbol, client, cb)
            self.add_symbol_callbacks.append(cb)
        else:
            self.symbols[symbol].add_client(client)
            API_Callback(self, symbol, 'add-symbol', callback).complete(True)
        self.output('symbol_enable: symbols=%s' % repr(self.symbols))

    def symbol_init(self, symbol):
        ret = not 'SYMBOL_ERROR' in symbol.rawdata.keys()
        if not ret:
            self.symbol_disable(symbol.symbol, list(symbol.clients)[0])
        symbol.callback.complete(ret)
        return ret

    def symbol_disable(self, symbol, client):
        self.output('symbol_disable(%s,%s)' % (symbol, client))
        self.output('self.symbols=%s' % repr(self.symbols))
        if symbol in self.symbols.keys():
            ts = self.symbols[symbol]
            ts.del_client(client)
            if not ts.clients:
                del(self.symbols[symbol])
            self.output('ret True: self.symbols=%s' % repr(self.symbols))
            return True
        self.output('ret False: self.symbols=%s' % repr(self.symbols))

    def update_connection_status(self, status):
        self.connection_status = status
        if status != self.last_connection_status:
            self.last_connection_status = status
            self.WriteAllClients('connection-status-changed: %s' % status)

    def request_accounts(self, callback):
        cb = API_Callback(self, 0, 'request-accounts', callback, self.callback_timeout['ACCOUNT'])
        if self.accounts:
            cb.complete(self.accounts)
        elif self.account_request_pending:
            self.account_request_callbacks.append(cb)
        else:
            self.output(
                'Error: request_accounts; no data, but no account_request_pending')
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
        self.cxn_get('ACCOUNT_GATEWAY', 'ORDER').request('ORDERS', '*', '', cb)
        self.execution_callbacks.append(cb)

    def request_account_data(self, account, fields, callback):
        cxn = self.cxn_get('ACCOUNT_GATEWAY', 'ORDER')
        cb = API_Callback(self, 0, 'account_data', callback, self.callback_timeout['ACCOUNT'])
        bank, branch, customer, deposit = account.split('.')[:4]
        tql_where = "BANK='%s',BRANCH='%s',CUSTOMER='%s',DEPOSIT='%s'" % (bank,branch,customer,deposit)
        if fields:
            fields = ','.join(fields)
        else:
            fields = '*'
        cxn.request('DEPOSIT', fields, tql_where, cb)
        self.accountdata_callbacks.append(cb)

    def request_global_cancel(self):
        self.rtx_request('ACCOUNT_GATEWAY', 'ORDER', 
                        'ORDERS', 'ORDER_ID,ORIGINAL_ORDER_ID,CURRENT_STATUS,TYPE', "CURRENT_STATUS={'LIVE','PENDING'}",
                        'global_cancel', self.handle_global_cancel, self.openorder_callbacks, self.callback_timeout['ORDER'])

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
        API_Callback(self, 0, 'query-bars-failed', callback).complete(None)
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
        print('barchart session_start=%s session_stop=%s' % (session_start, session_stop))
 
        # if start time is a negative integer, use it as an offset from the end time
        # limit start and end to the session start and stop times
        if str(bar_start).startswith('-'):
            offset = int(str(bar_start))
            bar_end = self.feed_now + datetime.timedelta(minutes=1)
            if bar_end.time() > session_stop.time():
                bar_end = datetime.datetime(bar_end.year, bar_end.month, bar_end.day, session_stop.hour, session_stop.minute, 0)
            if table=='DAILY':
                delta = [datetime.timedelta(days=offset), datetime.timedelta(weeks=offset), datetime.timedelta(days=offset*30)][interval]
            else:
                delta = datetime.timedelta(minutes=offset * interval)
            bar_start = bar_end + delta
            if bar_start.time() < session_start.time():
                bar_start = datetime.datetime(bar_start.year, bar_start.month, bar_start.day, session_start.hour, session_start.minute, 0)
            print('offset bar start: start=%s end=%s' % (repr(bar_start), repr(bar_end)))
        else:
            # implement defaults for bar_start, bar_end
            if bar_start=='.':
                bar_start = self.feed_now.date().isoformat()
            elif re.match('^\d\d\d\d-\d\d-\d\d \d\d:\d\d:\d\d$', bar_start):
                # bar_start provided with time; adjust timezone
                bar_start = self.unlocalize_time(datetime.datetime.strptime(bar_start, '%Y-%m-%d %H:%M:%S')).isoformat(' ')[:19]
            elif not re.match('^\d\d\d\d-\d\d-\d\d$', bar_start):
                return self._fail_query_bars('query_bars: bad parameter format bar_start=%s' % bar_start, callback) 
                
            if bar_end=='.':
                bar_end = bar_start[:10]
            elif re.match('^\d\d\d\d-\d\d-\d\d \d\d:\d\d:\d\d$', bar_end):
                bar_end = self.unlocalize_time(datetime.datetime.strptime(bar_end, '%Y-%m-%d %H:%M:%S')).isoformat(' ')[:19]
            elif not re.match('^\d\d\d\d-\d\d-\d\d$', bar_end):
                return self._fail_query_bars('query_bars: bad parameter format bar_end=%s' % bar_end, callback) 

            if len(bar_start) == 10:
                bar_start += session_start.time().strftime(' %H:%M:%S')

            if len(bar_end) == 10:
                bar_end += session_stop.time().strftime(' %H:%M:%S')

            print('+++ bar_start=%s bar_end=%s' % (repr(bar_start), repr(bar_end)))
            bar_start = datetime.datetime.strptime(bar_start, '%Y-%m-%d %H:%M:%S')
            bar_end = datetime.datetime.strptime(bar_end, '%Y-%m-%d %H:%M:%S')
   
        # limit bar_start and bar_end to stay within session start, stop
        if bar_start.time() < session_start.time() or table=='DAILY':
            bar_start = datetime.datetime(bar_start.year, bar_start.month, bar_start.day, session_start.hour, session_start.minute, 0)

        if bar_end.time() > session_stop.time() or table=='DAILY':
            bar_end = datetime.datetime(bar_end.year, bar_end.month, bar_end.day, session_stop.hour, session_stop.minute, 0)

        where = ','.join([
	    "DISP_NAME='%s'" % symbol,
            "BARINTERVAL=%d" % interval,
            "STARTDATE='%s'" % bar_start.strftime('%Y/%m/%d'),
            "CHART_STARTTIME='%s'" % bar_start.strftime('%H:%M'),
            "STOPDATE='%s'" % bar_end.strftime('%Y/%m/%d'),
            "CHART_STOPTIME='%s'" % bar_end.strftime('%H:%M'),
        ])

        print('barchart where=%s' % repr(where))

        cb = API_Callback(self, '%s;%s' % (table, where), 'barchart', callback, self.callback_timeout['BARCHART'])
        self.cxn_get('TA_SRV', BARCHART_TOPIC).request(table, BARCHART_FIELDS, where, cb)
        self.bardata_callbacks.append(cb)

    def format_barchart(self, rows):
        #pprint({'format_barchart': rows})
        bars = None 
        if type(rows) == list and len(rows)==1:
            row = rows[0]
            # DAILY bars have no time values, so spoof for the parser
            if row['TRDTIM_1']=='Error 17':
                symbol = self.symbols[row['DISP_NAME']]
                session_start = symbol.rawdata['STARTTIME']
                row['TRDTIM_1'] = [session_start for t in row['TRD_DATE']]
            types = {k:type(v) for k, v in row.iteritems()}
            print('types = %s' % repr(types))
            if types=={
                'DISP_NAME': unicode,
                'TRD_DATE': list,
                'TRDTIM_1': list,
                'OPEN_PRC': list,
                'HIGH_1': list,
                'LOW_1': list,
                'SETTLE': list,
                'ACVOL_1': list
            }:
                bars = [ self.format_barchart_date(row['TRD_DATE'][i], row['TRDTIM_1'][i]) + [row['OPEN_PRC'][i], row['HIGH_1'][i], row['LOW_1'][i], row['SETTLE'][i], row['ACVOL_1'][i]] for i in range(len(row['TRD_DATE'])) ]
        if not bars:
            self.error_handler(self, 'barchart data format failed: %s' % repr(rows))
        return bars

    def format_barchart_date(self, bdate, btime):
        bartime = datetime.datetime.strptime('%s %s' % (bdate, btime), '%Y-%m-%d %H:%M:%S')
        bartime = self.localize_time(bartime)
        return bartime.isoformat()[:19].split('T')

    def query_connection_status(self):
        return self.connection_status

    def set_order_route(self, route, callback):
        #print('set_order_route(%s, %s) type=%s %s' % (repr(route), repr(callback), type(route), (type(route) in [str, unicode])))
        if type(route) in [str, unicode]:
            if route.startswith('{'):
                route = json.loads(route)
	    elif route.startswith('"'):
                route = {json.loads(route): None}
            else:
                route = {route: None}
        if (type(route)==dict) and (len(route.keys()) == 1) and (type(route.keys()[0]) in [str, unicode]):
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
