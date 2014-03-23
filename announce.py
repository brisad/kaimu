import sys
import json
import time
import threading
from random import randrange
import zmq
from kaimu import FileListJSONEncoder
from avahiservice import AvahiAnnouncer

class RandomFilePublisher(threading.Thread):
    def __init__(self, name):
        super(RandomFilePublisher, self).__init__()
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.PUB)
        port = self.socket.bind_to_random_port("tcp://*")
        self.announcer = AvahiAnnouncer(name, port)
        self.announcer.start()
        self._stop = threading.Event()

    def run(self):
        while not self._stop.is_set():
            time.sleep(1)
            s = json.dumps(
                {'name': self.announcer.name,
                 'files': [{'name': "file %d" % x, 'path': None, 'size': x}
                          for x in range(randrange(1, 12))],
                 'port': -1},
                cls=FileListJSONEncoder)
            self.socket.send(s)

    def stop(self):
        self.announcer.stop()
        self._stop.set()


if __name__ == '__main__':
    if len(sys.argv) > 2:
        announcer = AvahiAnnouncer(sys.argv[1], int(sys.argv[2]))
        announcer.start()
        print "Announcing as", announcer.name
        raw_input("Press return to stop announcing")
        announcer.stop()
    else:
        p = RandomFilePublisher(sys.argv[1])
        p.daemon = True
        p.start()
        print "Announcing as", p.announcer.name, "with random files"
        raw_input("Press return to stop announcing")
        p.stop()
