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
from pathlib import Path
from contextlib import contextmanager

from .database import Database
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
            self.debug = int(os.environ['DEBUG'])
        except (KeyError, ValueError):
            self.debug = 0
        try:
            conf = self.parser.parse_args(args)
            db_path = Path(DATADIR) / 'tvrip.db'
            db_path.parent.mkdir(parents=True, exist_ok=True)
            with Database(db_path, debug=bool(self.debug)) as db:
                cmd = RipCmd(db)
                cmd.console.print(f'[green]TVRip {self.version}[/green]')
                cmd.console.print(
                    'Type "[yellow]help[/yellow]" for more information.')
                cmd.cmdloop()
        except Exception as e:
            if not self.debug:
                print(str(e), file=sys.stderr, flush=True)
                return 1
            elif self.debug == 1:
                raise
            else:
                import pdb
                pdb.post_mortem()
        return 0


main = TVRipApplication()
