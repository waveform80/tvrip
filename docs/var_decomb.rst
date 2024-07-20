=======
decomb
=======

::

    set decomb off|on|auto

This configuration option specifies a decomb mode. Before ripping the first
title from a disc, it is strongly recommended that users preview a title first
with the :doc:`cmd_play` command, disabling interlacing to determine whether
"combing" artifacts are present.

Valid values of this setting are:

``off``
    No decomb or deinterlace is applied. Use this on sources which are
    definitely progressively encoded all the way through (this is the case with
    most modern films)

``on``
    Apply deinterlacing to the entire rip. This is typically useful on older TV
    shows which were encoded entirely interlaced. This will slow down the rip,
    but will result in a much smaller file-size with no combing artifacts on
    playback

``auto``
    Apply automatic decomb on frames where combing is detected. This is
    typically useful on TV shows which use selective interlacing (typically for
    overlays or visual effects). This will slow down the rip, but will result
    in a smaller file-size with no combing artifacts on playback

Example::

    (tvrip) set decomb auto
    (tvrip) set decomb on

See also :doc:`cmd_play`
