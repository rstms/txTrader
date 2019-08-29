#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
  monitor.py
  ----------

  TxTrader Monitor class - Instantiate in client to receive event notifications.

  Copyright (c) 2015 Reliance Systems Inc. <mkrueger@rstms.net>
  Licensed under the MIT license.  See LICENSE for details.

"""


import time
from twisted.internet import reactor, protocol, task, error
from twisted.protocols.basic import NetstringReceiver

class Monitor(object):
    def __init__(self, host='localhost', port=50090, user=None, password=None, callbacks=None):
        """Initialize Monitor:
          connection parameters: host, port, user, password, 
          callbacks: {'name':function ...}  
            where name is one of ['status', 'error', 'time', 'order', 'execution', 'quote', 'trade', 'tick', 'shutdown']
            and function(data) is the callback that will receive event data
            callbacks must return True to continue monitor.run() loop
        """
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.shutdown_pending = False
        self.channel = ''
        self.callback_types = ['status', 'error', 'time', 'order', 'execution', 'quote', 'trade', 'tick', 'shutdown']
        self.flags = 'noquotes notrades'
        self.connection = None

        if callbacks:
            self.callbacks = callbacks
        else:
            self.callbacks = {}
            for cb_type in self.callback_types:
                self.set_callback(cb_type, self._cb_print)

    	reactor.addSystemEventTrigger('before','shutdown', self.shutdown_event)

    def shutdown_event(self):
        self._callback('shutdown', 'reactor shutdown detected')
        self.shutdown_pending = True
        if self.connection: 
            self.connection.disconnect()

    def listen(self, _reactor):
        f = StatusClientFactory(self)
        self.connection = reactor.connectTCP(self.host, self.port, f)

    def set_callback(self, cb_type, cb_func):
        """Set a callback function for a message type."""
        self.callbacks[cb_type] = cb_func

    def set_tick_interval(self, interval_seconds):
        l = task.LoopingCall(self.ticker)
        l.start(interval_seconds)

    def ticker(self):
        self._callback('tick', time.time())

    def delete_callback(self, cb_type):
        """Delete a callback function for a message type."""
        if cb_type in self.callbacks.keys():
            delete(self.callbacks[cb_type])

    def _callback(self, cb_type, cb_data):
        if not self.shutdown_pending: 
            if cb_type in self.callbacks.keys():
                if not self.callbacks[cb_type](cb_type, cb_data):
                    reactor.callFromThread(reactor.stop)

    def _cb_print(self, label, msg):
        print('%s: %s' % (label, repr(msg)))
        return True

    def run(self):
        """React to gateway events, returning data via callback functions."""
        self.listen(reactor)
        reactor.run()


class StatusClient(NetstringReceiver):

    def __init__(self):
        self.MAX_LENGTH = 0x1000000
        self.channel = ''
        self.message_types = []
        self.channel_map = {}
        self.last_account = ''

    def connectionMade(self):
        pass

    def stringReceived(self, data):
        if data.startswith('.'):
            self.factory.rx._callback('status', data)
            if data.startswith('.connected'):
                self.sendString('auth %s %s %s' % (self.factory.rx.user, self.factory.rx.password, self.factory.rx.flags))
            elif data.startswith('.Authorized'):
                dummy, self.channel = data.split()[:2]
                # setup channel map now that we have the channel name
                self.channel_map = {
                    '%s.time: ' % self.channel: 'time',
                    '%s.error:' % self.channel: 'error',
                    '%s.order.' % self.channel: 'order',
                    '%s.ticket.' % self.channel: 'ticket',
                    '%s.open-order.' % self.channel: 'order',
                    '%s.execution.' % self.channel: 'execution',
                    '%s.quote.' % self.channel: 'quote',
                    '%s.trade.' % self.channel: 'trade'}
                self.account_channel = '%s.current-account' % self.channel
        else:
            for cmap in self.channel_map.keys():
                if data.startswith(cmap):
                    return self.factory.rx._callback(self.channel_map[cmap], data[len(cmap):])
            # only return current_account message if different from last one
            if data.startswith(self.account_channel):
                if self.last_account == data:
                    return
                else:
                    self.last_account = data
            self.factory.rx._callback('status', data)

    def connectionLost(self, reason):
        pass

class StatusClientFactory(protocol.ClientFactory):
    protocol = StatusClient

    def __init__(self, receiver):
        self.rx = receiver

    def clientConnectionFailed(self, connector, reason):
        self.rx._callback('error', 'connection %s failed, reason=%s' % (connector, reason))
        if reactor.running:
            try: 
                reactor.stop()
            except error.ReactorNotRunning:
		pass

    def clientConnectionLost(self, connector, reason):
        self.rx._callback('error', 'connection %s lost, reason=%s' % (connector, reason))
        if reactor.running:
            try:
                reactor.stop()
            except error.ReactorNotRunning:
		pass


if __name__ == '__main__':

    _USER = 'txtrader_user'
    _PASS = 'change_this_password'
    rx = Monitor(user=_USER, password=_PASS)
    rx.run()
