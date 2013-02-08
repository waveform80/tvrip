.. -*- rst -*-

=====
tvrip
=====

tvrip is a small command line script that brings together several other
utilities (Handbrake, Atomic Parsley, GOCR, etc.) with the aim of making it
relatively simple to rip whole seasons or series of TV episodes from DVD to
high quality MP4s, along with optional subtitles (either ripped straight as
images into VOBSUB or tranlsated into text SubRip).

This package is also available in .deb form from ppa://waveform/ppa


Pre-requisites
==============

tvrip depends primarily on the following applications:

 * `Handbrake <http://handbrake.fr/>`_

 * `Atomic Parsley <http://atomicparsley.sourceforge.net>`_

If you wish to use OCR to convert DVD (picture-based) subtitles into SubRip
(text-based) subtitles you will also need:

 * `GOCR <http://jocr.sourceforge.net>`_

 * `Transcode Utilities <http://tcforge.berlios.de>`_

As tvrip is written in the `Python <http://www.python.org/>`_ language, you
will need a copy of this installed along with the following Python packages:

 * `sqlalchemy <http://www.sqlalchemy.org>`_


License
=======

This file is part of tvrip.

tvrip is free software: you can redistribute it and/or modify it under the
terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.

tvrip is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR
A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with
tvrip.  If not, see <http://www.gnu.org/licenses/>.

