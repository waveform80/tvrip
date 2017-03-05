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

"An application for extracting and transcoding DVDs of TV series"

__project__      = 'tvrip'
__version__      = '1.0'
__author__       = 'Dave Jones'
__author_email__ = 'dave@waveform.org.uk'
__url__          = 'https://github.com/waveform80/tvrip'
__platforms__    = ['ALL']

__classifiers__ = [
    'Development Status :: 5 - Production/Stable',
    'Environment :: Console',
    'Intended Audience :: End Users/Desktop',
    'License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)',
    'Operating System :: POSIX :: Linux',
    'Operating System :: MacOS :: MacOS X',
    'Programming Language :: Python :: 3',
    'Topic :: Multimedia :: Video :: Conversion',
    ]

__keywords__ = [
    'handbrake',
    'tv',
    'rip',
    ]

__requires__ = [
    'sqlalchemy<2.0dev',
    ]

__extra_requires__ = {
    'doc':   ['sphinx'],
    'test':  ['coverage', 'pytest'],
    }

__entry_points__ = {
    'console_scripts': [
        'tvrip = tvrip.main:main',
        ],
    }

