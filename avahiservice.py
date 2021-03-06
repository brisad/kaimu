import uuid
from multiprocessing import Process
import zmq
import dbus
import dbus.glib
from dbus.mainloop.glib import DBusGMainLoop
import avahi
import gobject


TYPE = '_kaimu._tcp'

def ipc_name(prefix):
    return "ipc://%s-%s" % (prefix,str(uuid.uuid4())[:13])


class Browser(object):
    """Browse services with Avahi in a new process.

    Detects addition and removal of kaimu services on the local
    domain.  When either of those events happen, a message is written
    to the zmq socket available immediately after start(), found in
    the instance variable socket.

    Two types of messages can be sent to the receiving socket,
    addition of a service and removal of a service.  These are
    represented as json encoded lists in the following format:
    - Addition: ["N", name, address, port]
    - Removal:  ["R", name]

    The browser runs in its own process.  All sorts of funny things
    happened when the browser was run in a thread at the same time as
    wxPython, even when the glib thread initialization methods had
    been called.  The solution was to do the browsing in a separate
    process instead and be careful to spawn it before initializing the
    wxApp.  If it's spawned after wxPython starts, funny things will
    begin happening again.
    """

    CHECK_STOP_INTERVAL = 100

    def __init__(self, context):
        self.context = context  # used in the stop method
        self.ctrladdr = ipc_name('browserctrl')

    def run(self):
        # This method runs in a new process, so create a new context
        context = zmq.Context()
        self.outsock = context.socket(zmq.PUSH)
        self.outsock.connect(self.address)

        # Socket for receiving the stop signal
        self.ctrlsock = context.socket(zmq.SUB)
        self.ctrlsock.setsockopt(zmq.SUBSCRIBE, "")
        self.ctrlsock.bind(self.ctrladdr)
        self.poller = zmq.Poller()
        self.poller.register(self.ctrlsock, zmq.POLLIN)

        self._start_browser()

        self.outsock.close()
        self.ctrlsock.close()
        # These are here to make sure zmq unlinks the ipc-pipes
        del self.poller
        del self.outsock
        del self.ctrlsock

    def start(self):
        """Bind receiving socket and start browsing."""

        self.address = ipc_name("avahibrowse")
        self.socket = self.context.socket(zmq.PULL)
        self.socket.bind(self.address)

        self.proc = Process(target=self.run)
        self.proc.start()

    def stop(self):
        """Stop browsing and close receiving socket."""

        socket = self.context.socket(zmq.PUB)
        socket.connect(self.ctrladdr)
        # Send stop signal until process dies
        while self.proc.is_alive():
            socket.send("STOP")
        self.socket.close()

    def _start_browser(self):
        bus = dbus.SystemBus(mainloop=DBusGMainLoop(set_as_default=True))
        self.server = dbus.Interface(bus.get_object(
                avahi.DBUS_NAME, avahi.DBUS_PATH_SERVER),
                                     avahi.DBUS_INTERFACE_SERVER)

        service_browser = dbus.Interface(bus.get_object(
                avahi.DBUS_NAME,
                self.server.ServiceBrowserNew(
                    avahi.IF_UNSPEC, avahi.PROTO_UNSPEC,
                    TYPE, "", dbus.UInt32(0))),
                                         avahi.DBUS_INTERFACE_SERVICE_BROWSER)
        service_browser.connect_to_signal("ItemNew", self._item_new)
        service_browser.connect_to_signal("ItemRemove", self._item_remove)

        self.loop = gobject.MainLoop()
        gobject.timeout_add(self.CHECK_STOP_INTERVAL, self._check_stop)
        self.loop.run()

    def _check_stop(self):
        """Stop main loop if stop command received."""

        socks = dict(self.poller.poll(0))
        if self.ctrlsock in socks and socks[self.ctrlsock] == zmq.POLLIN:
            self.loop.quit()
            return False
        return True

    def _resolved_service(self, interface, protocol, name, service_type,
                          domain, host, aprotocol, address, port, txt, flags):
        self.outsock.send_json(["N", name, address, port])

    def _resolve_error(self, *args):
        print "Resolve error:", args

    def _item_remove(self, interface, protocol, name, service_type, domain,
                     flags):
        self.outsock.send_json(["R", name])

    def _item_new(self, interface, protocol, name, service_type, domain, flags):
        if flags & avahi.LOOKUP_RESULT_LOCAL:
            pass  # skip later?

        self.server.ResolveService(
            interface, protocol, name, service_type, domain,
            avahi.PROTO_UNSPEC, dbus.UInt32(0),
            reply_handler=self._resolved_service,
            error_handler=self._resolve_error)


class Announcer(object):
    """Announce a kaimu service with Avahi."""

    def __init__(self, name, port):
        self.name = name
        self.port = port

    def start(self):
        bus = dbus.SystemBus()
        server = dbus.Interface(
            bus.get_object(avahi.DBUS_NAME, avahi.DBUS_PATH_SERVER),
            avahi.DBUS_INTERFACE_SERVER)

        self.group = dbus.Interface(
            bus.get_object(avahi.DBUS_NAME, server.EntryGroupNew()),
            avahi.DBUS_INTERFACE_ENTRY_GROUP)

        while True:
            try:
                self.group.AddService(avahi.IF_UNSPEC, avahi.PROTO_INET,
                                      dbus.UInt32(0), self.name,
                                      TYPE, "", "", self.port, "")
            except dbus.DBusException as e:
                if 'CollisionError' in e.get_dbus_name():
                    self.name = server.GetAlternativeServiceName(self.name)
                else:
                    raise e
            else:
                break

        self.group.Commit()

    def stop(self):
        self.group.Reset()


# Remaining code is for testing browser and announcer

def _poll_and_print(poller, socket, timeout):
    while True:
        socks = dict(poller.poll(timeout))
        if socket in socks and socks[socket] == zmq.POLLIN:
            print socket.recv()
        else:
            break

if __name__ == '__main__':
    context = zmq.Context()

    # Start browser
    browser = Browser(context)
    browser.start()
    socket = browser.socket

    # Announce local service
    announcer = Announcer("localkaimu", 9999)
    announcer.start()

    poller = zmq.Poller()
    poller.register(socket, zmq.POLLIN)

    # Show new service announcement
    _poll_and_print(poller, socket, 1000)

    announcer.stop()

    # Show service removal
    _poll_and_print(poller, socket, 2000)

    browser.stop()
