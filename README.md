txTrader - Twisted Trading API Controller 
=========================================

txTrader aims to eliminate the complexity of managing and interacting with multiple trading system APIs, presenting a native python interface.


Features
--------
- Cross-Platform securities trading API management engine   
- Provides a trader's eye view of the interaction with the trading system API.    
- Decouples business logic from low-level implementation details of interaction with the broker's API 
- Maintains internal data structures used to verify each step of the order management / trade execution transaction.   
- Supports fault-tolerance by maintaining a continuous connection with the API in the event of application failure.
- Frees trading software design from timing and architectural constraints imposed by the API implementation.
- Built on the mature and reliable [twisted](https://twistedmatrix.com/trac/) python networking engine.


Description
-----------
This system aims to present an interface to trading software composed of objects, procedures, and events that fit naturally into the design of an automated trading system.  Common trading system APIs often expose implementation details such as message packet parsing, message and field IDs.  They often have specific OS and development environment requirements.  Their use commonly requires the client application to support advanced programming techniques like blocking, threading, and event handling mechanisms.  This design seems to represent the point of view of the trading software implementer.  A goal of txTrader is to decouple the application software from strict timing and sequencing requirements.

This software implements interfaces to the API for CQG's CQGNet application and Interactive Brokers' Trader Workstation.  A version has been implemented for the Realtick API, but has a dependency on a closed-source gateway.  The system provides access to real-time market data, historical pricing, bar charts, order management, execution reports, and position data.

The gateway is built on the [twisted](https://twistedmatrix.com/trac/) python networking engine.  Clients can establish a long-lived TCP/IP streaming data connection using the [Netstring protocol](https://en.wikipedia.org/wiki/Netstring), and/or utilize a set of JSON-RPC functions.  Both services are password protected using basic authentication and a password handshake.   *Support for TLS connections with server and client certificates is planned.*

Common interface code is used to provide a normalized interface to the managed API.  While the contents of the returned objects may differ, many fields are common to the supported environments.

Status change events are available on the TCP/IP streaming service.  The data are JSON formatted objects.

Client Access
-------------

The [`txtrader-client`](https://github.com/rstms/txtrader-client) module exposes the server functions to a client program as local python callables.
The [`txtrader-monitor`](https://github.com/rstms/txtrader-monitor) module is used to receive asynchronous events from the TCP channel.  The object is configured by passing a dict with channel names and python functions to be called when data of the desired type is received.

See the client access projects for usage examples.


Dependencies
------------

TxTrader's server daemons depend on external libraries for each configured API:

 - Interactive Brokers
   - IbPy python wrappers for IB's java/C++ API
   - bootstrap script uses pinned fork at https://github.com/rstms/IbPy
   - https://interactivebrokers.github.io
   - runs using IB's API gateway in a docker container, or connected to the stand-alone version of the TWS java application


 - CQG
   - server runs on Windows
   - uses win32com to access CQG's COM API
   - http://partners.cqg.com/api-resources


 - RealTick
   - uses RTGW Txtrader GateWay running on Linux
   - Contact [the author](mailto:mkrueger@rstms.net) or your RealTick customer service agent for API details
    

Installation
------------
The fastest way to get started is to use [PyPI](https://pypi.org/search/?q=txtrader)
```
pip install txtrader txtrader-client txtrader-monitor
```

Run as a local daemon process
-----------------------------
```
txtraderd &
```

Run in a Docker container
---------------------------
```
docker start rstms/txtrader:latest
```

Configuration
-------------
At startup of a local process or as a docker container, environment variables are read to set configuration. Each variable has a
default value that will be used if it is not present.

To read configuration from a file, use a tool like envdir or cfgdir or a bash script may be used to set the desired variables.

Variable			| Description
------------------------------- | --------------------------------------------------
TXTRADER_USERNAME               | txtrader_user    | username for HTTP basic auth
TXTRADER_PASSWORD               | txtrader_pass    | password for HTTP basic auth
TXTRADER_HTTP_PORT              | 50080            | listen port used for JSON over HTTP server
TXTRADER_TCP_PORT               | 50090            | listen port used for streaming update server
TXTRADER_DAEMON_REACTOR		| poll             | txtraderd --reactor option (see twistd documentaion)
TXTRADER_DAEMON_LOGFILE		| -                | txtraderd --logfile option
TXTRADER_MODE                   | rtx              | select API (tws, rtx, cqg)
TXTRADER_DAEMON_PIDFILE		| ''               | txtraderd --pidfile option
TXTRADER_API_HOST               | localhost        | hostname for API connection
TXTRADER_API_PORT               | 51070            | port for API connection
TXTRADER_API_ACCOUNT            | api_account      | default API account
TXTRADER_API_TIMEZONE           | America/New_York | timezone used for naive time values in API data 
TXTRADER_API_ROUTE              | DEMO             | trade execution route (Realtick specific)
TXTRADER_API_CLIENT_ID          | 0                | API credential; (TWS Specific) 
TXTRADER_ENABLE_TICKER          | 0                | control bid/ask/last updates
TXTRADER_ENABLE_HIGH_LOW        | 1                | include daily high/low in query_symbol response
TXTRADER_ENABLE_BARCHART        | 1                | enable barchart queries
TXTRADER_ENABLE_SYMBOL_BARCHART | 0                | include intraday minute bars in query_symbol response
TXTRADER_ENABLE_SECONDS_TICK    | 1                | update time every second per the API clock
TXTRADER_ENABLE_EXCEPTION_HALT  | 0                | shutdown on runtime exceptions
TXTRADER_LOG_API_MESSAGES       | 0                | output API message text
TXTRADER_DEBUG_API_MESSAGES     | 0                | output API message hex dump
TXTRADER_LOG_CLIENT_MESSAGES    | 0                | output client message text
TXTRADER_LOG_HTTP_REQUESTS      | 1                | output HTTP GET/POST requests
TXTRADER_LOG_HTTP_RESPONSES     | 0                | output HTTP responses
TXTRADER_LOG_ORDER_UPDATES      | 0                | output order status update text
TXTRADER_TIME_OFFSET            | 0                | adjust clock for test system 15-minute delayed data
TXTRADER_SUPPRESS_ERROR_CODES   | 2100             | list of error codes to ignore (TWS specific)
TXTRADER_TIMEOUT_DEFAULT        | 15               | API timeout default
TXTRADER_TIMEOUT_ACCOUNT        | 15               | API timeout for query_account
TXTRADER_TIMEOUT_ADDSYMBOL      | 15               | API timeout for add_symbol
TXTRADER_TIMEOUT_BARCHART       | 10               | API timeout for query_bars
TXTRADER_TIMEOUT_ORDER          | 300              | API timeout for query_order
TXTRADER_TIMEOUT_ORDERSTATUS    | 3600             | API timeout for query_orders (all order data)
TXTRADER_TIMEOUT_POSITION       | 20               | API timeout for query_position
TXTRADER_TIMEOUT_TIMER          | 10               | API timeout for internal timer tick request
TXTRADER_ENABLE_AUTO_RESET      | 1                | timed automatic shutdown if enabled
TXTRADER_LOCAL_RESET_TIME       | "05:00"          | time for automatic shutdown in HH:MM format (local system time)



Security
--------
This version of the sofware is designed to be used on private internal infrastructure.   It is *NOT* intended to be exposed to the public Internet. 
TxTrader currently doesn't implement HTTPS and the password mechanism is rudimentary.  It is strongly recommended that access control be implemented at the network level.

Security mechanisms used in existing deployments include:
 - virtual machine private networking
 - local private network addressing
 - VPN
 - docker container networking
 - ssh port forwarding
 - firewall rules

Contact the author for additional info: mkrueger@rstms.net



JSONRPC Server
--------------
The server implements the following JSONRPC calls:

```

TxTrader Securities Trading API Controller 1.14.25 2020-08-10 02:23:00

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
        
get_order_route() => {'route_name', None | {parameter_name: parameter_value, ...}}

        Return current order route as a dict
        
global_cancel()

        Request cancellation of all pending orders
        
help() => {'command': 'command(parameters) => return', ...}

        Return dict containing brief documentation for each command
        
limit_order('account', 'route', 'symbol', price, quantity) => {'field':, data, ...}

        Submit a limit order, returning dict containing new order fields
        
market_order('account', 'route', 'symbol', quantity) => {'field':, data, ...}

        Submit a market order, returning dict containing new order fields
        
query_account(account, fields) => {'key': (value, currency), ...}

        Query account data for account. fields is list of fields to select; None=all fields
        
query_accounts() => ['account_name', ...]

        Return array of account names
        
query_bars('symbol', bar_period, 'start', 'end')
              => ['Status: OK', [time, open, high, low, close, volume], ...]

        Return array containing status strings and lists of bar data if successful
        
query_execution('id') => {'fieldname': data, ...}

        Return dict containing execution report data fields
        
query_executions() => {'exec_id': {'field': data, ...}, ...}

        Return dict keyed by execution id containing dicts of execution report data fields
        
query_order('id') => {'fieldname': data, ...}

        Return dict containing order/ticket status fields for given order id
        
query_executions() => {'exec_id': {'field': data, ...}, ...}

        Return dict keyed by execution id containing dicts of execution report data fields given order_id
        
query_orders() => {'order_id': {'field': data, ...}, ...}

        Return dict keyed by order id containing dicts of order data fields
        
query_positions() => {'account': {'fieldname': data, ...}, ...}

        Return dict keyed by account containing dicts of position data fields
        
query_symbol('symbol') => {'fieldname': data, ...}

        Return dict containing current data for given symbol
        
query_symbol_bars('symbol') => [[barchart data], ...]

        Return array of current live bar data for given symbol
        
query_symbol_data('symbol') => {'fieldname': data, ...}

        Return dict containing rawdata for given symbol
        
query_symbols() => ['symbol', ...]

        Return the list of active symbols
        
query_tickets() => {'order_id': {'field': data, ...}, ...}

        Return dict keyed by order id containing dicts of staged order ticket data fields
        
set_account('account')

        Select current active trading account.
        
set_order_route(route) => True if success, else False

        Set order route data given route {'route_name': {parameter: value, ...} (JSON string will be parsed into a route dict)}
        
set_primary_exchange(symbol, exchange)

        Set primary exchange for symbol (default is SMART), delete mapping if exchange is None.
        
shutdown(message) 

        Request server shutdown
        
stage_market_order('tag', 'account', 'route', 'symbol', quantity) => {'fieldname': data, ...}

        Submit a staged market order (displays as staged in GUI, requiring manual aproval), returning dict containing new order fields
        
status() => 'status string'

        return string describing current API connection status
        
stop_order('account', 'route', 'symbol', price, quantity) => {'field':, data, ...}

        Submit a stop order, returning dict containing new order fields
        
stoplimit_order('account', 'route', 'symbol', stop_price, limit_price, quantity) => {'field':, data, ...}

        Submit a stop-limit order, returning dict containing new order fields
        
time() => 'time string'

        Return formatted timestamp string (YYYY-MM-DD HH:MM:SS) matching latest datafeed time update
        
uptime() => 'uptime string'

        Return string showing start time and elapsed time for current server instance
        
version() => 'version string'

        Return string containing release version of current server instance
        
```
