"""Registers the undoable `ribbonfy` command.

    cmds.ribbonfy(direction="auto", spacing="edge", keepPosition=True, preserveDensity=True)

setUVs isn't undoable on its own, so the command keeps the old and new UVs and
swaps them on undo/redo.
"""
import os
import sys

import maya.api.OpenMaya as om

# Make the ribbonfy package importable even before Maya picks up the module file.
try:
    _SCRIPTS = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
    if os.path.isdir(_SCRIPTS) and _SCRIPTS not in sys.path:
        sys.path.append(_SCRIPTS)
except NameError:
    pass   # __file__ undefined: rely on the module file / installer having set the path

from ribbonfy import __version__  # noqa: E402


def _maya_io():
    """The current ribbonfy.maya_io. Looked up on every call instead of once at
    import, so reloading the ribbonfy package in a live session takes effect even
    though Maya keeps this plug-in module cached."""
    import importlib
    return importlib.import_module("ribbonfy.maya_io")

CMD_NAME = "ribbonfy"


def maya_useNewAPI():
    """Tells Maya this plugin uses the Python API 2.0."""


class StraightenCommand(om.MPxCommand):

    def __init__(self):
        om.MPxCommand.__init__(self)
        self._edits = []

    @staticmethod
    def creator():
        return StraightenCommand()

    @staticmethod
    def new_syntax():
        syntax = om.MSyntax()
        syntax.addFlag("-d", "-direction", om.MSyntax.kString)
        syntax.addFlag("-sp", "-spacing", om.MSyntax.kString)
        syntax.addFlag("-kp", "-keepPosition", om.MSyntax.kBoolean)
        syntax.addFlag("-pd", "-preserveDensity", om.MSyntax.kBoolean)
        return syntax

    def doIt(self, args):
        db = om.MArgDatabase(self.syntax(), args)
        direction = db.flagArgumentString("-d", 0) if db.isFlagSet("-d") else "auto"
        spacing = db.flagArgumentString("-sp", 0) if db.isFlagSet("-sp") else "edge"
        keep = db.flagArgumentBool("-kp", 0) if db.isFlagSet("-kp") else True
        density = db.flagArgumentBool("-pd", 0) if db.isFlagSet("-pd") else True
        if direction not in ("auto", "u", "v"):
            raise ValueError("direction must be auto, u or v")
        if spacing not in ("edge", "uniform"):
            raise ValueError("spacing must be edge or uniform")

        maya_io = _maya_io()
        self._edits, report = maya_io.compute(direction, spacing, keep, density)
        maya_io.LAST_REPORT = report
        self.redoIt()
        self.setResult(report.summary())

    def redoIt(self):
        for edit in self._edits:
            edit.redo()

    def undoIt(self):
        for edit in reversed(self._edits):
            edit.undo()

    def isUndoable(self):
        return bool(self._edits)


def initializePlugin(plugin):
    fn = om.MFnPlugin(plugin, "Brayan Fernandez", __version__)
    fn.registerCommand(CMD_NAME, StraightenCommand.creator, StraightenCommand.new_syntax)


def uninitializePlugin(plugin):
    om.MFnPlugin(plugin).deregisterCommand(CMD_NAME)
