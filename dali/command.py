"""Declaration of base types for dali commands and their responses."""

from __future__ import unicode_literals
from dali import address
from dali import frame

class CommandTracker(type):
    """Metaclass keeping track of all the types of Command we understand."""

    def __init__(cls, name, bases, attrs):
        if not hasattr(cls, '_commands'):
            cls._commands = []
        else:
            cls._commands.append(cls)

    @classmethod
    def commands(cls):
        """
        :return: List of known commands if there's any
        """
        return cls._commands

class MissingResponse(Exception):
    """Response was absent where a response was expected."""

class ResponseError(Exception):
    """Response had unexpected framing error."""

class Response(object):
    """Some DALI commands cause a response from the addressed devices.

    The response is either an 8-bit backward frame encoding 8-bit data
    or 0xff for "Yes", or a lack of response encoding "No".  If
    multiple devices respond at once the backward frame may be
    received with a framing error; this shall be interpreted as "more
    than one device answered "Yes".

    Initialise this class by passing a BackwardFrame object, or None
    if there was no response.
    """

    _expected = False
    _error_acceptable = False
    def __init__(self, val):
        if val is not None and not isinstance(val, frame.BackwardFrame):
            raise TypeError("Response must be passed None or a BackwardFrame")
        self._value = val

    @property
    def value(self):
        if self._value is None and self._expected:
            raise MissingResponse
        if self._value and self._value.error and not self._error_acceptable:
            raise ResponseError
        return self._value

    def __unicode__(self):
        try:
            return unicode(self.value)
        except MissingResponse or ResponseError as e:
            return unicode(e)

class YesNoResponse(Response):
    _error_acceptable = True
    @property
    def value(self):
        return self._value is not None

class BitmapResponseBitDict(type):
    """Metaclass adding dict of status bits."""
    def __init__(cls, name, bases, attrs):
        if hasattr(cls, "bits"):
            bd = {}
            bit = 0
            for b in cls.bits:
                if b:
                    mangled = b.replace(' ','_').replace('-','')
                    bd[mangled] = bit
                bit = bit + 1
            cls._bit_properties = bd

class BitmapResponse(Response):
    """A response that consists of several named bits.

    Bits are listed in subclasses with the least-sigificant bit first.
    """
    __metaclass__ = BitmapResponseBitDict
    _expected = True
    bits = []
    @property
    def status(self):
        if self._value is None:
            raise MissingResponse
        if self._value.error:
            return ["response received with framing error"]
        v = self._value[7:0]
        l = []
        for b in self.bits:
            if v & 0x01 and b:
                l.append(b)
            v = (v >> 1)
        return l
    @property
    def error(self):
        if self._value is None:
            return False
        return self._value.error
    def __getattr__(self, name):
        if name in self._bit_properties:
            if self._value is None:
                return
            if self._value.error:
                return
            return self._value[self._bit_properties[name]]
        raise AttributeError
    def __unicode__(self):
        try:
            return ",".join(self.status)
        except Exception as e:
            return unicode(e)

class Command(object):
    """A command frame.

    Subclasses must provide a class method "from_frame" which, when
    passed a Frame returns a new instance of the class corresponding
    to that command, or "None" if there is no match.
    """
    __metaclass__ = CommandTracker

    _isconfig = False
    _isquery = False
    _response = None
    _devicetype = 0

    def __init__(self, f):
        assert isinstance(f,frame.ForwardFrame)
        self._data = f

    @classmethod
    def from_frame(cls, f, devicetype=0):
        """Return a Command instance corresponding to the supplied frame.

        If the device type the command is intended for is known
        (i.e. the previous command was EnableDeviceType(foo)) then
        specify it here.

        :parameter frame: a forward frame
        :parameter devicetype: type of device frame is intended for

        :returns: Return a Command instance corresponding to the
        frame.  Returns None if there is no match.
        """
        if cls != Command:
            return

        for dc in cls._commands:
            if dc._devicetype != devicetype:
                continue
            r = dc.from_frame(f)
            if r:
                return r

        # At this point we can simply wrap the frame.  We don't know
        # what kind of command this is (config, query, etc.) so we're
        # unlikely ever to want to transmit it!
        return cls(f)

    @property
    def frame(self):
        """The forward frame to be transmitted for this command."""
        return self._data

    @property
    def is_config(self):
        """Is this a configuration command?  (Does it need repeating to
        take effect?)
        """
        return self._isconfig

    @property
    def is_query(self):
        """Does this command return a result?"""
        return self._isquery

    @property
    def response(self):
        """If this command returns a result, use this class for the response.
        """
        return self._response

    @staticmethod
    def _check_destination(destination):
        """Check that a valid destination has been specified.

        destination can be a dali.device.Device object with
        _addressobj attribute, a dali.address.Address object with
        add_to_frame method, or an integer which will be wrapped in a
        dali.address.Address object.
        """
        if hasattr(destination, "_addressobj"):
            destination = destination._addressobj
        if isinstance(destination, int):
            destination = address.Short(destination)
        if hasattr(destination, "add_to_frame"):
            return destination
        raise ValueError("destination must be an integer, dali.device.Device "
                         "object or dali.address.Address object")

    def __unicode__(self):
        joined = ":".join("{:02x}".format(c) for c in self._data.as_byte_sequence)
        return "({0}){1}".format(type(self), joined)


# XXX Rename to StandardCommand for consistency with IEC 62386-102?
class GeneralCommand(Command):
    """A standard command as defined in Table 15 of IEC 62386-102

    A command addressed to control gear that has a destination address
    and which is not a direct arc power command.  Optionally has a
    4-bit parameter which is used to specify group or scene as
    appropriate.

    The commands are declared as subclasses which override _cmdval to
    specify the opcode byte and override _hasparam to True if the
    4-bit parameter is to be used as the least significant 4 bits of
    the opcode byte.
    """
    _cmdval = None
    _hasparam = False
    _framesize = 16

    def __init__(self, destination, *args):
        if self._cmdval is None:
            raise NotImplementedError

        if self._hasparam:
            if len(args) != 1:
                raise TypeError(
                    "%s.__init__() takes exactly 3 arguments (%d given)" % (
                        self.__class__.__name__, len(args) + 2))

            param = args[0]

            if not isinstance(param, int):
                raise ValueError("param must be an integer")

            if param < 0 or param > 15:
                raise ValueError("param must be in the range 0..15")

            self.param = param

        else:
            if len(args) != 0:
                raise TypeError(
                    "%s.__init__() takes exactly 2 arguments (%d given)" % (
                        self.__class__.__name__, len(args) + 2))
            param = 0

        self.destination = self._check_destination(destination)

        f = frame.ForwardFrame(16, 0x100 | self._cmdval | param)
        self.destination.add_to_frame(f)

        Command.__init__(self, f)

    @classmethod
    def from_frame(cls, frame):
        if cls == GeneralCommand:
            return
        if len(frame) != 16:
            return
        if not frame[8]:
            # It's a direct arc power control command
            return
        b = frame[7:0]

        if cls._hasparam:
            if b & 0xf0 != cls._cmdval:
                return
        else:
            if b != cls._cmdval:
                return

        addr = address.from_frame(frame)

        if addr is None:
            return

        if cls._hasparam:
            return cls(addr, b & 0x0f)

        return cls(addr)

    def __unicode__(self):
        if self._hasparam:
            return "%s(%s,%s)" % (self.__class__.__name__, self.destination,
                                   self.param)
        return "%s(%s)" % (self.__class__.__name__, self.destination)


class ConfigCommand(GeneralCommand):
    """Configuration commands must be transmitted twice within 100ms,
    with no other commands addressing the same ballast being
    transmitted in between.
    """
    _isconfig = True


class SpecialCommand(Command):
    """A special command as defined in Table 16 of IEC 62386-102.

    Special commands are broadcast and are received by all devices."""
    _hasparam = False

    def __init__(self, *args):
        if self._hasparam:
            if len(args) != 1:
                raise TypeError(
                    "{}.__init__() takes exactly 2 arguments ({} given)".format(
                        self.__class__.__name__, len(args) + 1))
            param = args[0]
            if not isinstance(param, int):
                raise ValueError("param must be an int")
            if param < 0 or param > 255:
                raise ValueError("param must be in range 0..255")
            self.param = param
        else:
            if len(args) != 0:
                raise TypeError(
                    "{}.__init__() takes exactly 1 arguments ({} given)".format(
                        self.__class__.__name__, len(args) + 1))
            param = 0
        self.param = param

    @classmethod
    def from_frame(cls, frame):
        if cls == SpecialCommand:
            return
        if len(frame) != 16:
            return
        if frame[15:8] == cls._cmdval:
            if cls._hasparam:
                return cls(frame[7:0])
            else:
                if frame[7:0] == 0:
                    return cls()

    @property
    def frame(self):
        return frame.ForwardFrame(16, (self._cmdval, self.param))

    def __unicode__(self):
        if self._hasparam:
            return "{}({})".format(self.__class__.__name__, self.param)
        return "{}()".format(self.__class__.__name__)


class ShortAddrSpecialCommand(SpecialCommand):
    """A special command that has a short address as its parameter."""

    def __init__(self, address):
        if not isinstance(address, int):
            raise ValueError("address must be an integer")
        if address < 0 or address > 63:
            raise ValueError("address must be in the range 0..63")
        self.address = address

    @property
    def frame(self):
        return frame.ForwardFrame(16, (self._cmdval, (self.address << 1) | 1))

    @classmethod
    def from_frame(cls, frame):
        if cls == ShortAddrSpecialCommand:
            return
        if len(frame) != 16:
            return
        if frame[15:8] == cls._cmdval:
            if frame[7] is False and frame[0] is True:
                return cls(frame[6:1])

    def __unicode__(self):
        return "{}({})".format(self.__class__.__name__, self.address)


class QueryCommand(GeneralCommand):
    """Query commands are answered with "Yes", "No" or 8-bit information.

    "Yes" is encoded as 0xff (255)
    "No" is encoded as no response

    Query commands addressed to more than one ballast may receive
    invalid answers as all ballasts addressed will answer.  It may be
    useful to do this to check whether any ballast in a group provides
    a "Yes" response, for example to "QueryLampFailure".
    """
    _isquery = True
    _response = Response


from_frame = Command.from_frame
