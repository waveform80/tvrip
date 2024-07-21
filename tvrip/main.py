#!/usr/bin/env python
#
# tvrip: extract and transcode DVDs of TV series
#
# Copyright (c) 2017-2024 Dave Jones <dave@waveform.org.uk>
# Copyright (c) 2011-2014 Dave Hughes <dave@waveform.org.uk>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"Implements the main loop and option parser for the tvrip application"

import os
import sys
import argparse

from .database import init_session
from .ripcmd import RipCmd
from .const import DATADIR

from importlib.metadata import version


class TVRipApplication:
    """
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
                cmd.console.print(f'[green]TVRip {self.version}[/green]')
                cmd.console.print(
                    'Type "[yellow]help[/yellow]" for more information.')
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
        return 0


main = TVRipApplication()
