from http.cookies import SimpleCookie
from collections import namedtuple, Mapping
from itertools import product, chain
import time
import random
import json

from .http import Filter, Handler
from . import Context, context_activate, new_event


# Name generation for contexts and sessions
def name_parts():
    """
    This generator will create an endless list of steadily increasing
    name part lists.
    """
    # name parts
    letters = ['alpha', 'beta', 'gamma', 'delta', 'epsilon', 'zeta', 'eta',
               'theta', 'iota', 'kappa', 'lambda', 'mu', 'nu', 'xi', 'omicron',
               'pi', 'rho', 'sigma', 'tau', 'upsilon', 'phi', 'chi', 'psi',
               'omega']
    colours = ['red', 'orange', 'yellow', 'green', 'blue', 'violet']

    # randomize order
    random.shuffle(letters)
    random.shuffle(colours)

    # yield initial sequence (letter-colour)
    parts = [letters, colours]
    yield parts

    # forever generate longer sequences by appending the letter list
    # over and over. Note that this is the *same* letter list, so it will have
    # the exact order.
    while True:
        random.shuffle(letters)
        random.shuffle(colours)
        parts.append(letters)
        yield parts

# construct an iterator that will endlessly generate names:
# 1) for each parts list p in name_parts() we take the cartesian product
# 2) the product iterators are generated by the for...in generator
# 3) we chain these iterators so that when the first is exhausted, we can
#    continue with the second, etc.
# 4) we map the function '-'.join over the list of parts from the chain
names =  map('-'.join, chain.from_iterable((product(*p) for p in name_parts())))


class SessionCookie(Filter):
    """
    The actual HTTP filter that will apply the cookie handling logic to each
    request. This filter defers to the SessionManager with respect to the
    cookie name to use and the activation of sessions.
    """
    def bind(self, manager):
        """Post constructor configuration of filter."""
        self.manager = manager

    def handle(self):
        """
        Determine if a cookie needs to be set and let the session manager
        handle activation.
        """
        cookies = self.request.cookies
        morsel = cookies.get(self.manager.cookie)

        if not morsel:
            # Determine new cookie
            value = self.manager.generate_name()

            # Set new cookie
            cookies[self.manager.cookie] = value
            cookies[self.manager.cookie]['path'] = '/'

            # Send the new cookie as header
            self.request.send_header('Set-Cookie', cookies[self.manager.cookie].output(header=''))
        else:
            value = morsel.value

        self.manager.activate(value)


class Session:
    """
    The Session bookkeeping data.
    """
    def __init__(self, context, seen):
        self.context = context
        self.seen = seen

    def activate(self):
        """Activate the session. Updates last seen time."""
        self.seen = time.time()
        context_activate(self.context)


class SessionManager:
    """
    The SessionManager class. This class is callable so it can be used in place
    of a constructor in the configuration.
    """
    def __init__(self, cookie_name):
        self.sessions = {}
        self.cookie = cookie_name

    def __call__(self, *args, **kwargs):
        handler = SessionCookie(*args, **kwargs)
        handler.bind(self)
        return handler

    def generate_name(self):
        result = next(names)
        while result in self.sessions:
            result = next(names)
        return result

    def _new_session(self, name):
        result = Session(Context(name), time.time())
        result.context.start()
        return result

    def activate(self, name):
        if name not in self.sessions:
            self.sessions[name] = self._new_session(name)
        self.sessions[name].activate()


def GenerateEvent(name):
    """
    This function returns a handler class that creates the named event based
    on the posted JSON data.
    """
    class EventHandler(Handler):
        def handle_POST(self):
            # handle weirdness
            if 'content-length' not in self.request.headers:
                self.request.send_error(411)
                return

            # read content-length header
            length = int(self.request.headers['content-length'])

            # grab data
            data = self.request.rfile.read(length)
            try:
                structured = json.loads(data.decode('utf-8'))
            except ValueError as e:
                self.request.send_error(400, "Bad request: "+str(e))
                return

            if not isinstance(structured, Mapping):
                self.request.send_error(400, "Bad request: expect a JSON object")
                return

            try:
                new_event(name, structured)
            except NotImplementedError:
                # FIXME: logging here with hint about needing a SessionManager
                self.request.send_error(500, "No current context available.")
                return

            self.request.send_response(202)
            self.request.send_header('content-type', 'text/plain; charset=utf-8')
            self.request.send_header('content-length', 0)
            self.request.end_headers()

    return EventHandler


