#!/usr/bin/env python
# vim: set et sw=4 sts=4:

# Copyright 2012 Dave Hughes.
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

from setuptools import setup, find_packages
from utils import description, get_version, require_python

require_python(0x020500f0)

classifiers = [
    'Development Status :: 4 - Beta',
    'Environment :: Console',
    'Intended Audience :: Developers',
    'Intended Audience :: End Users/Desktop',
    'License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)',
    'Operating System :: POSIX',
    'Operating System :: Unix',
    'Programming Language :: Python :: 2.5',
    'Programming Language :: SQL',
    'Topic :: Multimedia :: Video :: Conversion',
    'Topic :: Database',
]

entry_points = {
    'console_scripts': [
        'tvrip = tvrip.main:tvrip_main',
    ]
}

def main():
    setup(
        name                 = 'tvrip',
        version              = get_version('tvrip/main.py'),
        description          = 'Command line TV series ripper',
        long_description     = description('README.txt'),
        author               = 'Dave Hughes',
        author_email         = 'dave@waveform.org.uk',
        url                  = 'http://www.waveform.org.uk/trac/tvrip/',
        packages             = find_packages(exclude=['distribute_setup', 'utils']),
        install_requires     = ['sqlalchemy'],
        include_package_data = True,
        platforms            = 'ALL',
        zip_safe             = False,
        entry_points         = entry_points,
        classifiers          = classifiers,
    )

if __name__ == '__main__':
    main()
