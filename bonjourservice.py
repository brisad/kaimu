import logging
import uuid
import select
import socket
import sys
import threading
import pybonjour
import zmq


regtype  = '_kaimu._tcp'
timeout  = 5
queried  = []
resolved = []

class BonjourBrowser(threading.Thread):
    """Browse services with Bonjour in a new thread.

    Detects addition and removal of services on the local domain.
    When a service is added or removed, that information is written to
    the address passed to the constructor of the BonjourBrowser.

    Since the inter-process transport protocol in ZeroMQ is currently
    not supported in Windows, this class uses inproc transports and
    threads instead of processes.  This has been working fine together
    with wxPython in Windows.
    """

    CHECK_STOP_INTERVAL = 100

    def __init__(self, context, address):
        super(BonjourBrowser, self).__init__()
        self.context = context
        self.address = address
        self.ctrladdr = "inproc://browserctrl-" + str(uuid.uuid4())[:13]
        self.resolve_data = {}

    def query_record_callback(self, sdRef, flags, interfaceIndex, errorCode,
                              fullname, rrtype, rrclass, rdata, ttl):
        if errorCode == pybonjour.kDNSServiceErr_NoError:
            logging.debug('  IP         = %s', socket.inet_ntoa(rdata))
            self.resolve_data['address'] = socket.inet_ntoa(rdata)
            queried.append(True)

    def resolve_callback(self, sdRef, flags, interfaceIndex, errorCode,
                         fullname, hosttarget, port, txtRecord):
        if errorCode != pybonjour.kDNSServiceErr_NoError:
            return

        logging.debug('Resolved service:')
        logging.debug('  fullname   = %s', fullname)
        logging.debug('  hosttarget = %s', hosttarget)
        logging.debug('  port       = %s', port)

        self.resolve_data['port'] = port

        query_sdRef = \
          pybonjour.DNSServiceQueryRecord(interfaceIndex=interfaceIndex,
                                          fullname=hosttarget,
                                          rrtype=pybonjour.kDNSServiceType_A,
                                          callBack=self.query_record_callback)

        try:
            while not queried:
                ready = select.select([query_sdRef], [], [], timeout)
                if query_sdRef not in ready[0]:
                    logging.warning('Query record timed out')
                    break
                pybonjour.DNSServiceProcessResult(query_sdRef)
            else:
                queried.pop()
        finally:
            query_sdRef.close()

        resolved.append(True)

    def browse_callback(self, sdRef, flags, interfaceIndex, errorCode,
                        serviceName, regtype, replyDomain):
        if errorCode != pybonjour.kDNSServiceErr_NoError:
            return

        if not (flags & pybonjour.kDNSServiceFlagsAdd):
            logging.debug('Service removed: %s', serviceName)
            outgoing = ['R', serviceName]
            logging.debug('Sending: %s', outgoing)
            self.outsock.send_json(outgoing)
            self.outsock.recv()
            return
        else:
            logging.debug('Resolving added service: %s', serviceName)

        self.resolve_data.clear()
        self.resolve_data['name'] = serviceName

        resolve_sdRef = pybonjour.DNSServiceResolve(0,
                                                    interfaceIndex,
                                                    serviceName,
                                                    regtype,
                                                    replyDomain,
                                                    self.resolve_callback)

        try:
            while not resolved:
                ready = select.select([resolve_sdRef], [], [], timeout)
                if resolve_sdRef not in ready[0]:
                    logging.warning('Resolve timed out')
                    logging.warning("Resolve of %s failed", serviceName)
                    break
                pybonjour.DNSServiceProcessResult(resolve_sdRef)
            else:
                try:
                    outgoing = ['N', self.resolve_data['name'],
                                self.resolve_data['address'],
                                self.resolve_data['port']]
                except KeyError:
                    logging.warning("Resolve of %s failed", serviceName)
                else:
                    logging.debug('Sending: %s', outgoing)
                    self.outsock.send_json(outgoing)
                    self.outsock.recv()
                resolved.pop()
        finally:
            resolve_sdRef.close()

    def run(self):
        self.outsock = self.context.socket(zmq.REQ)
        self.outsock.connect(self.address)

        self.ctrlsock = self.context.socket(zmq.PAIR)
        self.ctrlsock.bind(self.ctrladdr)

        self.poller = zmq.Poller()
        self.poller.register(self.ctrlsock, zmq.POLLIN)

        browse_sdRef = pybonjour.DNSServiceBrowse(regtype = regtype,
                                          callBack = self.browse_callback)

        try:
            try:
                while True:
                    socks = dict(self.poller.poll(0))
                    if self.ctrlsock in socks and \
                       socks[self.ctrlsock] == zmq.POLLIN:
                        logging.debug('Browser stop signal received')
                        break
                    ready = select.select([browse_sdRef], [], [],
                                          self.CHECK_STOP_INTERVAL / 1000.)
                    if browse_sdRef in ready[0]:
                        pybonjour.DNSServiceProcessResult(browse_sdRef)
            except KeyboardInterrupt:
                pass
        finally:
            browse_sdRef.close()

    def stop(self):
        sock = self.context.socket(zmq.PAIR)
        sock.connect(self.ctrladdr)
        sock.send("STOP")


class BonjourAnnouncer(object):
    """Announce a kaimu service with Bonjour."""

    def __init__(self, name, port):
        super(BonjourAnnouncer, self).__init__()
        self.name = name
        self.port = port
        self.registered = False

    def start(self):
        def register_callback(sdRef, flags, errorCode, name, regtype, domain):
            if errorCode == pybonjour.kDNSServiceErr_NoError:
                logging.debug('Registered service:')
                logging.debug('  name    = %s', name)
                logging.debug('  regtype = %s', regtype)
                logging.debug('  domain  = %s', domain)
                self.name = name
                self.registered = True

        self.sdRef = pybonjour.DNSServiceRegister(name = self.name,
                                                 regtype = regtype,
                                                 port = self.port,
                                                 callBack = register_callback)

        while not self.registered:
            ready = select.select([self.sdRef], [], [])
            if self.sdRef in ready[0]:
                pybonjour.DNSServiceProcessResult(self.sdRef)

    def stop(self):
        self.sdRef.close()


if __name__ == '__main__':
    # Create context, socket and address
    context = zmq.Context()
    s = context.socket(zmq.REP)
    addr = "inproc://kaimubrowser-" + str(uuid.uuid4())[:13]
    s.bind(addr)

    # Start browser
    browser = BonjourBrowser(context, addr)
    browser.start()

    # Announce local service
    announcer = BonjourAnnouncer("localkaimu", 9999)
    announcer.start()

    # Show new service announcement
    print s.recv()
    s.send("OK")

    announcer.stop()

    # Show service removal
    print s.recv()
    s.send("OK")

    browser.stop()
