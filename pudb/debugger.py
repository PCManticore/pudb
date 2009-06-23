#! /usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import division
import urwid
import bdb
from code import InteractiveConsole

try:
    import readline
    import rlcompleter
    HAVE_READLINE = True
except ImportError:
    HAVE_READLINE = False




HELP_TEXT = """\
Welcome to PuDB, the Python Urwid debugger.
-------------------------------------------

Keys:
    n - step over ("next")
    s - step into
    c - continue
    r/f - finish current function
    t - run to cursor
    e - show traceback [post-mortem or in exception state]

    ! - invoke python shell in current environment

    b - toggle breakpoint
    m - open module

    j/k - up/down
    ctrl-u/d - page up/down
    h/l - scroll left/right
    g/G - start/end
    L - go to line
    / - search
    ,/. - search next/previous

    V - focus variables
    S - focus stack
    B - focus breakpoint list
    +/- - grow/shrink sidebar

    f1/?/H - show this help screen

Keys in variables list:

    \ - expand/collapse
    t/r/s - show type/repr/str for this variable
    enter - edit options
    h - toggle highlighting
    w - toggle watching
    * - toggle private members

Keys in stack list:

    enter - jump to frame

Keys in breakpoints view:

    enter - edit breakpoint

License:
--------

PuDB is licensed to you under the MIT/X Consortium license:

Copyright (c) 2009 Andreas Klöckner

Permission is hereby granted, free of charge, to any person
obtaining a copy of this software and associated documentation
files (the "Software"), to deal in the Software without
restriction, including without limitation the rights to use,
copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the
Software is furnished to do so, subject to the following
conditions:

The above copyright notice and this permission notice shall be
included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
OTHER DEALINGS IN THE SOFTWARE.
"""



# debugger interface ----------------------------------------------------------
class Debugger(bdb.Bdb):
    def __init__(self, steal_output=False):
        bdb.Bdb.__init__(self)
        self.ui = DebuggerUI(self)
        self.steal_output = steal_output

        self.setup_state()

        if steal_output:
            raise NotImplementedError("output stealing")
            import sys
            from cStringIO import StringIO
            self.stolen_output = sys.stderr = sys.stdout = StringIO()
            sys.stdin = StringIO("") # avoid spurious hangs

    def enter_post_mortem(self, exc_tuple):
        self.post_mortem = True

    def setup_state(self):
        self.bottom_frame = None
        self.mainpyfile = ''
        self._wait_for_mainpyfile = False
        self.post_mortem = False

    def restart(self):
        self.setup_state()

    def do_clear(self, arg):
        self.clear_bpbynumber(int(arg))

    def set_frame_index(self, index):
        self.curindex = index
        self.curframe, lineno = self.stack[index]
        self.ui.set_current_line(lineno, self.curframe.f_code.co_filename)
        self.ui.set_locals(self.curframe.f_locals)
        self.ui.update_stack()

    def get_shortened_stack(self, frame, tb):
        stack, index = self.get_stack(frame, tb)

        for i, (s_frame, lineno) in enumerate(stack):
            if s_frame is self.bottom_frame and index >= i:
                stack = stack[i:]
                index -= i

        return stack, index

    def interaction(self, frame, exc_tuple=None):
        if exc_tuple is None:
            tb = None
        else:
            tb = exc_tuple[2]

        if frame is None:
            frame = tb.tb_frame

        found_bottom_frame = False
        walk_frame = frame
        while True:
            if walk_frame is self.bottom_frame:
                found_bottom_frame = True
                break
            if walk_frame is None:
                break
            walk_frame = walk_frame.f_back

        if not found_bottom_frame and not self.post_mortem:
            return

        self.stack, index = self.get_shortened_stack(frame, tb)
        if self.post_mortem:
            index = len(self.stack)-1

        self.set_frame_index(index)

        self.ui.call_with_ui(self.ui.interaction, exc_tuple)

    def get_stack_situation_id(self):
        return str(id(self.stack[self.curindex][0].f_code))

    def user_call(self, frame, argument_list):
        """This method is called when there is the remote possibility
        that we ever need to stop in this function."""
        if self._wait_for_mainpyfile:
            return
        if self.stop_here(frame):
            self.interaction(frame)

    def user_line(self, frame):
        """This function is called when we stop or break at this line."""
        if "__exc_tuple__" in frame.f_locals:
            del frame.f_locals['__exc_tuple__']

        if self._wait_for_mainpyfile:
            if (self.mainpyfile != self.canonic(frame.f_code.co_filename)
                or frame.f_lineno<= 0):
                return
            self._wait_for_mainpyfile = False
            self.bottom_frame = frame

        self.interaction(frame)

    def user_return(self, frame, return_value):
        """This function is called when a return trap is set here."""
        frame.f_locals['__return__'] = return_value

        if "__exc_tuple__" not in frame.f_locals:
            self.interaction(frame)

    def user_exception(self, frame, exc_tuple):
        """This function is called if an exception occurs,
        but only if we are to stop at or just below this level."""
        frame.f_locals['__exc_tuple__'] = exc_tuple
        self.interaction(frame, exc_tuple)

    def _runscript(self, filename):
        # Start with fresh empty copy of globals and locals and tell the script
        # that it's being run as __main__ to avoid scripts being able to access
        # the debugger's namespace.
        globals_ = {"__name__" : "__main__", "__file__": filename }
        locals_ = globals_

        # When bdb sets tracing, a number of call and line events happens
        # BEFORE debugger even reaches user's code (and the exact sequence of
        # events depends on python version). So we take special measures to
        # avoid stopping before we reach the main script (see user_line and
        # user_call for details).
        self._wait_for_mainpyfile = 1
        self.mainpyfile = self.canonic(filename)
        statement = 'execfile( "%s")' % filename
        self.run(statement, globals=globals_, locals=locals_)





# UI stuff --------------------------------------------------------------------
from pudb.ui_tools import make_hotkey_markup, labelled_value, \
        SelectableText, SignalWrap, Variable, StackFrame, SourceLine, \
        SearchBox




class MyConsole(InteractiveConsole):
    def __init__(self, locals):
        InteractiveConsole.__init__(self, locals)

        if HAVE_READLINE:
            import os
            import atexit

            histfile = os.path.join(os.environ["HOME"], ".pudbhist")
            if os.access(histfile, os.R_OK):
                readline.read_history_file(histfile)
            atexit.register(readline.write_history_file, histfile)
            readline.parse_and_bind("tab: complete")




class InspectInfo(object):
    def __init__(self):
        self.show_detail = False
        self.display_type = "type"
        self.highlighted = False
        self.watched = False
        self.show_private_members = False




class DebuggerUI(object):
    def __init__(self, dbg):
        self.debugger = dbg
        Attr = urwid.AttrWrap

        self.search_box = None
        self.last_module_filter = ""

        self.inspect_info = {}

        self.source = urwid.SimpleListWalker([])
        self.source_list = urwid.ListBox(self.source)
        self.source_hscroll_start = 0

        self.lhs_col = urwid.Pile([
            ("weight", 1, urwid.AttrWrap(self.source_list, "source"))
            ])

        self.locals = urwid.SimpleListWalker([])
        self.var_list = SignalWrap(
                urwid.ListBox(self.locals))

        self.stack_walker = urwid.SimpleListWalker([])
        self.stack_list = SignalWrap(
                urwid.ListBox(self.stack_walker))

        self.bp_walker = urwid.SimpleListWalker([])
        self.bp_list = SignalWrap(
                urwid.ListBox(self.bp_walker))

        self.rhs_col = urwid.Pile([
            Attr(urwid.Pile([
                ("flow", urwid.Text(make_hotkey_markup("_Variables:"))),
                Attr(self.var_list, "variables"),
                ]), None, "focused sidebar"),
            Attr(urwid.Pile([
                ("flow", urwid.Text(make_hotkey_markup("_Stack:"))),
                Attr(self.stack_list, "stack"),
                ]), None, "focused sidebar"),
            Attr(urwid.Pile([
                ("flow", urwid.Text(make_hotkey_markup("_Breakpoints:"))),
                Attr(self.bp_list, "breakpoint"),
                ]), None, "focused sidebar"),
            ])

        self.columns = urwid.Columns(
                    [
                        ("weight", 1, self.lhs_col),
                        ("weight", 0.5, self.rhs_col),
                        ],
                    dividechars=1)

        self.caption = urwid.Text("")
        header = urwid.AttrWrap(self.caption, "header")
        self.top = SignalWrap(urwid.Frame(
            urwid.AttrWrap(self.columns, "background"),
            header))

        # variable listeners --------------------------------------------------
        def change_var_state(w, size, key):
            var, pos = self.var_list._w.get_focus()

            ssid = self.debugger.get_stack_situation_id()
            id_path_to_iinfo = self.inspect_info.setdefault(ssid, {})
            iinfo = id_path_to_iinfo.setdefault(var.id_path, InspectInfo())

            if key == "\\": iinfo.show_detail = not iinfo.show_detail
            elif key == "t": iinfo.display_type = "type"
            elif key == "r": iinfo.display_type = "repr"
            elif key == "s": iinfo.display_type = "str"
            elif key == "h": iinfo.highlighted = not iinfo.highlighted
            elif key == "w": iinfo.watched = not iinfo.watched
            elif key == "*": iinfo.show_private_members = not iinfo.show_private_members

            self.set_locals(self.debugger.curframe.f_locals)

        def edit_variable_detail(w, size, key):
            var, pos = self.var_list._w.get_focus()

            ssid = self.debugger.get_stack_situation_id()
            id_path_to_iinfo = self.inspect_info.setdefault(ssid, {})
            iinfo = id_path_to_iinfo.setdefault(var.id_path, InspectInfo())

            rb_grp = []
            rb_show_type = urwid.RadioButton(rb_grp, "Show Type",
                    iinfo.display_type == "type")
            rb_show_repr = urwid.RadioButton(rb_grp, "Show repr()",
                    iinfo.display_type == "repr")
            rb_show_str = urwid.RadioButton(rb_grp, "Show str()",
                    iinfo.display_type == "str")

            expanded_checkbox = urwid.CheckBox("Expanded", iinfo.show_detail)
            highlighted_checkbox = urwid.CheckBox("Highlighted", iinfo.highlighted)
            watched_checkbox = urwid.CheckBox("Watched", iinfo.highlighted)
            show_private_checkbox = urwid.CheckBox("Show private members",
                    iinfo.show_private_members)

            lb = urwid.ListBox([
                #labelled_value("Stack Situation: ", ssid),
                labelled_value("Identifier Path: ", var.id_path),
                urwid.Text(""),
                ]+rb_grp+[
                urwid.Text(""),
                expanded_checkbox,
                highlighted_checkbox,
                watched_checkbox,
                show_private_checkbox,
                ])

            if self.dialog(lb, [
                ("OK", True),
                ("Cancel", False),
                ], title="Variable Inspection Options"):

                iinfo.show_detail = expanded_checkbox.get_state()
                iinfo.highlighted = highlighted_checkbox.get_state()
                iinfo.watched = watched_checkbox.get_state()
                iinfo.show_private_members = show_private_checkbox.get_state()

                if rb_show_type.get_state(): iinfo.display_type = "type"
                elif rb_show_repr.get_state(): iinfo.display_type = "repr"
                elif rb_show_str.get_state(): iinfo.display_type = "str"

            self.set_locals(self.debugger.curframe.f_locals)

        self.var_list.listen("\\", change_var_state)
        self.var_list.listen("t", change_var_state)
        self.var_list.listen("r", change_var_state)
        self.var_list.listen("s", change_var_state)
        self.var_list.listen("h", change_var_state)
        self.var_list.listen("w", change_var_state)
        self.var_list.listen("enter", edit_variable_detail)

        # stack listeners -----------------------------------------------------
        def examine_frame(w, size, key):
            _, pos = self.stack_list._w.get_focus()
            self.debugger.set_frame_index(pos)

        self.stack_list.listen("enter", examine_frame)

        # stack listeners -----------------------------------------------------
        def examine_breakpoint(w, size, key):
            _, pos = self.bp_list._w.get_focus()
            bp = self._get_bp_list()[pos]

            if bp.cond is None:
                cond = ""
            else:
                cond = str(bp.cond)

            enabled_checkbox = urwid.CheckBox(
                    "Enabled", bp.enabled)
            cond_edit = urwid.Edit([
                ("label", "Condition:               ")
                ], cond)
            ign_count_edit = urwid.IntEdit([
                ("label", "Ignore the next N times: ")
                ], bp.ignore)

            lb = urwid.ListBox([
                labelled_value("File: ", bp.file),
                labelled_value("Line: ", bp.line),
                labelled_value("Hits: ", bp.hits),
                urwid.Text(""),
                enabled_checkbox,
                urwid.AttrWrap(cond_edit, "value", "value"),
                urwid.AttrWrap(ign_count_edit, "value", "value"),
                ])

            result = self.dialog(lb, [
                ("OK", True),
                ("Cancel", False),
                None,
                ("Delete", "del"),
                ("Location", "loc"),
                ], title="Edit Breakpoint")

            if result == True:
                bp.enabled = enabled_checkbox.get_state()
                bp.ignore = int(ign_count_edit.value())
                cond = cond_edit.get_edit_text()
                if cond:
                    bp.cond = cond
                else:
                    bp.cond = None
            elif result == "loc":
                self.show_line(bp.line, bp.file)
                self.columns.set_focus(0)
            elif result == "del":
                if self.shown_file == bp.file:
                    self.source[bp.line-1].set_breakpoint(False)

                err = self.debugger.clear_break(bp.file, bp.line)
                if err:
                    self.message("Error clearing breakpoint:\n"+ err)

        self.bp_list.listen("enter", examine_breakpoint)

        # top-level listeners -------------------------------------------------
        def end():
            self.quit_event_loop = True

        def next(w, size, key):
            if self.debugger.post_mortem:
                self.message("Post-mortem mode: Can't modify state.")
            else:
                self.debugger.set_next(self.debugger.curframe)
                end()

        def step(w, size, key):
            if self.debugger.post_mortem:
                self.message("Post-mortem mode: Can't modify state.")
            else:
                self.debugger.set_step()
                end()

        def finish(w, size, key):
            if self.debugger.post_mortem:
                self.message("Post-mortem mode: Can't modify state.")
            else:
                self.debugger.set_return(self.debugger.curframe)
                end()


        def cont(w, size, key):
            if self.debugger.post_mortem:
                self.message("Post-mortem mode: Can't modify state.")
            else:
                self.debugger.set_continue()
                end()

        def run_to_cursor(w, size, key):
            if self.debugger.post_mortem:
                self.message("Post-mortem mode: Can't modify state.")
            else:
                sline, pos = self.source.get_focus()
                lineno = pos+1

                from pudb.lowlevel import get_breakpoint_invalid_reason
                invalid_reason = get_breakpoint_invalid_reason(
                        self.shown_file, lineno)

                if invalid_reason is not None:
                    self.message(
                        "Cannot run to the line you indicated, "
                        "for the following reason:\n\n"
                        + invalid_reason)
                else:
                    err = self.debugger.set_break(self.shown_file, pos+1, temporary=True)
                    if err:
                        self.message("Error dealing with breakpoint:\n"+ err)

                    self.debugger.set_continue()
                    end()

        def show_traceback(w, size, key):
            if self.current_exc_tuple is not None:
                from traceback import format_exception

                result = self.dialog(
                        urwid.ListBox([urwid.Text(
                            "".join(format_exception(*self.current_exc_tuple)))]),
                        [
                            ("Close", "close"),
                            ("Location", "location")
                            ],
                        title="Exception Viewer",
                        focus_buttons=True,
                        bind_enter_esc=False)

                if result == "location":
                    self.debugger.set_frame_index(len(self.debugger.stack)-1)

            else:
                self.message("No exception available.")

        def show_output(w, size, key):
            self.screen.stop()
            raw_input("Hit Enter to return:")
            self.screen.start()

        def run_shell(w, size, key):
            self.screen.stop()

            if not hasattr(self, "shell_ret_message_shown"):
                banner = "Hit Ctrl-D to return to PuDB."
                self.shell_ret_message_shown = True
            else:
                banner = ""

            curframe = self.debugger.curframe
            loc = curframe.f_locals.copy()
            loc.update(curframe.f_globals)

            cons = MyConsole(loc)
            cons.interact(banner)
            self.screen.start()

        class RHColumnFocuser:
            def __init__(self, idx):
                self.idx = idx

            def __call__(subself, w, size, key):
                self.columns.set_focus(self.rhs_col)
                self.rhs_col.set_focus(self.rhs_col.widget_list[subself.idx])

        def grow_sidebar(w, size, key):
            _, weight = self.columns.column_types[1]

            if weight < 5:
                weight *= 1.25
                self.columns.column_types[1] = "weight", weight
                self.columns._invalidate()

        def shrink_sidebar(w, size, key):
            _, weight = self.columns.column_types[1]

            if weight > 1/5:
                weight /= 1.25
                self.columns.column_types[1] = "weight", weight
                self.columns._invalidate()

        def move_home(w, size, key):
            self.source.set_focus(0)

        def move_end(w, size, key):
            self.source.set_focus(len(self.source))

        def go_to_line(w, size, key):
            _, line = self.source.get_focus()

            lineno_edit = urwid.IntEdit([
                ("label", "Line number: ")
                ], line+1)

            if self.dialog(
                    urwid.ListBox([ 
                        labelled_value("File :", self.shown_file),
                        urwid.AttrWrap(lineno_edit, "value") 
                        ]),
                    [
                        ("OK", True),
                        ("Cancel", False),
                        ], title="Go to Line Number"):
                lineno = min(max(0, int(lineno_edit.value())-1), len(self.source)-1)
                self.source.set_focus(lineno)

        def move_down(w, size, key):
            w.keypress(size, "down")

        def move_up(w, size, key):
            w.keypress(size, "up")

        def page_down(w, size, key):
            w.keypress(size, "page down")

        def page_up(w, size, key):
            w.keypress(size, "page up")

        def move_up(w, size, key):
            w.keypress(size, "up")
        def scroll_left(w, size, key):
            self.source_hscroll_start = max(
                    0,
                    self.source_hscroll_start - 4)
            for sl in self.source:
                sl._invalidate()

        def scroll_right(w, size, key):
            self.source_hscroll_start += 4
            for sl in self.source:
                sl._invalidate()

        def search(w, size, key):
            if self.search_box is None:
                _, search_start = self.source.get_focus()

                self.search_box = SearchBox(self)
                self.search_attrwrap = urwid.AttrWrap(self.search_box, "value")

                self.lhs_col.item_types.insert(
                        0, ("flow", None))
                self.lhs_col.widget_list.insert( 0, self.search_attrwrap)

                self.columns.set_focus(self.lhs_col)
                self.lhs_col.set_focus(self.search_attrwrap)
            else:
                self.columns.set_focus(self.lhs_col)
                self.lhs_col.set_focus(self.search_attrwrap)
                self.search_box.restart_search()

        def search_next(w, size, key):
            if self.search_box is not None:
                self.search_box.do_search(1)
            else:
                self.message("No previous search term.")

        def search_previous(w, size, key):
            if self.search_box is not None:
                self.search_box.do_search(-1)
            else:
                self.message("No previous search term.")

        def toggle_breakpoint(w, size, key):
            if self.shown_file:
                sline, pos = self.source.get_focus()
                lineno = pos+1

                existing_breaks = self.debugger.get_breaks(
                        self.shown_file, lineno)
                if existing_breaks:
                    err = self.debugger.clear_break(self.shown_file, lineno)
                    sline.set_breakpoint(False)
                else:
                    from pudb.lowlevel import get_breakpoint_invalid_reason
                    invalid_reason = get_breakpoint_invalid_reason(
                            self.shown_file, pos+1)

                    if invalid_reason is not None:
                        do_set = not self.dialog(urwid.ListBox([
                            urwid.Text("The breakpoint you just set may be "
                                "invalid, for the following reason:\n\n"
                                + invalid_reason),
                            ]), [
                            ("Cancel", True),
                            ("Set Anyway", False),
                            ], title="Possibly Invalid Breakpoint",
                            focus_buttons=True)
                    else:
                        do_set = True

                    if do_set:
                        err = self.debugger.set_break(self.shown_file, pos+1)
                        sline.set_breakpoint(True)
                    else:
                        err = None

                if err:
                    self.message("Error dealing with breakpoint:\n"+ err)

                self.update_breakpoints()
            else:
                raise RuntimeError, "no valid current file"

        def pick_module(w, size, key):
            from os.path import splitext

            import sys

            def mod_exists(mod):
                if not hasattr(mod, "__file__"):
                    return False
                filename = mod.__file__

                base, ext = splitext(filename)
                ext = ext.lower()

                from os.path import exists

                if ext == ".pyc":
                    return exists(base+".py")
                else:
                    return ext == ".py"

            new_mod_text = SelectableText("-- update me --")
            new_mod_entry = urwid.AttrWrap(new_mod_text,
                    None, "focused selectable")

            def build_filtered_mod_list(filt_string=""):
                modules = sorted(name
                        for name, mod in sys.modules.items()
                        if mod_exists(mod))

                result = [urwid.AttrWrap(SelectableText(mod),
                        None, "focused selectable")
                        for mod in modules if filt_string in mod]
                new_mod_text.set_text("<<< IMPORT MODULE '%s' >>>" % filt_string)
                result.append(new_mod_entry)
                return result

            def show_mod(mod):
                filename = self.debugger.canonic(mod.__file__)

                base, ext = splitext(filename)
                if ext == ".pyc":
                    ext = ".py"
                    filename = base+".py"

                self.set_current_file(filename)
                self.source_list.set_focus(0)

            class FilterEdit(urwid.Edit):
                def keypress(self, size, key):
                    result = urwid.Edit.keypress(self, size, key)

                    if result is None:
                        mod_list[:] = build_filtered_mod_list(
                                self.get_edit_text())

                    return result

            filt_edit = FilterEdit([("label", "Filter: ")],
                    self.last_module_filter)

            mod_list = urwid.SimpleListWalker(
                    build_filtered_mod_list(filt_edit.get_edit_text()))
            lb = urwid.ListBox(mod_list)

            w = urwid.Pile([
                ("flow", urwid.AttrWrap(filt_edit, "value")),
                ("fixed", 1, urwid.SolidFill()),
                urwid.AttrWrap(lb, "selectable")])

            while True:
                result = self.dialog(w, [
                    ("OK", True),
                    ("Cancel", False),
                    ("Reload", "reload"),

                    ], title="Pick Module")
                self.last_module_filter = filt_edit.get_edit_text()

                if result == True:
                    widget, pos = lb.get_focus()
                    if widget is new_mod_entry:
                        new_mod_name = filt_edit.get_edit_text()
                        try:
                            __import__(str(new_mod_name))
                        except:
                            from traceback import format_exception
                            import sys

                            self.message("Could not import module '%s':\n\n%s" % (
                                new_mod_name, "".join(format_exception(*sys.exc_info()))),
                                title="Import Error")
                        else:
                            show_mod(sys.modules[str(new_mod_name)])
                            break
                    else:
                        show_mod(sys.modules[widget.get_text()[0]])
                        break
                elif result == False:
                    break
                elif result == "reload":
                    widget, pos = lb.get_focus()
                    if widget is not new_mod_entry:
                        mod_name = widget.get_text()[0]
                        mod = sys.modules[mod_name]
                        reload(mod)
                        self.message("'%s' was successfully reloaded." % mod_name)
                elif result == "import":
                    mod = import_new_module(filt_edit.get_edit_text())
                    if mod is not None:
                        show_mod(mod)
                    break

        def quit(w, size, key):
            self.debugger.set_quit()
            end()

        def help(w, size, key):
            self.message(HELP_TEXT, title="PuDB Help")

        self.top.listen("n", next)
        self.top.listen("s", step)
        self.top.listen("f", finish)
        self.top.listen("r", finish)
        self.top.listen("c", cont)
        self.top.listen("t", run_to_cursor)
        self.top.listen("e", show_traceback)

        self.top.listen("o", show_output)
        self.top.listen("!", run_shell)

        self.top.listen("j", move_down)
        self.top.listen("k", move_up)
        self.top.listen("ctrl d", page_down)
        self.top.listen("ctrl u", page_up)
        self.top.listen("h", scroll_left)
        self.top.listen("l", scroll_right)

        self.top.listen("/", search)
        self.top.listen(",", search_previous)
        self.top.listen(".", search_next)

        self.top.listen("+", grow_sidebar)
        self.top.listen("-", shrink_sidebar)
        self.top.listen("V", RHColumnFocuser(0))
        self.top.listen("S", RHColumnFocuser(1))
        self.top.listen("B", RHColumnFocuser(2))

        self.top.listen("home", move_home)
        self.top.listen("end", move_end)
        self.top.listen("g", move_home)
        self.top.listen("G", move_end)
        self.top.listen("L", go_to_line)

        self.top.listen("b", toggle_breakpoint)
        self.top.listen("m", pick_module)

        self.top.listen("q", quit)
        self.top.listen("H", help)
        self.top.listen("f1", help)
        self.top.listen("?", help)

        # setup ---------------------------------------------------------------
        import urwid.raw_display as display

        self.screen = display.Screen()
        self.setup_palette(self.screen)

        self.show_count = 0
        self.shown_file = None

        self.current_line = None

        self.quit_event_loop = False

    def message(self, msg, title="Message", **kwargs):
        self.call_with_ui(self.dialog,
                urwid.ListBox([urwid.Text(msg)]),
                [("OK", True)], title=title, **kwargs)

    def dialog(self, content, buttons_and_results,
            title=None, bind_enter_esc=True, focus_buttons=False):
        class ResultSetter:
            def __init__(subself, res):
                subself.res = res

            def __call__(subself, btn):
                self.quit_event_loop = [subself.res]

        Attr = urwid.AttrWrap

        if bind_enter_esc:
            content = SignalWrap(content)
            def enter(w, size, key): self.quit_event_loop = [True]
            def esc(w, size, key): self.quit_event_loop = [False]
            content.listen("enter", enter)
            content.listen("esc", esc)

        button_widgets = []
        for btn_descr in buttons_and_results:
            if btn_descr is None:
                button_widgets.append(urwid.Text(""))
            else:
                btn_text, btn_result = btn_descr
                button_widgets.append(
                        Attr(urwid.Button(btn_text, ResultSetter(btn_result)),
                            "button", "focused button"))

        w = urwid.Columns([
            content,
            ("fixed", 15, urwid.ListBox(button_widgets)),
            ], dividechars=1)

        if focus_buttons:
            w.set_focus_column(1)

        if title is not None:
            w = urwid.Pile([
                ("flow", urwid.AttrWrap(
                    urwid.Text(title, align="center"),
                    "dialog title")),
                ("fixed", 1, urwid.SolidFill()),
                w])

        w = urwid.LineBox(w)

        w = urwid.Overlay(w, self.top,
                align="center",
                valign="middle",
                width=('relative', 75),
                height=('relative', 75),
                )
        w = Attr(w, "background")

        return self.event_loop(w)[0]

    @staticmethod
    def setup_palette(screen):
        from urwid.raw_display import Screen as RawScreen
        may_use_fancy_formats = isinstance(screen, RawScreen) and \
                not hasattr(urwid.escape, "_fg_attr_xterm")

        from pudb.theme import get_palette
        screen.register_palette(get_palette(may_use_fancy_formats))

    # UI enter/exit -----------------------------------------------------------
    def show(self):
        if self.show_count == 0:
            self.screen.start()
        self.show_count += 1

    def hide(self):
        self.show_count -= 1
        if self.show_count == 0:
            self.screen.stop()

    def call_with_ui(self, f, *args, **kwargs):
        self.show()
        try:
            return f(*args, **kwargs)
        finally:
            self.hide()

    # interaction -------------------------------------------------------------
    def event_loop(self, toplevel=None):
        prev_quit_loop = self.quit_event_loop

        try:
            import pygments
        except ImportError:
            if not hasattr(self, "pygments_message_shown"):
                self.pygments_message_shown = True
                self.message("Package 'pygments' not found. "
                        "Syntax highlighting disabled.")

        try:
            if toplevel is None:
                toplevel = self.top

            self.size = self.screen.get_cols_rows()

            self.quit_event_loop = False

            while not self.quit_event_loop:
                canvas = toplevel.render(self.size, focus=True)
                self.screen.draw_screen(self.size, canvas)
                keys = self.screen.get_input()

                for k in keys:
                    if k == "window resize":
                        self.size = self.screen.get_cols_rows()
                    else:
                        toplevel.keypress(self.size, k)

            return self.quit_event_loop
        finally:
            self.quit_event_loop = prev_quit_loop

    # debugger-facing interface -----------------------------------------------
    def interaction(self, exc_tuple):
        self.current_exc_tuple = exc_tuple

        from pudb import VERSION
        caption = [(None,
            u"PuDB %s - The Python Urwid debugger - Hit ? for help"
            u" - © Andreas Klöckner 2009"
            % VERSION)]

        if self.debugger.post_mortem:
            from traceback import format_exception

            self.message(
                    "The program has terminated abnormally because of an exception.\n\n"
                    "A full traceback is below. You may recall this traceback at any "
                    "time using the 'e' key. "
                    "The debugger has entered post-mortem mode and will prevent further "
                    "state changes.\n\n"
                    + "".join(format_exception(*exc_tuple)),
                    title="Program Terminated for Uncaught Exception")
            caption.extend([
                (None, " "),
                ("warning", "[POST-MORTEM MODE]")
                ])
        elif exc_tuple is not None:
            caption.extend([
                (None, " "),
                ("warning", "[PROCESSING EXCEPTION - hit 'e' to examine]")
                ])

        self.caption.set_text(caption)
        self.event_loop()

    def format_source(self, lines, breakpoints):
        try:
            import pygments
        except ImportError:
            return [SourceLine(self,
                line.rstrip("\n\r").replace("\t", 8*" "), None,
                has_breakpoint=i+1 in breakpoints)
                for i, line in enumerate(lines)]
        else:
            from pygments import highlight
            from pygments.lexers import PythonLexer
            from pygments.formatter import Formatter
            import pygments.token as t

            result = []

            ATTR_MAP = {
                    t.Token: "source",
                    t.Keyword: "keyword",
                    t.Literal: "literal",
                    t.Punctuation: "punctuation",
                    t.Comment: "comment",
                    }

            class UrwidFormatter(Formatter):
                def __init__(subself, **options):
                    Formatter.__init__(subself, **options)
                    subself.current_line = ""
                    subself.current_attr = []
                    subself.lineno = 1

                def format(subself, tokensource, outfile):
                    def add_snippet(ttype, s):
                        if not s:
                            return

                        while not ttype in ATTR_MAP:
                            if ttype.parent is not None:
                                ttype = ttype.parent
                            else:
                                raise RuntimeError(
                                        "untreated token type: %s" % str(ttype))

                        attr = ATTR_MAP[ttype]

                        subself.current_line += s
                        subself.current_attr.append((attr, len(s)))

                    def shipout_line():
                        result.append(
                                SourceLine(self,
                                    subself.current_line,
                                    subself.current_attr,
                                    has_breakpoint=subself.lineno in breakpoints))
                        subself.current_line = ""
                        subself.current_attr = []
                        subself.lineno += 1

                    for ttype, value in tokensource:
                        while True:
                            newline_pos = value.find("\n")
                            if newline_pos == -1:
                                add_snippet(ttype, value)
                                break
                            else:
                                add_snippet(ttype, value[:newline_pos])
                                shipout_line()
                                value = value[newline_pos+1:]

                    if subself.current_line:
                        shipout_line()

            highlight("".join(l.replace("\t", 8*" ") for l in lines),
                    PythonLexer(), UrwidFormatter())

            return result

    def set_current_file(self, fname):
        fname = self.debugger.canonic(fname)

        if self.shown_file != fname:
            if fname == "<string>":
                self.source[:] = [SourceLine(self, fname)]
            else:
                breakpoints = self.debugger.get_file_breaks(fname)
                try:
                    from linecache import getlines
                    lines = getlines(fname)

                    from pudb.lowlevel import detect_encoding
                    source_enc, _ = detect_encoding(iter(lines).next)

                    decoded_lines = []
                    for l in lines:
                        if hasattr(l, "decode"):
                            decoded_lines.append(l.decode(source_enc))
                        else:
                            decoded_lines.append(l)

                    self.source[:] = self.format_source(
                            decoded_lines, set(breakpoints))
                except:
                    from traceback import format_exception
                    import sys

                    self.message("Could not load source file '%s':\n\n%s" % (
                        fname, "".join(format_exception(*sys.exc_info()))),
                        title="Source Code Load Error")
                    self.source[:] = [SourceLine(self,
                        "Error while loading '%s'." % fname)]

            self.shown_file = fname
            self.current_line = None

    def show_line(self, line, fname=None):
        chaged_file = False
        if fname is not None:
            changed_file =  self.shown_file != fname
            self.set_current_file(fname)

        line -= 1
        if line >= 0 and line < len(self.source):
            self.source_list.set_focus(line)
            if changed_file:
                self.source_list.set_focus_valign("middle")

    def set_current_line(self, line, fname):
        if self.current_line is not None:
            self.current_line.set_current(False)

        self.show_line(line, fname)

        line -= 1
        if line >= 0 and line < len(self.source):
            self.current_line = self.source[line]
            self.current_line.set_current(True)

    def set_locals(self, locals):
        vars = locals.keys()
        vars.sort(key=lambda n: n.lower())

        watch_list = []
        loc_list = []

        ssid = self.debugger.get_stack_situation_id()
        id_path_to_iinfo = self.inspect_info.get(ssid, {})

        try:
            import numpy
            HAVE_NUMPY = 1
        except ImportError:
            HAVE_NUMPY = 0

        watch_prefixes = []

        def add_var(prefix, var_label, value_str, id_path=None, attr_prefix=None):
            iinfo = id_path_to_iinfo.get(id_path, InspectInfo())
            if iinfo.highlighted:
                attr_prefix = "highlighted var"

            watched = iinfo.watched
            for wp in watch_prefixes:
                if id_path.startswith(wp):
                    watched = True

            if watched:
                watch_list.append(Variable(prefix, var_label, value_str, id_path, attr_prefix))
                watch_prefixes.append(id_path)

            loc_list.append(Variable(prefix, var_label, value_str, id_path, attr_prefix))

        def display_var(prefix, label, value, id_path=None, attr_prefix=None):
            if id_path is None:
                id_path = label

            iinfo = id_path_to_iinfo.get(id_path, InspectInfo())

            if isinstance(value, (int, float, long, complex)):
                add_var(prefix, label, repr(value), id_path, attr_prefix)
            elif isinstance(value, (str, unicode)):
                add_var(prefix, label, repr(value)[:200], id_path, attr_prefix)
            elif isinstance(value, type):
                add_var(prefix, label, "type "+value.__name__, id_path, attr_prefix)
            else:
                if iinfo.display_type == "type":
                    if HAVE_NUMPY and isinstance(value, numpy.ndarray):
                        displayed_value = "ndarray %s %s" % (value.dtype, value.shape)
                    else:
                        displayed_value = type(value).__name__
                elif iinfo.display_type == "repr":
                    displayed_value = repr(value)
                elif iinfo.display_type == "str":
                    displayed_value = str(value)
                else:
                    displayed_value = "ERROR: Invalid display_type"

                add_var(prefix, label,
                    displayed_value, id_path, attr_prefix)

                if not iinfo.show_detail:
                    return

                # set ---------------------------------------------------------
                if isinstance(value, (set, frozenset)):
                    for i, entry in enumerate(value):
                        if i % 10 == 0 and i:
                            cont_id_path = "%s.cont-%d" % (id_path, i)
                            if not id_path_to_iinfo.get(
                                    cont_id_path, InspectInfo()).show_detail:
                                add_var(prefix+"  ", "...", None, cont_id_path)
                                break

                        display_var(prefix+"  ", None, entry,
                            "%s[%d]" % (id_path, i))
                    if not value:
                        add_var(prefix+"  ", "<empty>", None)
                    return

                # containers --------------------------------------------------
                key_it = None
                try:
                    l = len(value)
                except:
                    pass
                else:
                    try:
                        value[0]
                    except IndexError:
                        key_it = xrange(l)
                    except:
                        pass

                try:
                    key_it = value.iterkeys()
                except:
                    pass

                if key_it is not None:
                    cnt = 0
                    for key in key_it:
                        if cnt % 10 == 0 and cnt:
                            cont_id_path = "%s.cont-%d" % (id_path, cnt)
                            if not id_path_to_iinfo.get(
                                    cont_id_path, InspectInfo()).show_detail:
                                add_var(
                                    prefix+"  ", "...", None, cont_id_path)
                                break

                        display_var(prefix+"  ", repr(key), value[key],
                            "%s[%r]" % (id_path, key))
                        cnt += 1
                    if not cnt:
                        add_var(prefix+"  ", "<empty>", None)
                    return

                # class types -------------------------------------------------
                try:
                    key_it = value.__slots__
                except:
                    pass
                else:
                    for key in key_it:
                        if key[0] == "_" and not iinfo.show_private_members:
                            continue

                        if hasattr(value, key):
                            display_var(prefix+"  ",
                                    ".%s" % key, getattr(value, key),
                                    "%s.%s" % (id_path, key))

                try:
                    key_it = value.__dict__.iterkeys()
                except:
                    pass
                else:
                    for key in key_it:
                        if key[0] == "_" and not iinfo.show_private_members:
                            continue

                        display_var(prefix+"  ",
                                ".%s" % key, getattr(value, key),
                                "%s.%s" % (id_path, key))

        if "__return__" in vars:
            display_var("", "Return", locals["__return__"], attr_prefix="return")

        for var in vars:
            if not var[0] in "_.":
                display_var("", var, locals[var])

        if watch_list:
            loc_list = (watch_list
                    + [urwid.AttrWrap(
                        urwid.Text("---", align="center"),
                        "variable separator")]
                    + loc_list)

        self.locals[:] = loc_list

    def _get_bp_list(self):
        return [bp
                for fn, bp_lst in self.debugger.get_all_breaks().iteritems()
                for lineno in bp_lst
                for bp in self.debugger.get_breaks(fn, lineno)
                if not bp.temporary]

    def _format_fname(self, fname):
        from os.path import dirname, basename
        name = basename(fname)

        if name == "__init__.py":
            name = "..."+dirname(fname)[-10:]+"/"+name
        return name

    def update_breakpoints(self):
        def format_bp(bp):
            return "%s:%d" % (self._format_fname(bp.file), bp.line)

        self.bp_walker[:] = [
                urwid.AttrWrap(
                    SelectableText(format_bp(bp), wrap="clip"),
                    None, "focused breakpoint")
                for bp in self._get_bp_list()]

    def update_stack(self):
        def make_frame_ui(frame_lineno):
            frame, lineno = frame_lineno

            code = frame.f_code

            class_name = None
            if code.co_argcount and code.co_varnames[0] == "self":
                try:
                    class_name = frame.f_locals["self"].__class__.__name__
                except:
                    pass

            return StackFrame(frame is self.debugger.curframe,
                    code.co_name, class_name,
                    self._format_fname(code.co_filename), lineno)

        self.stack_walker[:] = [make_frame_ui(fl)
                for fl in self.debugger.stack]

    def show_exception(self, exc_type, exc_value, traceback):
        from traceback import format_exception

        self.message(
                "".join(format_exception(
                    exc_type, exc_value, traceback)),
                title="Exception Occurred")
