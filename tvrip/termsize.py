# vim: set et sw=4 sts=4:

import sys
import types

__all__ = ['terminal_size']

if sys.platform.startswith('win'):
    try:
        import win32console
        import win32api
        hstdin, hstdout, hstderr = win32api.STD_INPUT_HANDLE, win32api.STD_OUTPUT_HANDLE, win32api.STD_ERROR_HANDLE
    except ImportError:
        hstdin, hstdout, hstderr = -10, -11, -12
        try:
            import ctypes
            import struct
        except ImportError:
            # If neither ctypes (Python 2.5+) nor PyWin32 (extension) is
            # available, simply default to 80x25
            def query_console_size(handle):
                return None
        else:
            # ctypes query_console_size() adapted from
            # http://code.activestate.com/recipes/440694/
            def query_console_size(handle):
                h = ctypes.windll.kernel32.GetStdHandle(handle)
                if h:
                    buf = ctypes.create_string_buffer(22)
                    if ctypes.windll.kernel32.GetConsoleScreenBufferInfo(h, buf):
                        (
                            bufx, bufy,
                            curx, cury,
                            wattr,
                            left, top, right, bottom,
                            maxx, maxy,
                        ) = struct.unpack('hhhhHhhhhhh', buf.raw)
                        return (right - left + 1, bottom - top + 1)
                return None
    else:
        # PyWin32 query_console_size() adapted from 
        # http://groups.google.com/group/comp.lang.python/msg/f0febe6a8de9666b
        def query_console_size(handle):
            try:
                csb = win32console.GetStdHandle(handle)
                csbi = csb.GetConsoleScreenBufferInfo()
                size = csbi['Window']
                return (size.Right - size.Left + 1, size.Bottom - size.Top + 1)
            except:
                return None
    def default_console_size():
        return (80, 25)
else:
    # POSIX query_console_size() adapted from
    # http://mail.python.org/pipermail/python-list/2006-February/365594.html
    # http://mail.python.org/pipermail/python-list/2000-May/033365.html
    import fcntl
    import termios
    import struct
    import os
    hstdin, hstdout, hstderr = 0, 1, 2
    def query_console_size(handle):
        try:
            buf = fcntl.ioctl(handle, termios.TIOCGWINSZ, '12345678')
            row, col, rpx, cpx = struct.unpack('hhhh', buf)
            return (col, row)
        except:
            return None
    def default_console_size():
        fd = os.open(os.ctermid(), os.O_RDONLY)
        try:
            result = query_console_size(fd)
        finally:
            os.close(fd)
        if result:
            return result
        try:
            return (os.environ['COLUMNS'], os.environ['LINES'])
        except:
            return (80, 24)

def terminal_size():
    # Try stderr first as it's the least likely to be redirected
    for handle in (hstderr, hstdout, hstdin):
        result = query_console_size(handle)
        if result:
            return result
    return default_console_size()
