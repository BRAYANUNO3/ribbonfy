"""Installer, run by drag_to_install.mel.

Copies the package to Documents/maya/modules/ribbonfy, writes ribbonfy.mod,
loads the plug-in and adds a Ribbonfy shelf. Running it again updates in place.
"""
import os
import shutil
import sys

import maya.cmds as cmds
import maya.mel as mel

from ribbonfy import __version__

SHELF = "Ribbonfy"
BUTTON_LABEL = "Ribbonfy"
LEGACY_LABELS = ("uvkit",)          # shelf buttons from before the rename
COPY_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".git", ".gitignore", ".p4config", ".p4ignore", "docs", "tests")


def _modules_dir():
    path = os.path.join(cmds.internalVar(userAppDir=True), "modules")
    if not os.path.isdir(path):
        os.makedirs(path)
    return os.path.normpath(path).replace("\\", "/")


def _copy_package(source, target):
    """Copy the download into the modules folder (replacing an older copy)."""
    if os.path.normcase(os.path.abspath(source)) == os.path.normcase(os.path.abspath(target)):
        return target                                   # dropped from the installed copy itself
    if os.path.isdir(target):
        shutil.rmtree(target)
    shutil.copytree(source, target, ignore=COPY_IGNORE)
    return target


def _write_module_file(root):
    mod_path = os.path.join(_modules_dir(), "ribbonfy.mod")
    with open(mod_path, "w") as f:
        f.write("+ ribbonfy %s %s\n" % (__version__, root))
    return mod_path


def _unload_plugin():
    if cmds.pluginInfo("ribbonfy_plugin", query=True, loaded=True):
        try:
            cmds.unloadPlugin("ribbonfy_plugin", force=True)
        except RuntimeError:
            pass


def _fresh_import_path(scripts):
    """Make sure the installed copy is the one Python imports."""
    wanted = os.path.normcase(scripts)
    sys.path[:] = [p for p in sys.path if os.path.normcase(p.replace("\\", "/")) != wanted]
    sys.path.insert(0, scripts)
    for name in [k for k in sys.modules if k == "ribbonfy" or k.startswith("ribbonfy.")]:
        del sys.modules[name]


def _build_shelf(root):
    """Create (or rebuild) the Ribbonfy shelf tab with its button, then save shelves."""
    shelf_top = mel.eval("$tmp = $gShelfTopLevel")
    tabs = cmds.tabLayout(shelf_top, query=True, childArray=True) or []

    # Remove buttons left over from the old name, on any shelf.
    for tab in tabs:
        for child in cmds.shelfLayout(tab, query=True, childArray=True) or []:
            if cmds.objectTypeUI(child) == "shelfButton" and \
                    cmds.shelfButton(child, query=True, label=True) in LEGACY_LABELS:
                cmds.deleteUI(child)

    if SHELF in tabs:
        for child in cmds.shelfLayout(SHELF, query=True, childArray=True) or []:
            cmds.deleteUI(child)
    else:
        mel.eval('addNewShelfTab "%s"' % SHELF)

    icon = root + "/scripts/ribbonfy/icons/logo.svg"
    cmds.shelfButton(parent=SHELF, label=BUTTON_LABEL, annotation="Ribbonfy: straighten UVs in one click",
                     image=icon if os.path.isfile(icon) else "pythonFamily.png",
                     sourceType="python", command="import ribbonfy.ui; ribbonfy.ui.show()")
    cmds.tabLayout(shelf_top, edit=True, selectTab=SHELF)
    mel.eval('saveAllShelves "%s"' % shelf_top)


def install(source):
    source = os.path.normpath(source).replace("\\", "/")
    root = _modules_dir() + "/ribbonfy"

    _unload_plugin()                                    # so an update can replace the files
    _copy_package(source, root)
    _write_module_file(root)

    scripts = root + "/scripts"
    _fresh_import_path(scripts)

    plugin = root + "/plug-ins/ribbonfy_plugin.py"
    cmds.loadPlugin(plugin, quiet=True)
    cmds.pluginInfo(plugin, edit=True, autoload=True)

    _build_shelf(root)

    cmds.inViewMessage(assistMessage="Ribbonfy %s installed. Click its button on the <hl>Ribbonfy</hl> shelf." % __version__,
                       position="topCenter", fade=True)
    print("Ribbonfy %s installed to %s" % (__version__, root))
