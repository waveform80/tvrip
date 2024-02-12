#!/usr/bin/env python
# vim: set et sw=4 sts=4:

# Copyright 2012-2017 Dave Jones <dave@waveform.org.uk>.
#
# This file is part of tvrip.
#
# tvrip is free software: you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version.
#
# tvrip is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR
# A PARTICULAR PURPOSE.  See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with
# tvrip.  If not, see <http://www.gnu.org/licenses/>.

"Implements the main loop and option parser for the tvrip application"

import os
import sys
import argparse

from .terminal import ErrorHandler
from .database import init_session
from .ripcmd import RipCmd
from .const import DATADIR

from importlib.metadata import version


class TVRipApplication:
    """
    %prog [options]

    This command line interface simplifies the extraction and transcoding of a
    DVD containing a TV series (or a season of a TV series) via HandBrake.
    """
    def __init__(self):
        super().__init__()
        self.version = version(__package__)
        self.parser = argparse.ArgumentParser(description=self.__doc__)
        self.parser.add_argument(
            '--version', action='version', version=self.version)

    def __call__(self, args=None):
        try:
            debug = int(os.environ['DEBUG'])
        except (KeyError, ValueError):
            debug = 0

        try:
            conf = self.parser.parse_args(args)
            DATADIR.mkdir(parents=True, exist_ok=True)
            with init_session(debug=bool(debug)) as session:
                cmd = RipCmd(session)
                cmd.pprint('TVRip %s' % self.version)
                cmd.pprint('Type "help" for more information.')
                cmd.cmdloop()
        except Exception as e:
            if not debug:
                print(str(e), file=sys.stderr, flush=True)
                return 1
            elif debug == 1:
                raise
            else:
                import pdb
                pdb.post_mortem()


main = TVRipApplication()
