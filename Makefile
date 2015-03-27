# txTrader Makefile

default: 
	@echo "Nothing to do"

clean:
	@echo "cleaning up"
	rm -f txtrader/*.pyc
	rm -rf build

build:
	@echo "Nothing to do"

config:
	@echo -n "Enter daemon user:";\
        read _user;\
        echo $$_user>service/env/TXTRADER_DAEMON_USER
	pip install egenix-mx-base


install:
	python bumpbuild.py
	python setup.py install
	cp bin/txtrader /usr/local/bin
	mkdir -p /var/svc.d/txtrader
	cp -r service/* /var/svc.d/txtrader
	update-service --add /var/svc.d/txtrader

uninstall:
	svc -d /etc/service/txtrader
	svc -d /etc/service/txtrader/log
	update-service --remove /var/svc.d/txtrader
	rm -rf /var/svc.d/txtrader
	cat files.txt | xargs rm -f
	rm -f /usr/local/bin/txtrader

dist:
	python setup.py sdist

TESTS := $(wildcard txtrader/test-*.py)

test: $(TESTS)
	@echo "Testing..."
	cd txtrader; envdir ../service/env py.test -vvx $(notdir $^)
