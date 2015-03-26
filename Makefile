# txTrader Makefile

default: 
	@echo "Nothing to do"

clean:
	@echo "cleaning up"
	rm -f txtrader/*.pyc
	rm -rf build

build:
	@echo "Nothing to do"

install:
	python bumpbuild.py
	python setup.py install
	cp bin/txtrader /usr/local/bin
	ln -s $$PWD/service /etc/service/txtrader
	svc -u /etc/service/txtrader/log
	svc -u /etc/service/txtrader

uninstall:
	svc -d /etc/service/txtrader/log
	svc -d /etc/service/txtrader
	rm -f /etc/service/txtrader
	cat files.txt | xargs rm -f
	rm -f /usr/local/bin/txtrader

dist:
	python setup.py sdist

TESTS := $(wildcard txtrader/test-*.py)

test: $(TESTS)
	@echo "Testing..."
	cd txtrader; envdir ../service/env py.test -vvx $(notdir $^)
