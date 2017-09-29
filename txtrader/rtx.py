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
import simplejson as json
import time
from collections import OrderedDict
from hexdump import hexdump

from txtrader.config import Config

DEFAULT_CALLBACK_TIMEOUT = 5

# default RealTick orders to NYSE and Stock type
RTX_EXCHANGE='NYS'
RTX_STYPE=1

# allow disable of tick requests for testing

ENABLE_CXN_DEBUG = False

DISCONNECT_SECONDS = 15
SHUTDOWN_ON_DISCONNECT = True 
ADD_SYMBOL_TIMEOUT = 5
ACCOUNT_QUERY_TIMEOUT = 15
POSITION_QUERY_TIMEOUT = 10 

from twisted.python import log
from twisted.python.failure import Failure
from twisted.internet.protocol import Protocol, ReconnectingClientFactory
from twisted.protocols.basic import LineReceiver
from twisted.internet import reactor, defer
from twisted.internet.task import LoopingCall
from twisted.web import server
from socket import gethostname


class RtxClient(LineReceiver):
    def __init__(self, rtx):
        self.delimiter = '\n'
        self.rtx = rtx

    def connectionMade(self):
        self.rtx.gateway_connect(self)

    def lineReceived(self, data):
        self.rtx.gateway_receive(data)

class RtxClientFactory(ReconnectingClientFactory):
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

class API_Symbol():
    def __init__(self, api, symbol, client_id, init_callback):
        self.api = api
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
        self.close = 0.0
        self.rawdata = ''
        self.api.symbols[symbol] = self
        self.last_quote = ''
        self.output('API_Symbol %s %s created for client %s' %
                    (self, symbol, client_id))
        self.output('Adding %s to watchlist' % self.symbol)
        self.cxn = api.cxn_get('TA_SRV', 'LIVEQUOTE')
        cb = API_Callback(self.api, self.cxn.id, 'init_symbol', RTX_LocalCallback(self.api, self.init_handler), ADD_SYMBOL_TIMEOUT)
        self.cxn.request('LIVEQUOTE', '*', "DISP_NAME='%s'" % symbol, cb)

    def __str__(self):
        return 'API_Symbol(%s bid=%s bidsize=%d ask=%s asksize=%d last=%s size=%d volume=%d close=%s clients=%s' % (self.symbol, self.bid, self.bid_size, self.ask, self.ask_size, self.last, self.size, self.volume, self.close, self.clients)

    def __repr__(self):
        return str(self)

    def export(self):
        return {
            'symbol': self.symbol,
            'bid': self.bid,
            'bidsize': self.bid_size,
            'ask': self.ask,
            'asksize': self.ask_size,
            'last': self.last,
            'size': self.size,
            'volume': self.volume,
            'close': self.close,
            'fullname': self.fullname
        }

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
            # TODO: stop live updates of market data from RTX

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
        self.output('API_Symbol init: %s' % data)
        self.rawdata = data
        self.parse_fields(None, data[0])
        if self.api.symbol_init(self):
            self.cxn = self.api.cxn_get('TA_SRV', 'LIVEQUOTE')
            self.cxn.advise('LIVEQUOTE', 'TRDPRC_1,TRDVOL_1,BID,BIDSIZE,ASK,ASKSIZE,ACVOL_1',
                            "DISP_NAME='%s'" % self.symbol, self.parse_fields)

    def parse_fields(self, cxn, data):
        trade_flag = False
        quote_flag = False
        if 'TRDPRC_1' in data.keys():
            self.last = float(data['TRDPRC_1'])
            trade_flag = True
        if 'TRDVOL_1' in data.keys():
            self.size = int(data['TRDVOL_1'])
            trade_flag = True
        if 'ACVOL_1' in data.keys():
            self.volume = int(data['ACVOL_1'])
            trade_flag = True
        if 'BID' in data.keys():
            self.bid = float(data['BID'])
            quote_flag = True
        if 'BIDSIZE' in data.keys():
            self.bidsize = int(data['BIDSIZE'])
            quote_flag = True
        if 'ASK' in data.keys():
            self.ask = float(data['ASK'])
            quote_flag = True
        if 'ASKSIZE' in data.keys():
            self.asksize = int(data['ASKSIZE'])
            quote_flag = True
        if 'COMPANY_NAME' in data.keys():
            self.fullname = data['COMPANY_NAME']
        if 'HST_CLOSE' in data.keys():
            self.close = float(data['HST_CLOSE'])

        if self.api.enable_ticker:
            if quote_flag:
                self.update_quote()
            if trade_flag:
                self.update_trade()

    #def update_handler(self, data):
    #    self.output('API_Symbol update: %s' % data)
    #    self.rawdata = data

class API_Order():
    def __init__(self, api, oid, data, callback=None):
        self.api = api
        self.oid = oid
        self.fields = data
        self.callback = callback
        self.updates = {}

    def initial_update(self, data):
        self.update(data)
        if self.callback:
            self.callback.complete(self.render())
            self.callback = None

    def update(self, data):
        if 'status' in self.fields:
            oldstatus = json.dumps(self.fields)
        else:
            oldstatus = ''
        changes={} 
        for k,v in data.items():
            ov = self.fields.setdefault(k,None)
            self.fields[k]=v
            if v!=ov:
                changes[k]=v
        self.updates[time.time()]=changes
        if json.dumps(self.fields) != oldstatus:
            self.api.send_order_status(self)

    def render(self):
        # customize fields for standard txTrader order status 
        self.fields['permid']=self.fields['ORIGINAL_ORDER_ID']
        status = self.fields.setdefault('CURRENT_STATUS', 'UNDEFINED')
        otype = self.fields.setdefault('TYPE', 'Undefined')
        print('render: permid=%s CURRENT_STATUS=%s TYPE=%s' % (self.fields['permid'], status, otype))
        if status=='PENDING':
            self.fields['status'] = 'Submitted'
        elif status=='LIVE':
            self.fields['status'] = 'Pending'
        elif status=='COMPLETED':
            if otype in ['UserSubmitOrder', 'UserSubmitStagedOrder']:
                if not self.is_filled():
                    self.fields['status'] = 'Submitted'
            elif otype == 'UserSubmitCancel':
                self.fields['status'] = 'Cancelled'
            elif otype == 'UserSubmitChange':
                self.fields['status'] = 'Changed'
            elif otype == 'ExchangeAcceptOrder':
                self.fields['status'] = 'Accepted'
            elif otype == 'ClerkReject':
                self.fields['status'] = 'Error'
            elif otype == 'ExchangeTradeOrder':
                if self.is_filled():
                    self.fields['status']='Filled'
                    self.fields['filled'] =self.fields['VOLUME_TRADED']
                    self.fields['remaining']=0
                    self.fields['avgfillprice']=self.fields['AVG_PRICE']
                else:
                    self.api.error_handler(self.oid, 'exchangeTradeOrder but not is_filled: %s' % self.fields)
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

        return self.fields

    def is_filled(self):
        return bool(self.fields['CURRENT_STATUS']=='COMPLETED' and
            self.has_fill_type() and
            'VOLUME' in self.fields and
            'VOLUME_TRADED' in self.fields and 
            self.fields['VOLUME'] == self.fields['VOLUME_TRADED'])
 
    def has_fill_type(self):
        if self.fields['TYPE']=='ExchangeTradeOrder':
            return True
        for fields in self.updates.values():
            if 'TYPE' in fields and fields['TYPE']=='ExchangeTradeOrder':
                return True
        return False

class API_Callback():
    def __init__(self, api, id, label, callable, timeout=0):
        """callable is stored and used to return results later"""
        #api.output('API_Callback.__init__() %s' % self)
        self.api = api
        self.id = id
        self.label = label
        if not timeout:
            timeout = api.callback_timeout
        self.expire = time.time() + timeout
        self.callable = callable
        self.done = False
        self.data = None

    def complete(self, results):
        """complete callback by calling callable function with value of results"""
        if not self.done:
            ret = self.format_results(results)
            if self.callable.callback.__name__ == 'write':
                ret = '%s.%s: %s\n' % (self.api.channel, self.label, ret)
            #self.api.output('API_Callback.complete(%s)' % repr(ret))
            self.callable.callback(ret)
            self.callable = None
            self.done = True

        else:
            self.api.error_handler(self.id, 'callback: %s was already done! results=%s' % (self, results))

    def check_expire(self):
        #SElf.api.output('API_Callback.check_expire() %s' % self)
        if not self.done:
            if time.time() > self.expire:
                msg = 'error: callback expired: %s' % repr((self.id, self.label))
                self.api.WriteAllClients(msg)
                if self.callable.callback.__name__ == 'write':
                    self.callable.callback('%s.error: %s callback expired\n', (self.api.channel, self.label))
                else:
                    # special case for positions; timeout indicates empty positions 
                    if self.label == 'positions':
                        self.callable.callback(self.format_results([]))
                    else:
                        self.callable.errback(Failure(Exception(msg)))
                self.done = True

    def format_results(self, results):
        #print('format_results: label=%s results=%s' % (self.label, results))
        if self.label == 'account_data':
            results = results[0]
        elif self.label == 'positions':
            results = self.format_positions(results)
        elif self.label == 'orders':
            results = self.format_orders(results)
        elif self.label=='executions':
            results = self.format_executions(results)

        return json.dumps(results)

    def format_positions(self, rows):
        # Positions should return {'ACOUNT': {'SYMBOL': QUANTITY, ...}, ...}
        positions = {}
        [positions.setdefault(a, {}) for a in self.api.accounts]
        for pos in rows:
            account = self.api.make_account(pos)
            positions[account][pos['DISP_NAME']] = int(pos['LONGPOS']) - int(pos['SHORTPOS'])
        return positions

    def format_orders(self, rows):
        for row in rows:
            self.api.handle_order_response(row)
        results={}
        for k,v in self.api.orders.items():
            results[k]=v.fields
            results[k]['updates']=v.updates
        return results

    def format_executions(self, rows):
        for row in rows:
            self.api.handle_order_response(row)
        results={}
        for k,v in self.api.orders.items():
            if v.is_filled():
                results[k]=v.fields
                results[k]['updates']=v.updates
        return results

class RTX_Connection():
    def __init__(self, api, service, topic, enable_logging=False):
        self.api = api
        self.id = str(uuid1())
        self.service = service
        self.topic = topic
        self.key = '%s;%s' % (service, topic)
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

    def update_ready(self):
        self.ready = not(
            self.ack_pending or self.response_pending or self.status_pending or self.status_callback or self.update_callback or self.update_handler)
        #self.api.output('update_ready() %s %s' % (self.id, self.ready))
        if self.ready:
            self.api.cxn_activate(self)

    def receive(self, type, data):
        if type == 'ack':
            self.handle_ack(data)
        elif type == 'response':
            self.handle_response(data)
        elif type == 'status':
            self.handle_status(data)
        elif type == 'update':
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

    def handle_status(self, data):
        if self.log:
            self.api.output('Connection Status: %s %s' % (self, data))
        if self.status_pending and data['msg'] == self.status_pending:
            self.status_pending = None
            if data['status'] == '1':
                # special case for the first status ack of a new connection, may need to do on_connect_action
                if data['msg'] == 'OnInitAck':
                    self.connected = True
                    if self.on_connect_action:
                        self.ready = True
                        cmd, arg, exa, cba, exr, cbr, exs, cbs, cbu, uhr = self.on_connect_action
                        self.api.output('Sending on_connect_action: %s' % repr(self.on_connect_action))
                        self.send(cmd, arg, exa, cba, exr, cbr, exs, cbs, cbu, uhr)
                        self.on_connect_action = None

                if self.status_callback:
                    self.status_callback.complete(data)
                    self.status_callback = None
                    self.status_pending = None
            else:
                self.api.error_handler(self.id, 'Status Error: %s' % data)
        else:
            self.api.error_handler(self.id, 'Status Unexpected: %s' % data)

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

    def query(self, cmd, table, what, where, ex_ack=None, cb_ack=None, ex_response=None, cb_response=None, ex_status=None, cb_status=None, cb_update=None, update_handler=None):
        tql='%s;%s;%s' % (table, what, where)
        ret = self.send(cmd, tql, ex_ack, cb_ack, ex_response, cb_response, ex_status, cb_status, cb_update, update_handler)

    def request(self, table, what, where, callback):
        return self.query('request', table, what, where, 'REQUEST_OK', None, True, callback)

    def advise(self, table, what, where, handler):
        return self.query('advise', table, what, where, 'ADVISE_OK', None, None, None, 'OnOtherAck', None, None, handler)

    def adviserequest(self, table, what, where, callback, handler):
        return self.query('adviserequest', table, what, where, 'ADVISEREQUEST_OK', None, True, callback, 'OnOtherAck', None, None, handler)

    def unadvise(self, table, what, where, callback):
        return self.query('unadvise', table, what, where, 'UNADVISE_OK', None, None, None, 'OnOtherAck', callback)

    def poke(self, table, what, where, data, callback):
        return self.send('poke', '%s;%s;%s!%s' % (table, what, where, data), "POKE_OK", None, None, None, 'OnOtherAck', callback)

    def execute(self, command, callback):
        return self.send('execute', command, "EXECUTE_OK", callback)

    def terminate(self, code, callback):
        return self.send('terminate', str(code), "TERMINATE_OK", callback)

    def send(self, cmd, args, ex_ack=None, cb_ack=None, ex_response=None, cb_response=None, ex_status=None, cb_status=None, cb_update=None, update_handler=None):
        if self.ready:
            self.cmd = cmd
            if 'request' in cmd:
                self.response_rows = []
            ret = self.api.gateway_send('%s %s %s' % (cmd, self.id, args))
            self.ack_pending = ex_ack
            self.ack_callback = cb_ack
            self.response_pending = ex_response
            self.response_callback = cb_response
            self.status_pending = ex_status
            self.status_callback = cb_status
            self.update_callback = cb_update
            self.update_handler = update_handler
        else:
            if self.on_connect_action:
                self.api.error_handler(self.id, 'Failure: on_connect_action already exists: %s' % repr(self.on_connect_action))
                ret = False
            else:
                self.api.output('storing on_connect_action...%s' % self)
                self.on_connect_action = (cmd, args, ex_ack, cb_ack, ex_response, cb_response, ex_status, cb_status, cb_update, update_handler)
                ret = True
        return ret


class RTX_LocalCallback:
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


class RTX():
    def __init__(self):
        self.label = 'RTX Gateway'
        self.channel = 'rtx'
        self.id = 'RTX'
        self.output('RTX init')
        self.config = Config(self.channel)
        self.api_hostname = self.config.get('API_HOST')
        self.api_port = int(self.config.get('API_PORT'))
        self.current_route = self.config.get('API_ROUTE')
        self.username = self.config.get('USERNAME')
        self.password = self.config.get('PASSWORD')
        self.http_port = int(self.config.get('HTTP_PORT'))
        self.tcp_port = int(self.config.get('TCP_PORT'))
        self.enable_ticker = bool(int(self.config.get('ENABLE_TICKER')))
        self.enable_seconds_tick = bool(int(self.config.get('ENABLE_SECONDS_TICK')))
        self.log_api_messages = bool(int(self.config.get('LOG_API_MESSAGES')))
        self.debug_api_messages = bool(int(self.config.get('DEBUG_API_MESSAGES')))
        self.log_client_messages = bool(int(self.config.get('LOG_CLIENT_MESSAGES')))
        self.callback_timeout = int(self.config.get('CALLBACK_TIMEOUT'))
        if not self.callback_timeout:
            self.callback_timeout = DEFAULT_CALLBACK_TIMEOUT
        self.output('callback_timeout=%d' % self.callback_timeout)
        self.current_account = ''
        self.clients = set([])
        self.orders = {}
        self.pending_orders = {}
        self.openorder_callbacks = []
        self.accounts = None
        self.account_data = {}
        self.pending_account_data_requests = set([])
        self.positions = {}
        self.position_callbacks = []
        self.executions = {}
        self.execution_callbacks = []
        self.bardata_callbacks = []
        self.cancel_callbacks = []
        self.order_callbacks = []
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
        self.primary_exchange_map = {}
        self.gateway_sender = None
        self.active_cxn = {}
        self.idle_cxn = {}
        self.cx_time = None
        self.seconds_disconnected = 0
        self.repeater = LoopingCall(self.EverySecond)
        self.repeater.start(1)
        reactor.connectTCP(self.api_hostname, self.api_port, RtxClientFactory(self))

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
            self.gateway_sender('%s\n' % msg)

    def gateway_receive(self, msg):
        """handle input from rtgw """

        if self.debug_api_messages:
            self.output('--RX[%d]-->' % (len(msg)))
            hexdump(msg)

        o = json.loads(msg)
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
                         'accounts', self.handle_accounts, self.accountdata_callbacks, ACCOUNT_QUERY_TIMEOUT)

        self.cxn_get('ACCOUNT_GATEWAY', 'ORDER').advise('ORDERS', '*', '', self.handle_order_update)
        
        self.rtx_request('ACCOUNT_GATEWAY', 'ORDER', 'ORDERS', '*', '',
                        'orders', self.handle_initial_orders_response, self.openorder_callbacks)

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
        for cblist in [self.timer_callbacks, self.position_callbacks, self.openorder_callbacks, self.execution_callbacks, self.bardata_callbacks, self.order_callbacks, self.cancel_callbacks, self.add_symbol_callbacks, self.accountdata_callbacks, self.set_account_callbacks, self.account_request_callbacks]:
            dlist = []
            for cb in cblist:
                cb.check_expire()
                if cb.done:
                    dlist.append(cb)
            # delete any callbacks that are done
            for cb in dlist:
                cblist.remove(cb)

    def handle_order_update(self, cxn, msg):
        return self.handle_order_response(msg)

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
                o = API_Order(self, oid, {})
                self.orders[oid]=o
                o.update(msg)
        else:
            self.error_handler(self.id, 'handle_order_update: ORIGINAL_ORDER_ID not found in %s' % repr(msg))

    def send_order_status(self, order):
        o = order.render()
        self.WriteAllClients('order.%s: %s' % (order.fields['permid'], json.dumps(o)))

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
            self.error_handler(self.id, 'handle_accounts: unexpected null input')

    def set_account(self, account_name, callback):
        cb = API_Callback(self, account_name, 'set-account', callback)
        if self.accounts:
            self.process_set_account(account_name, cb)
        elif self.account_request_pending:
            self.set_account_callbacks.append(cb)
        else:
            self.error_handler(self.id, 'set_account; no data, but no account_request_pending')
            cb.complete(None)

    def process_set_account(self, account_name, callback):
        if account_name in self.accounts:
            self.current_account = account_name
            msg = 'current account set to %s' % account_name
            self.output(msg)
            ret = True
        else:
            msg = 'account %s not found' % account_name
            self.error_handler(self.id, 'set_account(): %s' % msg)
            ret = False
        self.WriteAllClients('current-account: %s' % self.current_account)
        if callback:
            callback.complete(ret)
        else:
            return ret

    def rtx_request(self, service, topic, table, what, where, label, handler, cb_list, timeout=0):
        cxn = self.cxn_get(service, topic)
        cb = API_Callback(self, cxn.id, label, RTX_LocalCallback(self, handler), timeout)
        cxn.request(table, what, where, cb)
        cb_list.append(cb)

    def EverySecond(self):
        if self.connected:
            if self.enable_seconds_tick:
                self.rtx_request('TA_SRV', 'LIVEQUOTE', 'LIVEQUOTE', 'DISP_NAME,TRDTIM_1,TRD_DATE',
                                 "DISP_NAME='$TIME'", 'tick', self.handle_time, self.timer_callbacks, 5)
        else:
            self.seconds_disconnected += 1
            if self.seconds_disconnected > DISCONNECT_SECONDS:
                if SHUTDOWN_ON_DISCONNECT:
                    self.output('Realtick Gateway is disconnected; forcing shutdown')
                    reactor.stop()

        self.CheckPendingResults()

    def WriteAllClients(self, msg):
        if self.log_client_messages:
            self.output('WriteAllClients: %s.%s' % (self.channel, msg))
        msg = str('%s.%s\n' % (self.channel, msg))
        for c in self.clients:
            c.transport.write(msg)

    def error_handler(self, id, msg):
        """report error messages"""
        self.output('ERROR: %s %s' % (id, msg))
        self.WriteAllClients('error: %s %s' % (id, msg))

    def handle_time(self, rows):
        rows = json.loads(rows)
        if rows:
            field = rows[0]['TRDTIM_1']
            if field.lower().startswith('error'):
                self.error_handler(self.id, 'handle_time: time field %s' % field)
            else:
                hour, minute = [int(i) for i in field.split(':')[0:2]]
                if minute != self.last_minute:
                    self.last_minute = minute
                    self.WriteAllClients('time: %s %02d:%02d:00' % (rows[0]['TRD_DATE'], hour, minute))
        else:
            self.error_handler(self.id, 'handle_time: unexpected null input')

    def connect(self):
        self.update_connection_status('Connecting')
        self.output('Awaiting startup response from RTX gateway at %s:%d...' % (self.api_hostname, self.api_port))

    def market_order(self, symbol, quantity, callback):
        return self.submit_order('market', 0, 0, symbol, int(quantity), callback)

    def limit_order(self, symbol, limit_price, quantity, callback):
        return self.submit_order('limit', float(limit_price), 0, symbol, int(quantity), callback)

    def stop_order(self, symbol, stop_price, quantity, callback):
        return self.submit_order('stop', 0, float(stop_price), symbol, int(quantity), callback)

    def stoplimit_order(self, symbol, stop_price, limit_price, quantity, callback):
        return self.submit_order('stoplimit', float(limit_price), float(stop_price), symbol, int(quantity), callback)

    def stage_market_order(self, tag, symbol, quantity, callback):
        return self.submit_order('market', 0, 0, symbol, int(quantity), callback, staged=tag)

    def execute_staged_market_order(self, oid, callback):
        if oid in self.orders:
            o = self.orders[oid]
            symbol = o.fields['DISP_NAME']
            quantity = int(o.fields['VOLUME'])
            if o.fields['BUYORSELL'] != 'Buy':
                quantity *= -1
            self.submit_order('market', 0, 0, symbol, quantity, callback, staged=None, oid=oid)
        else:
            ret = {oid: {'status:': 'Undefined'}}
            API_Callback(self, 0, 'execute_staged_market_order', callback).complete(ret)

    def create_order_id(self):
        return str(uuid1())

    def submit_order(self, order_type, price, stop_price, symbol, quantity, callback, staged=None, oid=None):

        o=OrderedDict({})
        bank, branch, customer, deposit = self.current_account.split('.')[:4]
        o['BANK']=bank
        o['BRANCH']=branch
        o['CUSTOMER']=customer
        o['DEPOSIT']=deposit

        o['BUYORSELL']='Buy' if quantity > 0 else 'Sell' # Buy Sell SellShort
        o['GOOD_UNTIL']='DAY' # DAY or YYMMDDHHMMSS
        o['EXIT_VEHICLE']=self.current_route

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
            
        o['TYPE']='UserSubmit%s%s' % (staging, submission)

        # create callback to return to client after initial order update
        cb = API_Callback(self, oid, 'order', callback)
        self.order_callbacks.append(cb)
        if oid in self.orders:
            self.pending_orders[oid]=self.orders[oid]
            self.orders[oid].callback = cb
        else:
            self.pending_orders[oid]=API_Order(self, oid, o, cb)

        fields= ','.join(['%s=%s' %(i,v) for i,v in o.iteritems()])

        cb = API_Callback(self, oid, 'order', RTX_LocalCallback(self, self.order_submit_callback))
        self.cxn_get('ACCOUNT_GATEWAY', 'ORDER').poke('ORDERS', '*', '', fields, cb)

    def order_submit_callback(self, data):
        """called when order has been submitted with 'poke' and OnOtherAck has returned""" 
        self.output('order submitted: %s' % repr(data))

    def cancel_order(self, oid, callback):
        self.output('cancel_order %s' % oid)
        cb = API_Callback(self, oid, 'cancel_order', callback)
        order = self.orders[oid] if oid in self.orders else None
        if order:
            if order.fields['status'] == 'Canceled':
                cb.complete({'status': 'Error', 'errorMsg': 'Already canceled.', 'id': oid})
            else:
                msg=OrderedDict({})
                msg['TYPE']='UserCancelOrder'
                msg['REFERS_TO_ID']=oid
                fields= ','.join(['%s=%s' %(i,v) for i,v in msg.iteritems()])
                self.cxn_get('ACCOUNT_GATEWAY', 'ORDER').poke('ORDERS', '*', '', fields, cb)
                self.cancel_callbacks.append(cb)
        else:
            cb.complete({'status': 'Error', 'errorMsg': 'Order not found', 'id': oid})

    def symbol_enable(self, symbol, client, callback):
        self.output('symbol_enable(%s,%s,%s)' % (symbol, client, callback))
        if not symbol in self.symbols.keys():
            cb = API_Callback(self, symbol, 'add-symbol', callback)
            symbol = API_Symbol(self, symbol, client, cb)
            self.add_symbol_callbacks.append(cb)
        else:
            self.symbols[symbol].add_client(client)
            API_Callback(self, symbol, 'add-symbol', callback).complete(True)
        self.output('symbol_enable: symbols=%s' % repr(self.symbols))

    def symbol_init(self, symbol):
        ret = not 'SYMBOL_ERROR' in symbol.rawdata[0].keys()
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
        cb = API_Callback(self, 0, 'request-accounts', callback)
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
        cb = API_Callback(self, 0, 'positions', callback, POSITION_QUERY_TIMEOUT)
        cxn.request('POSITION', '*', '', cb)
        self.position_callbacks.append(cb)

    def request_orders(self, callback):
        cxn = self.cxn_get('ACCOUNT_GATEWAY', 'ORDER')
        cb = API_Callback(self, 0, 'orders', callback)
        #cxn.request('ORDERS', '*', "CURRENT_STATUS={'LIVE','PENDING'}", cb)
        cxn.request('ORDERS', '*', '', cb)
        self.openorder_callbacks.append(cb)

    def request_order(self, oid, callback):
        if oid in self.orders:
            ret = self.orders[oid].render()
        else:
            ret = {oid: {'status:': 'Undefined'}}
        API_Callback(self, 0, 'order_request', callback).complete(ret)

    def request_executions(self, callback):
        cb = API_Callback(self, 0, 'executions', callback)
        self.cxn_get('ACCOUNT_GATEWAY', 'ORDER').request('ORDERS', '*', '', cb)
        self.execution_callbacks.append(cb)

    def request_account_data(self, account, fields, callback):
        cxn = self.cxn_get('ACCOUNT_GATEWAY', 'ORDER')
        cb = API_Callback(self, 0, 'account_data', callback)
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
                        'global_cancel', self.handle_global_cancel, self.openorder_callbacks)

    def handle_global_cancel(self, rows):
        rows = json.loads(rows)
        for row in rows:
            if row['CURRENT_STATUS'] in ['LIVE', 'PENDING']:
                self.cancel_order(row['ORIGINAL_ORDER_ID'], RTX_LocalCallback(self, self.global_cancel_callback))

    def global_cancel_callback(self, data):
        data = json.loads(data)
        self.output('global cancel: %s' % repr(data))

    def query_bars(self, symbol, period, bar_start, bar_end, callback):
        self.error_handler(self.id, 'ERROR: query_bars unimplemented')
        return None

    def handle_historical_data(self, msg):
        for cb in self.bardata_callbacks:
            if cb.id == msg.reqId:
                if not cb.data:
                    cb.data = []
                if msg.date.startswith('finished'):
                    cb.complete(['OK', cb.data])
                else:
                    cb.data.append(dict(msg.items()))
        # self.output('historical_data: %s' % msg) #repr((id, start_date, bar_open, bar_high, bar_low, bar_close, bar_volume, count, WAP, hasGaps)))

    def query_connection_status(self):
        return self.connection_status
