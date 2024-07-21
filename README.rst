.. -*- rst -*-

=====
tvrip
=====

tvrip is a small command line script that brings together several other
utilities (Handbrake, Atomic Parsley, GOCR, etc.) with the aim of making it
relatively simple to rip whole seasons or series of TV episodes from DVD to
high quality MP4s, along with optional subtitles, alternate languages and
director's commentaries.


Pre-requisites
==============

tvrip depends primarily on the following applications:

 * `Handbrake`_

 * `Atomic Parsley`_

 * `mkvpropedit`_

 * `VLC`_

As tvrip is written in the `Python`_ language, you will need a copy of this
installed along with the following Python packages:

 * `sqlalchemy`_

 * `requests`_

 * `rich`_


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


Attributions
============

Episode meta-data in tvrip is (optionally) downloaded from the excellent
`TVDB`_.

.. image:: docs/images/the-tvdb.png
    :align: center


.. _Python: http://www.python.org/
.. _HandBrake: http://handbrake.fr/
.. _Atomic Parsley: http://atomicparsley.sourceforge.net/
.. _mkvpropedit: https://mkvtoolnix.download/
.. _sqlalchemy: http://www.sqlalchemy.org/
.. _requests: https://requests.readthedocs.io/
.. _rich: https://rich.readthedocs.io/
.. _TVDB: https://thetvdb.com/
