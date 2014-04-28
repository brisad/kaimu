import logging
import itertools
import threading
import os
import os.path
import json
import sys
import zmq
import serialization


class DownloadError(Exception):
    pass


def file_request_msg(filename, offset, size):
    """Return serialized file request message"""

    return json.dumps({'request': filename,
                       'offset': int(offset), 'size': int(size)})

def parse_file_request(message):
    """Return deserialized message as a tuple"""

    def unpack(request, offset, size):
        return request, int(offset), int(size)

    filename, offset, size = unpack(**json.loads(message))
    return filename, offset, size

def file_header(filename, offset, size):
    """Return serialized file header"""

    return json.dumps({'filename': filename, 'offset': offset, 'size': size})

def parse_file_header(header):
    """Return deserialized header contents as a dict

    The reason for returning a dict instead of a tuple is that the
    contents of the header can take different forms, and thus also the
    items in the returned dict.
    """

    def unpack(filename, offset, size):
        return filename, int(offset), int(size)

    decoded_header = json.loads(header)
    if 'error' in decoded_header:
        return {'error': decoded_header['error']}
    filename, offset, size = unpack(**decoded_header)
    return {'filename': filename, 'offset': offset, 'size': size}

def error_msg(description):
    """Return serialized error message"""

    return json.dumps({'error': description})


class FileChunker(object):
    """Handles chunked reading of file contents.

    Reads chunks of a file into frames ready to be transmitted.
    """

    def __init__(self, filename):
        self.filename = filename
        self.f = open(filename, 'rb')

    def __del__(self):
        # This check prevents us from trying to close a non-existant
        # file in case open in __init__ raised an exception.
        if hasattr(self, 'f'):
            self.f.close()

    def read(self, offset, size):
        """Read a chunk from opened file.

        Given an offset and size, return a header and actual chunk
        contents as a tuple.

        The header contains offset, size and filename.  The offset and
        size will have the same values as the passed arguments.  The
        filename on the other hand will only contain the basename of
        the opened file.  This is because this header will be
        transmitted and then the path to the file should not be
        present.
        """

        self.f.seek(offset)
        contents = self.f.read(size)
        header = {'filename': os.path.basename(self.filename),
                  'offset': offset, 'size': size}
        return header, contents


class FileServer(threading.Thread):
    def __init__(self, context, frontend_addr=None, pipe=None):
        super(FileServer, self).__init__()
        self.context = context
        self.frontend_addr = frontend_addr
        self.pipe = pipe
        self._shared_files = []
        self._bound_port = None

        if not self.pipe:
            self.pipe = self.context.socket(zmq.PAIR)
            self.pipe.bind("inproc://fs-pipe")

    def run(self, iterations=None,
            use_frontend=True, frontend=None,
            use_thread_pipe=True, thread_pipe=None):
        poller = zmq.Poller()

        if use_frontend:
            if frontend is None:
                frontend = self.context.socket(zmq.ROUTER)
                if self.frontend_addr:
                    frontend.bind(self.frontend_addr)
                    port_str = self.frontend_addr.rpartition(':')[-1]
                    self._bound_port = int(port_str)
                else:
                    self._bound_port = frontend.bind_to_random_port("tcp://*")
            poller.register(frontend, zmq.POLLIN)

        if use_thread_pipe:
            if thread_pipe is None:
                thread_pipe = self.context.socket(zmq.PAIR)
                thread_pipe.connect("inproc://fs-pipe")
            poller.register(thread_pipe, zmq.POLLIN)

        for i in itertools.count():
            if iterations is not None and iterations == i:
                break
            socks = dict(poller.poll())
            if thread_pipe in socks and socks[thread_pipe] == zmq.POLLIN:
                should_stop = self._handle_pipe(thread_pipe)
                if should_stop:
                    break
            elif frontend in socks and socks[frontend] == zmq.POLLIN:
                self._handle_frontend(frontend)

    def _handle_pipe(self, pipe):
        data = pipe.recv()
        if data == 'STOP':
            return True
        method, params = serialization.deserialize(data)
        result = getattr(self, 'on_%s' % method)(params)
        pipe.send(serialization.s_res(result))
        return False

    def _handle_frontend(self, frontend):
        identity = frontend.recv()
        message = frontend.recv()
        frontend.send_multipart([identity] + self.on_frontend_message(message))

    def add_file(self, filename):
        """Add file to be shared.

        filename is the full path of the file to be shared.

        The basename of the filename cannot collide with the basename
        of another file already shared.  This is because when serving
        files on the frontend, basenames are used to identify the
        files.
        """

        self.pipe.send(serialization.s_req('add_file', filename))
        response = self.pipe.recv()
        if response and serialization.deserialize(response).result is False:
            raise IndexError("File already present")

    def on_add_file(self, filename):
        if filename in self._shared_files:
            return False
        self._shared_files.append(filename)
        return True

    def remove_file(self, filename):
        self.pipe.send(serialization.s_req('remove_file', filename))
        response = self.pipe.recv()

    def on_remove_file(self, filename):
        self._shared_files.remove(filename)

    def get_files(self):
        self.pipe.send(serialization.s_req('get_files', None))
        response = self.pipe.recv()
        return serialization.deserialize(response).result

    def on_get_files(self, dummy=None):
        return tuple(self._shared_files)

    def on_frontend_message(self, message):
        # Process message from client.  Returns list of zmq frames to
        # be sent back to client.
        filename, offset, size = parse_file_request(message)
        for path in self._shared_files:
            if os.path.basename(path) == filename:
                try:
                    # This opens the file for every request.  We'll
                    # want to cache this later
                    chunker = FileChunker(path)
                    header, contents = chunker.read(offset, size)
                    logging.debug('Server response header: %s', header)
                    frames = [file_header(**header), contents]
                except IOError:
                    frames = [error_msg('read error')]
                return frames
        # If we got here we didn't have the requested file
        return [error_msg('file not found')]

    def get_bound_port(self):
        self.pipe.send(serialization.s_req('get_bound_port', None))
        response = self.pipe.recv()
        return serialization.deserialize(response).result

    def on_get_bound_port(self, dummy=None):
        return self._bound_port

    def stop(self):
        self.pipe.send("STOP")


class Downloader(object):
    """Client for downloading files from server"""

    def __init__(self, context, endpoint, filename, filesize, chunksize=None):
        self.context = context
        self.endpoint = endpoint
        self.filename = filename
        self.filesize = filesize
        if chunksize is None:
            chunksize = filesize
        self.chunksize = chunksize
        self.destination = os.path.join(os.getcwd(), filename)
        self.has_downloaded = False

    def _validate_header(self, header, offset, size):
        # Check that header is consistent with what we expect.
        # Otherwise raise DownloadError.
        if 'error' in header:
            raise DownloadError({'success': False, 'reason': header['error']})
        elif header['filename'] != self.filename:
            print header['filename']
            print self.filename
            raise DownloadError(
                {'success': False,
                 'reason': 'Wrong filename received from server'})
        elif header['offset'] != offset:
            raise DownloadError(
                {'success': False,
                 'reason': 'Wrong offset received from server'})
        elif header['size'] != size:
            raise DownloadError(
                {'success': False,
                 'reason': 'Wrong size received from server'})

    def _validate_chunk(self, chunk, size):
        # Check that chunk is consistent with what we expect.
        # Otherwise raise DownloadError.
        if len(chunk) != size:
            raise DownloadError(
                {'success': False,
                 'reason': 'Wrong data received from server'})

    def _chunks(self, chunksize, total):
        # Generate tuples of offset and size describing chunks of a
        # file.  Continue until total size has been exhausted.
        offset = 0
        while offset < total:
            size = min(chunksize, total - offset)
            yield offset, size
            offset += size

    def _get_all_chunks(self, socket, filehandle):
        # Query all chunks making up a file from socket and write it
        # to filehandle.  For all chunks, send a request, receive the
        # response and append it to file.
        for offset, size in self._chunks(self.chunksize, self.filesize):
            # Create and send request to server
            request_msg = file_request_msg(self.filename, offset, size)
            logging.debug('Request chunk: %s', request_msg)
            socket.send(request_msg.encode('utf-8'))

            # The first frame contains the header
            first_frame = socket.recv()
            try:
                header = parse_file_header(first_frame)
            except (ValueError, TypeError):
                raise DownloadError(
                    {'success': False,
                     'reason': 'Invalid data received from server'})

            # Header had the right structure, now check that it is
            # what we expect it to be
            self._validate_header(header, offset, size)

            # Retreive contents and validate
            file_chunk = socket.recv()
            self._validate_chunk(file_chunk, size)

            filehandle.write(file_chunk)

    def download(self, callback):
        """Start download of file to disk

        Use callback to signal the result of the operation.  callback
        is passed a dict as argument which contains a key 'success'
        with a value of True or False.  If it is True, it indicates
        success and the dict will also contain a key 'path' with a
        value giving the path of the downloaded file on the file
        system.  If 'success' is False, the dict will instead contain
        a key 'reason' with a string as value, stating the reason for
        the failure.
        """

        if os.path.exists(self.destination):
            callback({'success': False, 'reason': 'File already exists'})
            return

        socket = self.context.socket(zmq.DEALER)
        socket.connect(self.endpoint)

        with open(self.destination, 'wb') as f:
            try:
                self._get_all_chunks(socket, f)
            except DownloadError as error:
                callback(error.args[0])
                return

        self.has_downloaded = True
        callback({'success': True, 'path': self.destination})


if __name__ == '__main__':
    context = zmq.Context()
    server = FileServer(context)
    server.start()

    server.add_file("tests.py")
    server.add_file("README.md")
    print server.get_files()
    server.remove_file("README.md")
    print server.get_files()

    serverport = server.get_bound_port()
    print serverport

    try:
        req = raw_input()
        while True:
            s = context.socket(zmq.DEALER)
            s.connect("tcp://localhost:%d" % serverport)
            msg = file_request_msg(req, 0, 42)
            print "Sending:", msg
            s.send(msg)
            header = s.recv()
            print header
            if 'filename' in header:
                print s.recv()
            req = raw_input()
    except (EOFError, KeyboardInterrupt):
        pass
    server.stop()
