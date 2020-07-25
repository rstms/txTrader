FROM python:3.8.3-buster

MAINTAINER mkrueger@rstms.net

RUN pip install \
  click \
  hexdump \
  pytest \ 
  pytz \ 
  requests \
  twisted \ 
  txtrader-client \
  txtrader-monitor \ 
  tzlocal \ 
  ujson \
  wait-for-it 

RUN apt-get update && apt-get install -y \
  less \
  vim

RUN \
  echo 'America/Chicago' >/etc/timezone \
  && rm /etc/localtime \
  && dpkg-reconfigure -f noninteractive tzdata

RUN useradd -m txtrader
USER txtrader
WORKDIR /home/txtrader
RUN mkdir -p /home/txtrader/.local/bin
COPY setup.py /home/txtrader
COPY pytest.ini /home/txtrader
COPY txtrader /home/txtrader/txtrader
COPY tests /home/txtrader/tests
RUN pip install . --user --no-warn-script-location

CMD ["bash", "-l", "-c", "txtraderd"]
