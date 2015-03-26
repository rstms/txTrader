# TxTrader setup.py



from distutils.core import setup
from rsagw.version import __version__
setup(
  name='txTrader',
  version=__version__,
  description='TxTrader Securities Trading API Controller',
  author='Matt Krueger',
  author_email='mkrueger@rstms.net',
  url='https://github.com/rstms/txTrader',
  install_requires=[
    'Twisted',
    'egenix-mx-base'
  ],
  packages=['txtrader'],
  package_dir={'txtrader': 'txtrader'},
)
