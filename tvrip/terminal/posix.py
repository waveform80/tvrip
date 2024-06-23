import os
import fcntl
import struct
import termios


# POSIX query_console_size() adapted from
# http://mail.python.org/pipermail/python-list/2006-February/365594.html
# http://mail.python.org/pipermail/python-list/2000-May/033365.html
def term_size():
    "Returns the size (cols, rows) of the console"

    def get_handle_size(handle):
        "Subroutine for querying terminal size from std handle"
        try:
            buf = fcntl.ioctl(handle, termios.TIOCGWINSZ, '12345678')
            row, col = struct.unpack('hhhh', buf)[0:2]
            return (col, row)
        except OSError:
            return None

    stdin, stdout, stderr = 0, 1, 2
    # Try stderr first as it's the least likely to be redirected
    result = (
        get_handle_size(stderr) or
        get_handle_size(stdout) or
        get_handle_size(stdin)
    )
    if not result:
        try:
            fd = os.open(os.ctermid(), os.O_RDONLY)
        except OSError:
            pass
        else:
            try:
                result = get_handle_size(fd)
            finally:
                os.close(fd)
    if not result:
        try:
            result = (os.environ['COLUMNS'], os.environ['LINES'])
        except KeyError:
            # Default
            result = (80, 24)
    return result
