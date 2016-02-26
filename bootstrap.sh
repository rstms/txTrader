#!/bin/sh
[ -n "$IBPY_VERSION" ] || IBPY_VERSION=master
curl --location https://github.com/rstms/IbPy/tarball/$IBPY_VERSION | tar zxfv -
mv rstms-IbPy-* IbPy
cd IbPy
python setup.py sdist
cd
[ -n "$TXTRADER_VERSION" ] || TXTRADER_VERSION=master
curl --location -o- https://github.com/rstms/txTrader/tarball/$TXTRADER_VERSION | tar zxfv -
mv rstms-txTrader-* txTrader
cd txTrader
sudo make install
