#!/bin/sh
[ -n "$TXTRADER_VERSION" ] || TXTRADER_VERSION=master
[ -n "$MODE" ] || MODE=rtx
curl --location -o- https://github.com/rstms/txTrader/tarball/$TXTRADER_VERSION | tar zxfv -
mv rstms-txTrader-* txTrader
cd txTrader
make config && make build && make venv && make install
