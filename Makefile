# txTrader makefile
#

build:
	docker-compose build 

# run the service locally
run: 
	docker-compose up --build txtrader 

# start the service locally in the background
start:
	docker-compose up --build -d txtrader

# stop the local running service
stop:
	docker-compose down 

shell:
	docker-compose run -v $$(pwd)/txtrader:/home/txtrader/txtrader txtrader /bin/bash -l

module:
	docker-compose run -v $$(pwd)/txtrader:/home/txtrader/txtrader txtrader /bin/bash -l
