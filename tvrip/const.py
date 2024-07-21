# tvrip: extract and transcode DVDs of TV series
#
# Copyright (c) 2024 Dave Jones <dave@waveform.org.uk>
# Copyright (c) 2011-2012 Dave Hughes <dave@waveform.org.uk>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Contains suite-level constants defined as globals"""

import os
from pathlib import Path

# The path under which tvrip-related data will be kept
XDG_CONFIG_HOME = Path(os.environ.get(
    'XDG_CONFIG_HOME', Path.home() / '.config'))
DATADIR = Path(os.environ.get(
    'TVRIP_CONFIG', XDG_CONFIG_HOME / 'tvrip'))
