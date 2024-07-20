===========
video_style
===========

::

    set video_style tv|film|animation

This setting provides a hint of the video style to the HandBrake encoder. The
following values are valid for this setting:

``tv``
    This is the default setting, and doesn't affect encoder behaviour that
    much. ``television`` is a valid alias for this value.

``film``
    This setting attempts to preserve "film grain" in the output. Be aware that
    while output will typically be closer to the original, it can result in
    *much* larger output files.

``animation``
    This setting optimizes the encoder for animation that includes large blocks
    of similar color and "sharp" lines. ``anim`` is a valid alias for this
    value.

For example::

    (tvrip) set video_style anim
