#!/bin/sh
aptitude install python-pip python-twisted-web python-egenix-mx-base-dev daemontools-run ucspi-tcp
curl --location -o- https://github.com/rstms/txTrader/tarball/master | tar zxfv -
cd rstms-txTrader-*
make configure
make install
