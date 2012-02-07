#!/usr/bin/env python
# vim: set et sw=4 sts=4:

"""Command line TV series ripper.

tvrip is a small command line script that brings together several other
utilities (Handbrake, MEncoder, GOCR, etc.) with the aim of making it
relatively simple to rip whole seasons or series of TV episodes from DVD to
high quality MP4s, along with optional subtitles (either ripped straight as
images into VOBSUB or tranlsated into text SubRip).
"""

import ez_setup
ez_setup.use_setuptools() # install setuptools if it isn't already installed

classifiers = [
    'Development Status :: 4 - Beta',
    'Environment :: Console',
    'Intended Audience :: Developers',
    'Intended Audience :: End Users/Desktop',
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

def get_console_scripts():
    import re
    for s in entry_points['console_scripts']:
        print re.match(r'^([^= ]*) ?=.*$', s).group(1)

def main():
    from setuptools import setup, find_packages
    from tvrip.main import __version__
    setup(
        name                 = 'tvrip',
        version              = __version__,
        description          = 'Command line TV series ripper',
        long_description     = __doc__,
        author               = 'Dave Hughes',
        author_email         = 'dave@waveform.org.uk',
        url                  = 'http://www.waveform.org.uk/trac/tvrip/',
        packages             = find_packages(),
        include_package_data = True,
        platforms            = 'ALL',
        zip_safe             = False,
        entry_points         = entry_points,
        classifiers          = classifiers,
        install_requires     = [
            'sqlalchemy',
        ],
    )

if __name__ == '__main__':
    main()
