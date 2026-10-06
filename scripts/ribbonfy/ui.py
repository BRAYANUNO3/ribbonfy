"""Ribbonfy panel. Open with: import ribbonfy.ui; ribbonfy.ui.show()"""
import os

try:
    from PySide6 import QtCore, QtGui, QtWidgets          # Maya 2025+
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets          # Maya 2022-2024

import maya.api.OpenMaya as om
import maya.cmds as cmds
from maya.app.general.mayaMixin import MayaQWidgetDockableMixin

from ribbonfy import __version__, maya_io

WINDOW_NAME = "ribbonfyWindow"
DEFAULT_WIDTH = 340             # compact floating panel; users can still resize or dock it
ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")
README = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "README.md"))
_window = None

THEME = {
    "window": "#353535",      # panel background
    "header": "#2a2a2a",      # top bar and section headers
    "frame": "#3d3d3d",       # inside a section
    "field": "#222222",       # button groups, the log
    "border": "#262626",
    "text": "#dddddd",
    "muted": "#9a9a9a",
    "hover": "#4a4a4a",
    "select": "#5285a6",      # steel blue: checked options, active frame, main button
    "select_hover": "#5f93b5",
    "select_down": "#46738f",
    "frame_active": "#5d8fb3",
    "warn": "#e2a557",
}

STYLE = """
QWidget#ribbonfyRoot { background: %(window)s; }
QWidget#topBar { background: %(header)s; }
QLabel#brand { color: %(text)s; font-size: 13px; font-weight: bold; letter-spacing: 1px; }
QLabel#version { color: %(muted)s; font-size: 10px; }
QToolButton#iconOnly { background: transparent; border: none; border-radius: 3px; padding: 2px; }
QToolButton#iconOnly:hover { background: %(hover)s; }

QFrame#section { background: %(frame)s; border: 1px solid %(border)s; border-radius: 3px; }
QFrame#section[active="true"] { border: 1px solid %(frame_active)s; }
QFrame#sectionHeader { background: %(header)s; border: none; border-top-left-radius: 3px; border-top-right-radius: 3px; }
QFrame#sectionHeader:hover { background: #303030; }
QLabel#sectionTitle { color: %(text)s; font-weight: bold; letter-spacing: 1px; }
QLabel#selection { color: %(text)s; font-weight: bold; }

QWidget#group { background: %(field)s; border: 1px solid %(border)s; border-radius: 3px; }
QToolButton#opt { background: transparent; border: none; border-radius: 2px; }
QToolButton#opt:hover { background: %(hover)s; }
QToolButton#opt:checked { background: %(select)s; }

QPushButton#primary { background: %(select)s; color: white; border: 1px solid #3f6a85; border-radius: 3px;
                      min-height: 38px; font-weight: bold; letter-spacing: 1px; }
QPushButton#primary:hover { background: %(select_hover)s; }
QPushButton#primary:pressed { background: %(select_down)s; }

QLabel#footer { color: %(muted)s; font-size: 10px; }
QToolTip { background: %(header)s; color: %(text)s; border: 1px solid %(select)s; padding: 4px; }
""" % THEME


def _ensure_plugin():
    if cmds.pluginInfo("ribbonfy_plugin", query=True, loaded=True):
        return
    try:
        cmds.loadPlugin("ribbonfy_plugin", quiet=True)
    except RuntimeError:
        here = os.path.dirname(os.path.abspath(__file__))
        cmds.loadPlugin(os.path.normpath(os.path.join(here, "..", "..", "plug-ins", "ribbonfy_plugin.py")),
                        quiet=True)


def _message(text, warn=False):
    """Short fade-out message at the top of the viewport (warnings also go to the Script Editor)."""
    if warn:
        cmds.warning("Ribbonfy: " + text)
    colour = "#e2a557" if warn else "#dddddd"
    cmds.inViewMessage(assistMessage='<span style="color:%s">%s</span>' % (colour, text),
                       position="topCenter", fade=True, fadeStayTime=2500)


def _icon(name):
    """Blue line icon, switching to its white version when the button is checked."""
    icon = QtGui.QIcon()
    icon.addFile(os.path.join(ICON_DIR, name + ".svg"), QtCore.QSize(), QtGui.QIcon.Normal, QtGui.QIcon.Off)
    on = os.path.join(ICON_DIR, name + "_on.svg")
    if os.path.isfile(on):
        icon.addFile(on, QtCore.QSize(), QtGui.QIcon.Normal, QtGui.QIcon.On)
    return icon


def _icon_label(name, size=16):
    label = QtWidgets.QLabel()
    label.setPixmap(_icon(name).pixmap(size, size))
    return label


def _option_button(icon, tip, checkable=True):
    btn = QtWidgets.QToolButton()
    btn.setObjectName("opt")
    btn.setIcon(_icon(icon))
    btn.setIconSize(QtCore.QSize(18, 18))
    btn.setMinimumSize(34, 30)
    btn.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)   # fill the row
    btn.setCheckable(checkable)
    btn.setToolTip(tip)
    btn.setCursor(QtCore.Qt.PointingHandCursor)
    return btn


def _group(buttons, exclusive):
    """A dark rounded strip holding a row of icon buttons."""
    box = QtWidgets.QWidget()
    box.setObjectName("group")
    box.setAttribute(QtCore.Qt.WA_StyledBackground, True)
    lay = QtWidgets.QHBoxLayout(box)
    lay.setContentsMargins(2, 2, 2, 2)
    lay.setSpacing(2)
    group = QtWidgets.QButtonGroup(box)
    group.setExclusive(exclusive)
    for i, btn in enumerate(buttons):
        group.addButton(btn, i)
        lay.addWidget(btn)
    return box, group


def _choice(options):
    """Exclusive icon group. options: (icon, key, tooltip); the first starts checked."""
    buttons = []
    for i, (icon, key, tip) in enumerate(options):
        btn = _option_button(icon, tip)
        btn.setProperty("key", key)
        btn.setChecked(i == 0)
        buttons.append(btn)
    return _group(buttons, exclusive=True)


class _Header(QtWidgets.QFrame):
    clicked = QtCore.Signal()

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.clicked.emit()
        super(_Header, self).mousePressEvent(event)


class Section(QtWidgets.QFrame):
    """A framed block with an icon header that folds its contents away when clicked."""

    def __init__(self, title, icon, tip="", parent=None, expanded=True, stretch=False):
        super(Section, self).__init__(parent)
        self.setObjectName("section")
        self._stretch = stretch
        self._expanded = expanded
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.header = _Header()
        self.header.setObjectName("sectionHeader")
        self.header.setCursor(QtCore.Qt.PointingHandCursor)
        self.header.setToolTip(tip or "Click to fold or unfold")
        head = QtWidgets.QHBoxLayout(self.header)
        head.setContentsMargins(8, 6, 8, 6)
        head.setSpacing(7)
        self.arrow = QtWidgets.QLabel()
        self.arrow.setStyleSheet("color: %s; font-size: 9px;" % THEME["muted"])
        head.addWidget(self.arrow)
        head.addWidget(_icon_label(icon))
        title_label = QtWidgets.QLabel(title.upper())
        title_label.setObjectName("sectionTitle")
        head.addWidget(title_label)
        head.addStretch(1)
        self.header.clicked.connect(lambda: self._toggle(not self._expanded))
        outer.addWidget(self.header)

        self.body = QtWidgets.QWidget()
        self.content = QtWidgets.QVBoxLayout(self.body)
        self.content.setContentsMargins(10, 8, 10, 10)
        self.content.setSpacing(8)
        outer.addWidget(self.body)
        self._toggle(expanded)

    def _toggle(self, expanded):
        self._expanded = expanded
        self.arrow.setText(u"▼" if expanded else u"▶")
        self.body.setVisible(expanded)
        grow = QtWidgets.QSizePolicy.Expanding if (expanded and self._stretch) else QtWidgets.QSizePolicy.Maximum
        self.setSizePolicy(QtWidgets.QSizePolicy.Preferred, grow)

    def set_active(self, active):
        self.setProperty("active", "true" if active else "false")
        self.style().unpolish(self)
        self.style().polish(self)


class RibbonfyWindow(MayaQWidgetDockableMixin, QtWidgets.QWidget):

    def __init__(self, parent=None):
        super(RibbonfyWindow, self).__init__(parent=parent)
        self.setObjectName(WINDOW_NAME)
        self.setWindowTitle("Ribbonfy")
        self.setMinimumWidth(300)
        self._callback = None
        self._refresh_timer = QtCore.QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(120)
        self._refresh_timer.timeout.connect(self._safe_refresh)
        self._build()
        self._refresh_selection()
        self._callback = om.MEventMessage.addEventCallback("SelectionChanged", self._on_selection_changed)

    # ---- layout ----------------------------------------------------------
    def _build(self):
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        root = QtWidgets.QWidget()
        root.setObjectName("ribbonfyRoot")
        root.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        root.setStyleSheet(STYLE)
        outer.addWidget(root)
        lay = QtWidgets.QVBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 6)
        lay.setSpacing(0)

        top = QtWidgets.QWidget()
        top.setObjectName("topBar")
        top.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        top_lay = QtWidgets.QHBoxLayout(top)
        top_lay.setContentsMargins(10, 6, 6, 6)
        top_lay.setSpacing(8)
        top_lay.addWidget(_icon_label("logo", 20))
        brand = QtWidgets.QLabel("RIBBONFY")
        brand.setObjectName("brand")
        top_lay.addWidget(brand)
        top_lay.addStretch(1)
        version = QtWidgets.QLabel("v%s" % __version__)
        version.setObjectName("version")
        top_lay.addWidget(version)
        help_btn = QtWidgets.QToolButton()
        help_btn.setObjectName("iconOnly")
        help_btn.setIcon(_icon("help"))
        help_btn.setIconSize(QtCore.QSize(18, 18))
        help_btn.setToolTip("Open the Ribbonfy guide")
        help_btn.setCursor(QtCore.Qt.PointingHandCursor)
        help_btn.clicked.connect(self._open_help)
        top_lay.addWidget(help_btn)
        lay.addWidget(top)

        lay.addWidget(self._build_straighten(), 1)

        footer = QtWidgets.QLabel("by brayanuno")
        footer.setObjectName("footer")
        footer.setContentsMargins(10, 4, 10, 0)
        lay.addWidget(footer)

    def _build_straighten(self):
        page = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(page)
        lay.setContentsMargins(8, 8, 8, 4)
        lay.setSpacing(6)

        sel = Section("Selection", "selection",
                      "Meshes, groups, faces, edges, vertices or UVs. Every UV shell they touch is straightened.")
        self.selection_label = QtWidgets.QLabel()
        self.selection_label.setObjectName("selection")
        sel.content.addWidget(self.selection_label)
        self.selection_section = sel
        lay.addWidget(sel)

        opts = Section("Settings", "settings",
                       "Hover any icon for what it does. Closed rings, like the open end of a pipe, "
                       "are cut open automatically.")
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(6)
        box, self.direction_group = _choice([
            ("dir_auto", "auto", "Direction: Auto\nFollow each shell's current layout"),
            ("dir_u", "u", "Direction: U\nPut the long side along U (horizontal)"),
            ("dir_v", "v", "Direction: V\nPut the long side along V (vertical)"),
        ])
        row.addWidget(box, 3)
        box, self.spacing_group = _choice([
            ("spacing_edge", "edge", "Spacing: 3D edge lengths\nRows and columns keep real proportions, "
                                     "so textures don't stretch"),
            ("spacing_uniform", "uniform", "Spacing: Uniform\nEvery row and column the same size"),
        ])
        row.addWidget(box, 2)
        self.keep_position = _option_button("keep_position", "Keep shell position\nLeave each shell where it is "
                                                              "instead of moving it to the corner")
        self.preserve_density = _option_button("density", "Preserve texel density\nKeep the same texture "
                                                           "resolution on the shell")
        self.layout_after = _option_button("layout", "Lay out shells\nAfter straightening, pack the shells "
                                                     "into 0-1 so they don't overlap (Maya Layout)")
        self.keep_position.setChecked(True)
        self.preserve_density.setChecked(True)
        self.layout_after.setChecked(False)          # off: don't move shells an artist already arranged
        box, _ = _group([self.keep_position, self.preserve_density, self.layout_after], exclusive=False)
        row.addWidget(box, 3)
        opts.content.addLayout(row)
        lay.addWidget(opts)

        run = QtWidgets.QPushButton("  STRAIGHTEN UVS")
        run.setObjectName("primary")
        run.setIcon(QtGui.QIcon(os.path.join(ICON_DIR, "straighten.svg")))
        run.setIconSize(QtCore.QSize(18, 18))
        run.setToolTip("Straighten every UV shell in the selection")
        run.setCursor(QtCore.Qt.PointingHandCursor)
        run.clicked.connect(self._run)

        lay.addStretch(1)
        lay.addWidget(run)      # main action sits at the bottom of the panel
        return page

    def fit_to_content(self, reset_width=False):
        """Shrink a floating panel to its content so there's no empty space at the bottom.
        reset_width also puts it back to the default width (only done when it opens)."""
        control = WINDOW_NAME + "WorkspaceControl"
        try:
            if cmds.workspaceControl(control, query=True, exists=True) and \
                    cmds.workspaceControl(control, query=True, floating=True):
                self.adjustSize()
                if reset_width:
                    cmds.workspaceControl(control, edit=True, resizeWidth=max(DEFAULT_WIDTH, self.minimumWidth()))
                cmds.workspaceControl(control, edit=True, resizeHeight=self.sizeHint().height())
        except RuntimeError:
            pass

    # ---- behaviour -------------------------------------------------------
    def _open_help(self):
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(README))

    def _on_selection_changed(self, *args):
        # Box-selecting fires many events; count shells once at the end.
        try:
            self._refresh_timer.start()
        except RuntimeError:
            pass   # widget already gone

    def _safe_refresh(self):
        try:
            self._refresh_selection()
        except RuntimeError:
            pass   # widget already gone

    def _refresh_selection(self):
        meshes, shells = maya_io.selection_summary()
        self.selection_section.set_active(bool(meshes))
        if not meshes:
            self.selection_label.setText("Nothing selected")
        else:
            self.selection_label.setText("%d mesh%s  ·  %d UV shell%s" % (
                meshes, "" if meshes == 1 else "es", shells, "" if shells == 1 else "s"))

    def _run(self):
        if not om.MGlobal.getActiveSelectionList().length():
            _message("Select meshes, faces or UV shells first.", warn=True)
            return
        _ensure_plugin()
        cmds.undoInfo(openChunk=True, chunkName="ribbonfy")
        try:
            self._run_steps()
        finally:
            cmds.undoInfo(closeChunk=True)

    def _run_steps(self):
        if not self._resolve_history():
            return
        opts = {
            "direction": self.direction_group.checkedButton().property("key"),
            "spacing": self.spacing_group.checkedButton().property("key"),
            "keepPosition": self.keep_position.isChecked(),
            "preserveDensity": self.preserve_density.isChecked(),
        }
        cmds.waitCursor(state=True)
        maya_io.LAST_REPORT = None
        try:
            result = cmds.ribbonfy(**opts)
        except Exception as exc:
            _message("Ribbonfy failed: %s" % exc, warn=True)
            return
        finally:
            cmds.waitCursor(state=False)
        report = maya_io.LAST_REPORT
        if report is None:
            # The command ran but its report went to another copy of ribbonfy, which
            # happens when an older plug-in is still loaded in this Maya session.
            text = result[0] if isinstance(result, (list, tuple)) and result else (result or "Done")
            _message("%s. Restart Maya to load the latest Ribbonfy." % text, warn=True)
            return
        laid_out = False
        if self.layout_after.isChecked() and report.straightened:
            try:
                maya_io.layout(report)
                laid_out = True
            except Exception as exc:
                _message("Straightened, but layout failed: %s" % exc, warn=True)
                return
        self._finish(report, laid_out)

    def _finish(self, report, laid_out):
        """Show the result in the viewport and select whatever was skipped."""
        text = report.summary() + (", laid out" if laid_out else "")
        if report.skipped:
            picks = []
            for entry in report.skipped:
                picks.extend(maya_io.face_ranges(entry["mesh"], entry["faces"]) if entry["faces"]
                             else [entry["mesh"]])
                where = entry["mesh"] if entry["shell"] is None else "%s shell %d" % (entry["mesh"], entry["shell"])
                print("Ribbonfy skipped %s: %s" % (where, entry["reason"]))
            cmds.select(picks, replace=True)
            text += ". Skipped shells are selected (reasons in the Script Editor)"
        _message(text, warn=bool(report.skipped))

    def _resolve_history(self):
        """Ask before touching construction history. Returns False to cancel the run."""
        with_history = maya_io.meshes_with_history()
        if not with_history:
            return True
        names = [p.split("|")[-1] for p in with_history]
        listed = ", ".join(names[:4]) + (" and %d more" % (len(names) - 4) if len(names) > 4 else "")
        choice = cmds.confirmDialog(
            title="Ribbonfy: construction history",
            message=("%s %s construction history, which would overwrite the new UVs.\n\n"
                     "Delete non-deformer history and continue?"
                     % (listed, "has" if len(names) == 1 else "have")),
            button=["Delete history", "Skip these", "Cancel"],
            defaultButton="Delete history", cancelButton="Cancel", dismissString="Cancel")
        if choice == "Cancel":
            _message("Cancelled. Nothing changed.")
            return False
        if choice == "Delete history":
            maya_io.delete_history(with_history)
        return True

    # ---- cleanup ---------------------------------------------------------
    def cleanup(self):
        try:
            self._refresh_timer.stop()
        except RuntimeError:
            pass
        if self._callback is not None:
            try:
                om.MMessage.removeCallback(self._callback)
            except RuntimeError:
                pass
            self._callback = None

    def dockCloseEventTriggered(self):
        self.cleanup()

    def closeEvent(self, event):
        self.cleanup()
        super(RibbonfyWindow, self).closeEvent(event)


def show():
    """Open (or reopen) the Ribbonfy panel."""
    global _window
    _ensure_plugin()
    if _window is not None:
        _window.cleanup()
    control = WINDOW_NAME + "WorkspaceControl"
    if cmds.workspaceControl(control, query=True, exists=True):
        cmds.workspaceControl(control, edit=True, close=True)
        cmds.deleteUI(control, control=True)
    _window = RibbonfyWindow()
    _window.show(dockable=True, floating=True, width=DEFAULT_WIDTH)
    QtCore.QTimer.singleShot(0, lambda: _window.fit_to_content(reset_width=True))
    return _window
