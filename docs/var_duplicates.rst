==========
duplicates
==========

::

    set duplicates all|first|last


Description
===========

This setting specifies the handling of duplicates (detected by title and
chapter length) by the :doc:`cmd_automap` command. For various reasons, it is
fairly common to find duplicated tracks on DVDs. The valid values for this
setting are:

all
    This is the default setting and indicates that you wish to map and rip all
    tracks, regardless of whether they have been detected as duplicates.

first
    Specifies that you only wish to rip the first out of a set of duplicate
    tracks. In the presence of actual duplicates, this is usually the best
    setting choice.

last
    Specifies that you only wish to rip the last out of a set of duplicate
    tracks.

.. note::

    In contrast to DVDs of films, where duplicate tracks are used as an
    anti-piracy measure, on DVD sets of TV series it is occasionally used for
    "commentary" tracks. Often, duplicated titles have both audio tracks, but
    one title will re-order them such that the commentary track is the default.
    This doesn't mean the video blocks are duplicated; just that multiple
    tracks with different meta-data exist.


See Also
========

:doc:`cmd_automap`
