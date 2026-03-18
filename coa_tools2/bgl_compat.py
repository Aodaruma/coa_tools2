"""
Compatibility layer for the removed `bgl` module in newer Blender versions.
"""

try:
    import bgl as _bgl
except ModuleNotFoundError:
    _bgl = None


class _BGLStub:
    GL_BLEND = 0
    GL_LINE_SMOOTH = 0
    GL_QUADS = 0
    GL_LINE_STRIP = 0

    @staticmethod
    def _noop(*_args, **_kwargs):
        return None

    def __getattr__(self, _name):
        return self._noop


HAS_BGL = _bgl is not None
bgl = _bgl if HAS_BGL else _BGLStub()
