# vim: set et sw=4 sts=4:

import os
import locale

# Stuff you probably don't want to change

ENCODING = locale.getdefaultlocale()[1]
DATADIR = os.path.expanduser('~/.tvrip') # must be absolute

HANDBRAKE       = u'/usr/bin/HandBrakeCLI'
ATOMIC_PARSLEY  = u'/usr/bin/AtomicParsley'
TCCAT           = u'/usr/bin/tccat'
TCEXTRACT       = u'/usr/bin/tcextract'
SUBP2PGM        = u'/usr/bin/subtitle2pgm'
GOCR            = u'/usr/bin/gocr'
MENCODER        = u'/usr/bin/mencoder'

AUDIO_MIX_ORDER = [u'5.1 ch', u'5.0 ch', u'Dolby Surround', u'2.0 ch', u'1.0 ch']
AUDIO_ENC_ORDER = [u'DTS', u'AC3']

ISOFILE = os.path.join(DATADIR, u'iso639.txt')
if os.path.exists(ISOFILE):
    ISO639 = list(
        line.split('|')
        for line in open(ISOFILE).read().decode('UTF-8').splitlines()
    )
    ISO639 = dict(
        (bib_code, (lang_code, name))
        for (bib_code, term_code, lang_code, name, french_name) in ISO639
    )

