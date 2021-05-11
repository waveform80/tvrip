import struct
import ctypes


# ctypes query_console_size() adapted from
# http://code.activestate.com/recipes/440694/
def term_size():
    "Returns the size (cols, rows) of the console"

    def get_handle_size(handle):
        "Subroutine for querying terminal size from std handle"
        handle = ctypes.windll.kernel32.GetStdHandle(handle)
        if handle:
            buf = ctypes.create_string_buffer(22)
            if ctypes.windll.kernel32.GetConsoleScreenBufferInfo(
                    handle, buf):
                (left, top, right, bottom) = struct.unpack(
                    'hhhhHhhhhhh', buf.raw)[5:9]
                return (right - left + 1, bottom - top + 1)
        return None

    stdin, stdout, stderr = -10, -11, -12
    return (
        get_handle_size(stderr) or
        get_handle_size(stdout) or
        get_handle_size(stdin) or
        # Default
        (80, 25)
    )
