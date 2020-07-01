FROM amazon/aws-cli:2.0.17 as awscli

FROM python:3.8.3-buster

COPY --from=awscli /usr/local/bin /usr/local/bin
COPY --from=awscli /usr/local/aws-cli /usr/local/aws-cli

MAINTAINER mkrueger@rstms.net
RUN \
  apt update -y \
  && apt install -y build-essential wget daemontools-run ucspi-tcp jq ncat vim less
##--no-install-recommends \ 
# && apt-get clean
# && rm -rf /var/lib/apt/lists/*

RUN pip install twisted ujson hexdump pytz tzlocal

RUN \
  echo 'America/Chicago' >/etc/timezone \
  && rm /etc/localtime \
  && dpkg-reconfigure -f noninteractive tzdata

ARG TXTRADER_UID
ARG TXTRADER_GID 

ENV TXTRADER_UID ${TXTRADER_UID:-1000} 
ENV TXTRADER_GID ${TXTRADER_GID:-1000} 

# add user account and configure
RUN groupadd --gid $TXTRADER_GID txtrader 
RUN useradd -m txtrader --uid $TXTRADER_UID --gid $TXTRADER_GID -Gsudo 
#RUN sed -e "s|^%sudo.*$|%sudo ALL=(ALL:ALL) NOPASSWD:ALL|" -i /etc/sudoers

WORKDIR /home/txtrader
COPY txtrader ./txtrader/
COPY etc/txtrader ./env
COPY service/txtrader/txtrader.tac .

RUN chown -R txtrader.txtrader /home/txtrader

USER txtrader

CMD ["/usr/bin/envdir", "/home/txtrader/env", "/usr/local/bin/python", "-m", "txtrader"]
