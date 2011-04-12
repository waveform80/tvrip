# vim: set et sw=4 sts=4:

import os

# Stuff you probably don't want to change

DATADIR = os.path.expanduser('~/.tvrip') # must be absolute
if not os.path.exists(DATADIR):
    os.mkdir(DATADIR)
