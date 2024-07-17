===============
subtitle_format
===============

::

    set subtitle_format none|vobsub|pgs|cc|any


Description
===========

Sets the encoding of subtitles in the output file. The following values are
valid for this setting:

none
    Disables all subtitle encoding. This can also be achieved by clearing the
    :doc:`var_subtitle_langs` setting, but this is simpler. ``off`` is an alias
    for this value.

vobsub
    This is the standard encoding method for DVD subtitles, in which subtitles
    are encoded as static overlay pictures. ``vob``, ``bmp``, and ``bitmap``
    are aliases for this value. Both MP4 (.mp4) and Matroska (.mkv) files can
    contain subtitles with this encoding.

    While the results are relatively crude, can't be repositioned, resized, or
    rendered in different fonts, they are capable of showing anything a picture
    can show, and thus aren't limited to specific character sets or fonts. This
    is the recommended setting for DVD ripping.

pgs
    This is the standard encoding method for Blu-ray subtitles. Only Matroska
    (.mkv) files can contain subtitles in this format. This is the recommended
    setting for Blu-ray ripping.

cc
    Closed-captions; some DVDs (particularly US Region 1) contain subtitles in
    this format which is essentially plain text. ``text`` is an alias for this
    value.

any
    Any encoding; this will pass through any subtitles matching the language
    filter to the output file. This is not generally recommended as it will
    often result in duplicated subtitle tracks.

For example::

    (tvrip) set subtitle_format vobsub
    (tvrip) set subtitle_format off


See Also
========

:doc:`var_subtitle_langs`
