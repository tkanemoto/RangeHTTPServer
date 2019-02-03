#!/usr/bin/python
'''
Use this in the same way as Python's SimpleHTTPServer:

  python -m RangeHTTPServer [port]

The only difference from SimpleHTTPServer is that RangeHTTPServer supports
'Range:' headers to load portions of files. This is helpful for doing local web
development with genomic data files, which tend to be to large to load into the
browser all at once.
'''

import os
import re
import sys

try:
    # Python3
    from http.server import SimpleHTTPRequestHandler

except ImportError:
    # Python 2
    from SimpleHTTPServer import SimpleHTTPRequestHandler


def copy_byte_range(infile, outfile, start=None, stop=None, bufsize=16*1024):
    '''Like shutil.copyfileobj, but only copy a range of the streams.

    Both start and stop are inclusive.
    '''
    approx_start = start if start else 0
    approx_stop = stop if stop else bufsize * 100
    approx_bytes = approx_stop - approx_start
    acc = 0
    percent = 0

    if start is not None: infile.seek(start)
    while 1:
        to_read = min(bufsize, stop + 1 - infile.tell() if stop else bufsize)
        buf = infile.read(to_read)
        if not buf:
            break
        outfile.write(buf)

        acc += to_read
        percent = acc * 100 / approx_bytes
        for i in range(100):
            sys.stderr.write('█' if i < percent else '░')
        sys.stderr.write('\r')

    sys.stderr.write('\n')


BYTE_RANGE_RE = re.compile(r'bytes=(\d+)-(\d+)?$')
def parse_byte_range(byte_range):
    '''Returns the two numbers in 'bytes=123-456' or throws ValueError.

    The last number or both numbers may be None.
    '''
    if byte_range.strip() == '':
        return None, None

    m = BYTE_RANGE_RE.match(byte_range)
    if not m:
        raise ValueError('Invalid byte range %s' % byte_range)

    first, last = [x and int(x) for x in m.groups()]
    if last and last < first:
        raise ValueError('Invalid byte range %s' % byte_range)
    return first, last


class RangeRequestHandler(SimpleHTTPRequestHandler):
    """Adds support for HTTP 'Range' requests to SimpleHTTPRequestHandler

    The approach is to:
    - Override send_head to look for 'Range' and respond appropriately.
    - Override copyfile to only transmit a range when requested.
    """
    def send_head(self):
        if 'Range' not in self.headers:
            self.range = None
            self.file_length = None
            f = SimpleHTTPRequestHandler.send_head(self)
            if f:
                old = f.tell()
                f.seek(0, os.SEEK_END)
                self.file_length = f.tell()
                f.seek(old, os.SEEK_SET)
            return f
        try:
            self.range = parse_byte_range(self.headers['Range'])
        except ValueError as e:
            self.send_error(400, 'Invalid byte range')
            return None
        first, last = self.range

        # Mirroring SimpleHTTPServer.py here
        path = self.translate_path(self.path)
        f = None
        ctype = self.guess_type(path)
        try:
            f = open(path, 'rb')
        except IOError:
            self.send_error(404, 'File not found')
            return None

        f.seek(0, os.SEEK_END)
        self.file_length = f.tell()
        f.seek(0, os.SEEK_SET)

        fs = os.fstat(f.fileno())
        file_len = fs[6]
        if first >= file_len:
            self.send_error(416, 'Requested Range Not Satisfiable')
            return None

        if last is None or last >= file_len:
            last = file_len - 1
        response_length = last - first + 1

        self.send_response(206)
        self.send_header('Content-type', ctype)
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Range',
                         'bytes %s-%s/%s' % (first, last, file_len))
        self.send_header('Content-Length', str(response_length))
        self.send_header('Last-Modified', self.date_time_string(fs.st_mtime))
        self.end_headers()
        return f

    def copyfile(self, source, outputfile):
        if not self.range:
            return SimpleHTTPRequestHandler.copyfile(self, source, outputfile)

        # SimpleHTTPRequestHandler uses shutil.copyfileobj, which doesn't let
        # you stop the copying before the end of the file.
        start, stop = self.range  # set in send_head()
        copy_byte_range(source, outputfile, start, stop)

    def log_message(self, format, *args):
        if self.range is not None:
            args += (self.range,)
            format += ' %s'
        if self.file_length is not None:
            args += (self.file_length,)
            format += ' %s'
        SimpleHTTPRequestHandler.log_message(self, format, *args)
