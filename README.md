kaimu
=====

Tired of the same old problem of how to transfer a file between your
computers in your LAN? Don't want to configure FTP, SSH or Samba? Had
enough of running around with USB-sticks? And how stupid doesn't it
feel when you resort to e-mailing files to yourself just to get them
to the computer right next to you?

`kaimu` enables effortless file sharing by relieving you from any
network configuration whatsoever. Start the application on two
computers connected to your local network. Select a file to share on
one of the computers. **Bam!** You see it on the other computer
instantly. Just for you to press download.

![screenshot](https://raw.github.com/brisad/kaimu/master/screenshot.png)

Goals
-----

These simple goals are driving the design decisions during development:

- Easy to install
- No configuration needed to get started
- User friendly
- Cross-platform

Implementation
--------------

`kaimu` is a wxPython application aiming to be lightweight and having as
few dependencies as possible to make it easy to get started.

Automatic service discovery is made possible by ZeroConf,
currently through Avahi on Linux and Bonjour on Windows. No need for
configuring any IP-addresses or ports.

Network communication is done with ZeroMQ sockets. ZeroMQ makes it
easy to publish file lists to subscribers and to transfer messages.

Current status
--------------

Basic functionality is working but there are things left to do before
it can become useful.

* Split the files into chunks and do the download in the
background with UI feedback.
* Simplify distribution and installation, especially for Windows users.

I am doing this on my free time so development goes slow but
steady. Any help or feedback is very welcome!
