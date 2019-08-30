txTrader - Twisted Trading API Controller 
=========================================

Overview - what is this thing, and what does it do?
---------------------------------------------------
- Cross-Platform securities trading API management engine   
- Encapsulates the interaction with the broker's API 
- Provides a trader's eye view of the interaction with the trading software API.    
- Manages connection maintenance and communication details of the order management / trade execution transaction.   
- Frees trading software from timing and architectural constraints imposed by the execution API.


Description
-----------
This system aims to present an interface to trading software comprised of objects, procedures, and events that directly represent trading activities.  Common API designs expose implementation details such as message packet parsing, message and field IDs, blocking, threading, and event handling mechanisms.  This design seems to represent the point of view of the trading software implementor. Another goal of txTrader is to decouple the application software from strict timing and sequencing requirements.  

This software implemements interfaces to the API for CQG's CQGNet application and Interactive Brokers' Trader Workstation.  The servers provide access to realtime market data, historical barcharts, order management, execution reports, and position data.

The gateway is built on the twisted python server architecture.  Each instance implements a TCP/IP ASCII line-delimited protocol as well as an XMLRPC interface.  Both services are password protected using a simple username/password pair from a static configuration file.

Common interface code is used to provide identical access to CQG and TWS.  Note that the contents of the returned objects may differ.  Many fieldnames are common to the two environments.

Status change events are available on the TCP/IP streaming service.  The data are JSON-formatted objects.


Dependencies
------------

TxTrader's server daemons depend on external libraries for each configured API:

 - Interactive Brokers
   - IbPy python wrappers for IB's java/C++ API
   - bootstrap script uses pinned fork at https://github.com/rstms/IbPy
   - https://interactivebrokers.github.io

 - CQG
   - server runs under Windows
   - uses win32com to access CQG's COM API
   - http://partners.cqg.com/api-resources

 - RealTick
   - uses RTGW Txtrader GateWay running under Linux
   - consult your RealTick customer service agent for API details
    

Server Configuration
--------------------
The `txtrader.tws` and/or `txtrader.cqg` servers run as a supervised process under daemontools

The service runs in its own directory under `/etc/service/`.

The service directory contains startup files:  `run`, `txtrader.tac`.

Configuration data are read from environment variables, set up using envdir from `/etc/txtrader`.

Runtime information and errors append to log files: `/var/log/<service_name>/current`.


Security 
--------
The Makefile will set up a user and group account named `txtrader`.  The configuration files are owned by root and readable by this group.  Group membership controls interaction with the configured API.  To allow a user account to interact with txTrader, add the account to the txtrader group.


Installation
------------
```
curl --location https://github.com/rstms/TxTrader/raw/master/bootstrap.sh | sudo sh
```
For the command line tool, add the current user to the 'txtrader' group:
```
sudo usermod -a -G txtrader USERNAME
```

JSONRPC Server
--------------
The server implements the following JSONRPC calls:

```
add_symbol('symbol')

        Request subscription to a symbol for price updates and order entry
        

cancel_order('id')
 
        Request cancellation of a pending order
        

del_symbol('symbol')

        Delete subscription to a symbol for price updates and order entry
        

gateway_logoff()
    
        Logoff from gateway
        

gateway_logon('username', 'password')
        
        logon to gateway
        

global_cancel()
  
        Request cancellation of all pending orders
        

limit_order('symbol', price, quantity) => {'field':, data, ...}

        Submit a limit order, returning dict containing new order fields (see market_order)
        

market_order('symbol', quantity) => {'field':, data, ...}

        Submit a market order, returning dict containing new order fields
        dict will include 'permid' field containing permanent order id string
        dict will include 'status' field containing latest order status string
        

query_accounts() => ['account_name', ...]

        Return array of account names
        

query_bars('symbol', bar_period, 'start', 'end')
              => ['Status: OK', [time, open, high, low, close, volume], ...]

        Return array containing status strings and lists of bar data if successful
        

query_executions() => {'exec_id': {'field': data, ...}, ...}

        Return dict keyed by execution id containing dicts of execution report data fields
        

query_order('id') => {'fieldname': data, ...}

        Return dict containing order status fields for given order id
        

query_orders() => {'order_id': {'field': data, ...}, ...}

        Return dict keyed by order id containing dicts of order data fields
        

query_positions() => {'account': {'fieldname': data, ...}, ...}
        
        Return dict keyed by account containing dicts of position data fields
        

query_symbol('symbol') => {'fieldname': data, ...}

        Return dict containing current data for given symbol

query_symbol_data('symbol') => {'fieldname': data, ...}

        Return dict containing rawdata for given symbol
        

query_symbols() => ['symbol', ...]

        Return the list of active symbols
        

set_account('account')

        Select current active trading account
        

shutdown() 

        Request server shutdown
        

status() => 'status string'

        return string describing current API connection status
        

stop_order('symbol', price, quantity) => {'field':, data, ...}

        Submit a stop order, returning dict containing new order fields (see market_order)
        

stoplimit_order('symbol', stop_price, limit_price, quantity) => {'field':, data, ...}

        Submit a stop-limit order, returning dict containing new order fields (see market_order)
        

system.listMethods [['array']]

        Return a list of the method names implemented by this server.
        

system.methodHelp [['string', 'string']]

        Return a documentation string describing the use of the given method.
        

system.methodSignature [['array', 'string'], ['string', 'string']]

        Return a list of type signatures.

        Each type signature is a list of the form [rtype, type1, type2, ...]
        where rtype is the return type and typeN is the type of the Nth
        argument. If no signature information is available, the empty
        string is returned.
        

uptime() => 'uptime string'

        Return string showing start time and elapsed time for current server instance
        
```

Environment Variables
---------------------

The default values for these configuration variables are copied from `etc/txtrader` to `/etc/txtrader` at installation.  They are
loaded into the environment with `envdir` by the service run script.

Variable			| Description
------------------------------- | --------------------------------------------------
TXTRADER_API_ACCOUNT            | default API account, override with `set_account`
TXTRADER_API_CLIENT_ID          | API credential; default to 0 (TWS Specific)
TXTRADER_API_HOST               | hostname for API TCP/IP connection
TXTRADER_API_PORT               | port for API TCP/IP connection
TXTRADER_API_ROUTE              | trade execution route (Realtick specific)
TXTRADER_CALLBACK_TIMEOUT       | default timeout for API status/response
TXTRADER_DAEMON_USER            | username (used by run script)
TXTRADER_ENABLE_SECONDS_TICK    | switch to control time tick update
TXTRADER_ENABLE_TICKER          | switch to control bid/ask/last updates
TXTRADER_HOST                   | hostname used by client for txTrader 
TXTRADER_HTTP_PORT              | port used by client for txTrader JSON over HTTP 
TXTRADER_LOG_API_MESSAGES       | switch API message i/o logging
TXTRADER_DEBUG_API_MESSAGES     | switch API message i/o hex dump
TXTRADER_LOG_CLIENT_MESSAGES    | switch client message output
TXTRADER_MODE                   | backend mode (tws, rtx, cqg)
TXTRADER_PASSWORD               | password for HTTP session
TXTRADER_SUPPRESS_ERROR_CODES   | list of error codes to ignore (TWS)
TXTRADER_TCP_PORT               | port used by client for txTrader ASCII output
TXTRADER_TEST_ACCOUNT		| account used for regression test
TXTRADER_TIME_OFFSET            | adjust clock for test system's 15-minute delayed data
TXTRADER_USERNAME               | username for HTTP session 
TXTRADER_VENV                   | virtualenv directory (used by run script, cli script)


Service
-------
txTrader is designed to run under [daemontools](http://cr.yp.to/daemontools.html)

The configuration files service/txtrader are the service template files.

An additional convention is added:  if a file named `disable` is present in the service directory
at startup time, the service prints "Disabled" to its log and sleeps for a minute before restarting.
