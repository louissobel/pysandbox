import __builtin__
from types import FrameType
from sys import _getframe, version_info
import sys

from sandbox import BlockedFunction, USE_CPYTHON_HACKS
from .cpython import dictionary_of
from .safe_open import _safe_open
from .safe_import import _safe_import
from .restorable_dict import RestorableDict
from .proxy import readOnlyError, createObjectProxy
if USE_CPYTHON_HACKS:
    from .cpython_hack import set_frame_builtins, set_interp_builtins

# Use a blacklist instead of a whitelist policy because __builtins__ HAVE TO
# inherit from dict: Python/ceval.c uses PyDict_SetItem() and an inlined
# version of PyDict_GetItem().
#
# Don't proxy __getattr__ because I suppose that __builtins__ only contains
# safe functions (not mutable objects).
class ReadOnlyBuiltins(dict):
    __slots__ = tuple()

    def clear(self):
        readOnlyError()

    def __delitem__(self, key):
        readOnlyError()

    def pop(self, key, default=None):
        readOnlyError()

    def popitem(self):
        readOnlyError()

    def setdefault(self, key, value):
        readOnlyError()

    def __setitem__(self, key, value):
        readOnlyError()

    def __setslice__(self, start, end, value):
        readOnlyError()

    def update(self, dict, **kw):
        readOnlyError()

class CleanupBuiltins:
    """
    Deny unsafe builtins functions.
    """
    def __init__(self):
        self.get_frame_builtins = dictionary_of(FrameType)['f_builtins'].__get__
        self.builtin_dict = RestorableDict(__builtin__.__dict__)

    def enable(self, sandbox):
        config = sandbox.config

        # Get frame builtins
        self.frame = _getframe(2)
        self.builtins_dict = self.get_frame_builtins(self.frame)

        # Get module list
        self.modules_dict = []
        for name, module in sys.modules.iteritems():
            if module is None:
                continue
            if '__builtins__' not in module.__dict__:
                # builtin modules have no __dict__ attribute
                continue
            if name == "__main__":
                 # __main__ is a special case
                continue
            self.modules_dict.append(module.__dict__)
        self.main_module = sys.modules['__main__']

        # Replace open and file functions
        open_whitelist = config.open_whitelist
        safe_open = _safe_open(open_whitelist)
        self.builtin_dict['open'] = safe_open
        if version_info < (3, 0):
            self.builtin_dict['file'] = safe_open

        # Replace __import__ function
        import_whitelist = config.import_whitelist
        self.builtin_dict['__import__'] = _safe_import(__import__, import_whitelist)

        # Replace exit function
        if 'exit' not in config.features:
            def safe_exit(code=0):
                raise BlockedFunction("exit")
            self.builtin_dict['exit'] = safe_exit
            del self.builtin_dict['SystemExit']

        # Replace help function
        help_func = self.builtin_dict.dict.get('help')
        if help_func:
            if 'help' in config.features:
                self.builtin_dict['help'] = createObjectProxy(help_func)
            else:
                del self.builtin_dict['help']

        # Make builtins read only (enable restricted mode)
        safe_builtins = ReadOnlyBuiltins(self.builtin_dict.dict)
        if USE_CPYTHON_HACKS:
            set_frame_builtins(self.frame, safe_builtins)
            if not config.cpython_restricted:
                set_interp_builtins(self.frame, safe_builtins)
        for module_dict in self.modules_dict:
            module_dict['__builtins__'] = safe_builtins
        self.main_module.__dict__['__builtins__'] = safe_builtins

    def disable(self, sandbox):
        # Restore builtin functions
        self.builtin_dict.restore()

        # Restore modifiable builtins
        if USE_CPYTHON_HACKS:
            set_frame_builtins(self.frame, self.builtins_dict)
            if not sandbox.config.cpython_restricted:
                set_interp_builtins(self.frame, self.builtins_dict)
        for module_dict in self.modules_dict:
            module_dict['__builtins__'] = self.builtins_dict
        self.main_module.__dict__['__builtins__'] = __builtin__

