import itertools
import threading
import json
import sys
import zmq
import serialization


class FileReader(object):
    def __init__(self, open_func=open):
        self.open_func = open_func

    def read(self, filename):
        try:
            data = self.open_func(filename).read()
        except IOError:
            return {"error": "read error"}
        return {"filename": filename, "contents": data}


class FileServer(threading.Thread):
    def __init__(self, context, frontend_addr=None, pipe=None, reader=None):
        super(FileServer, self).__init__()
        self.context = context
        self.frontend_addr = frontend_addr
        self.pipe = pipe
        self.reader = reader
        self._shared_files = []

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
                frontend.bind(self.frontend_addr)
            poller.register(frontend, zmq.POLLIN)

        if use_thread_pipe:
            if thread_pipe is None:
                thread_pipe = self.context.socket(zmq.PAIR)
                thread_pipe.connect("inproc://fs-pipe")
            poller.register(thread_pipe, zmq.POLLIN)

        for i in itertools.count():
            if iterations is not None and iterations == i:
                break
            socks = dict(poller.poll(0))
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
        frontend.send_multipart([identity, self.on_frontend_message(message)])

    def add_file(self, filename):
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

    def _extract_request(self, message):
        return json.loads(message)['request']

    def on_frontend_message(self, message):
        filename = self._extract_request(message)
        if filename in self._shared_files:
            return json.dumps(self.reader.read(filename))
        return '{"error": "file not found"}'

    def stop(self):
        self.pipe.send("STOP")


if __name__ == '__main__':
    context = zmq.Context()
    server = FileServer(context, "tcp://*:6777", reader=FileReader())
    server.start()

    server.add_file("tests.py")
    server.add_file("README.md")
    print server.get_files()
    server.remove_file("README.md")
    print server.get_files()

    try:
        req = raw_input()
        while True:
            s = context.socket(zmq.DEALER)
            s.connect("tcp://localhost:6777")
            msg = '{"request": "%s"}' % req
            print "Sending:", msg
            s.send(msg)
            print s.recv()
            req = raw_input()
    except:
        pass
    server.stop()