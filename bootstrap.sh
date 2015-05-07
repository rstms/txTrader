#!/bin/sh
#aptitude -y update
#aptitude -y install make python-twisted-web python-egenix-mx-base-dev python-egenix-mxdatetime daemontools-run ucspi-tcp
curl --location https://github.com/rstms/IbPy/tarball/master | tar zxfv -
mv rstms-IbPy-* IbPy
cd IbPy
python setup.py install
cd
curl --location -o- https://github.com/rstms/txTrader/tarball/master | tar zxfv -
mv rstms-txTrader-* txTrader
cd txTrader
make config
make install
