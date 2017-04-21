#!/usr/bin/env python2
# vim:fileencoding=UTF-8:ts=4:sw=4:sta:et:sts=4:ai
# License: GPLv3 Copyright: 2010, Kovid Goyal <kovid at kovidgoyal.net>

import textwrap
import time

from PyQt5.Qt import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QHBoxLayout, QIcon, QLabel, QLineEdit, QListWidget, QPlainTextEdit, QPushButton,
    QScrollArea, QSize, QSizePolicy, QSpinBox, Qt, QTabWidget, QTimer, QUrl,
    QVBoxLayout, QWidget, pyqtSignal
)

from calibre import as_unicode
from calibre.gui2 import config, error_dialog, info_dialog, open_url, warning_dialog
from calibre.gui2.preferences import AbortCommit, ConfigWidgetBase, test_widget
from calibre.srv.opts import change_settings, options, server_config
from calibre.srv.users import UserManager, validate_username, validate_password, create_user_data
from calibre.utils.icu import primary_sort_key


# Advanced {{{


def init_opt(widget, opt, layout):
    widget.name, widget.default_val = opt.name, opt.default
    if opt.longdoc:
        widget.setWhatsThis(opt.longdoc)
        widget.setStatusTip(opt.longdoc)
        widget.setToolTip(textwrap.fill(opt.longdoc))
    layout.addRow(opt.shortdoc + ':', widget)


class Bool(QCheckBox):

    changed_signal = pyqtSignal()

    def __init__(self, name, layout):
        opt = options[name]
        QCheckBox.__init__(self)
        self.stateChanged.connect(self.changed_signal.emit)
        init_opt(self, opt, layout)

    def get(self):
        return self.isChecked()

    def set(self, val):
        self.setChecked(bool(val))


class Int(QSpinBox):

    changed_signal = pyqtSignal()

    def __init__(self, name, layout):
        QSpinBox.__init__(self)
        self.setRange(0, 10000)
        opt = options[name]
        self.valueChanged.connect(self.changed_signal.emit)
        init_opt(self, opt, layout)

    def get(self):
        return self.value()

    def set(self, val):
        self.setValue(int(val))


class Float(QDoubleSpinBox):

    changed_signal = pyqtSignal()

    def __init__(self, name, layout):
        QDoubleSpinBox.__init__(self)
        self.setRange(0, 10000)
        self.setDecimals(1)
        opt = options[name]
        self.valueChanged.connect(self.changed_signal.emit)
        init_opt(self, opt, layout)

    def get(self):
        return self.value()

    def set(self, val):
        self.setValue(float(val))


class Text(QLineEdit):

    changed_signal = pyqtSignal()

    def __init__(self, name, layout):
        QLineEdit.__init__(self)
        opt = options[name]
        self.textChanged.connect(self.changed_signal.emit)
        init_opt(self, opt, layout)

    def get(self):
        return self.text().strip() or None

    def set(self, val):
        self.setText(type(u'')(val or ''))


class Choices(QComboBox):

    changed_signal = pyqtSignal()

    def __init__(self, name, layout):
        QComboBox.__init__(self)
        self.setEditable(False)
        opt = options[name]
        self.choices = opt.choices
        tuple(map(self.addItem, opt.choices))
        self.currentIndexChanged.connect(self.changed_signal.emit)
        init_opt(self, opt, layout)

    def get(self):
        return self.currentText()

    def set(self, val):
        if val in self.choices:
            self.setCurrentText(val)
        else:
            self.setCurrentIndex(0)


class AdvancedTab(QWidget):

    changed_signal = pyqtSignal()

    def __init__(self, parent=None):
        QWidget.__init__(self, parent)
        self.l = l = QFormLayout(self)
        l.setFieldGrowthPolicy(l.AllNonFixedFieldsGrow)
        self.widgets = []
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        for name in sorted(options, key=lambda n: options[n].shortdoc.lower()):
            if name in ('auth', 'port', 'allow_socket_preallocation', 'userdb'):
                continue
            opt = options[name]
            if opt.choices:
                w = Choices
            elif isinstance(opt.default, bool):
                w = Bool
            elif isinstance(opt.default, (int, long)):
                w = Int
            elif isinstance(opt.default, float):
                w = Float
            else:
                w = Text
            w = w(name, l)
            setattr(self, 'opt_' + name, w)
            self.widgets.append(w)

    def genesis(self):
        opts = server_config()
        for w in self.widgets:
            w.set(getattr(opts, w.name))
            w.changed_signal.connect(self.changed_signal.emit)

    def restore_defaults(self):
        for w in self.widgets:
            w.set(w.default_val)

    @property
    def settings(self):
        return {w.name: w.get() for w in self.widgets}


# }}}


class MainTab(QWidget):  # {{{

    changed_signal = pyqtSignal()
    start_server = pyqtSignal()
    stop_server = pyqtSignal()
    test_server = pyqtSignal()
    show_logs = pyqtSignal()

    def __init__(self, parent=None):
        QWidget.__init__(self, parent)
        self.l = l = QVBoxLayout(self)
        self.la = la = QLabel(
            _(
                'calibre contains an internet server that allows you to'
                ' access your book collection using a browser from anywhere'
                ' in the world. Any changes to the settings will only take'
                ' effect after a server restart.'
            )
        )
        la.setWordWrap(True)
        l.addWidget(la)
        l.addSpacing(10)
        self.fl = fl = QFormLayout()
        l.addLayout(fl)
        self.opt_port = sb = QSpinBox(self)
        if options['port'].longdoc:
            sb.setToolTip(options['port'].longdoc)
        sb.setRange(1, 65535)
        sb.valueChanged.connect(self.changed_signal.emit)
        fl.addRow(options['port'].shortdoc + ':', sb)
        l.addSpacing(25)
        self.opt_auth = cb = QCheckBox(
            _('Require username/password to access the content server')
        )
        l.addWidget(cb)
        self.auth_desc = la = QLabel(self)
        la.setStyleSheet('QLabel { font-size: small; font-style: italic }')
        la.setWordWrap(True)
        l.addWidget(la)
        l.addSpacing(25)
        self.opt_autolaunch_server = al = QCheckBox(
            _('Run server &automatically when calibre starts')
        )
        l.addWidget(al)
        l.addSpacing(25)
        self.h = h = QHBoxLayout()
        l.addLayout(h)
        for text, name in [(_('&Start server'),
                            'start_server'), (_('St&op server'), 'stop_server'),
                           (_('&Test server'),
                            'test_server'), (_('Show server &logs'), 'show_logs')]:
            b = QPushButton(text)
            b.clicked.connect(getattr(self, name).emit)
            setattr(self, name + '_button', b)
            if name == 'show_logs':
                h.addStretch(10)
            h.addWidget(b)
        l.addStretch(10)

    def genesis(self):
        opts = server_config()
        self.opt_auth.setChecked(opts.auth)
        self.opt_auth.stateChanged.connect(self.auth_changed)
        self.opt_port.setValue(opts.port)
        self.change_auth_desc()
        self.update_button_state()

    def change_auth_desc(self):
        self.auth_desc.setText(
            _('Remember to create some user accounts in the "Users" tab')
            if self.opt_auth.isChecked() else _(
                'Requiring a username/password prevents unauthorized people from'
                ' accessing your calibre library. It is also needed for some features'
                ' such as making any changes to the library as well as'
                ' last read position/annotation syncing.'
            )
        )

    def auth_changed(self):
        self.changed_signal.emit()
        self.change_auth_desc()

    def restore_defaults(self):
        self.opt_auth.setChecked(options['auth'].default)
        self.opt_port.setValue(options['port'].default)

    def update_button_state(self):
        from calibre.gui2.ui import get_gui
        gui = get_gui()
        is_running = gui.content_server is not None and gui.content_server.is_running
        self.start_server_button.setEnabled(not is_running)
        self.stop_server_button.setEnabled(is_running)
        self.test_server_button.setEnabled(is_running)

    @property
    def settings(self):
        return {'auth': self.opt_auth.isChecked(), 'port': self.opt_port.value()}


# }}}


# Users {{{

class NewUser(QDialog):

    def __init__(self, user_data, parent=None, username=None):
        QDialog.__init__(self, parent)
        self.user_data = user_data
        self.setWindowTitle(_('Change password for {}').format(username) if username else _('Add new user'))
        self.l = l = QFormLayout(self)
        l.setFieldGrowthPolicy(l.AllNonFixedFieldsGrow)
        self.uw = u = QLineEdit(self)
        l.addRow(_('&Username:'), u)
        if username:
            u.setText(username)
            u.setReadOnly(True)
        l.addRow(QLabel(_('Set the password for this user')))
        self.p1, self.p2 = p1, p2 = QLineEdit(self), QLineEdit(self)
        l.addRow(_('&Password:'), p1), l.addRow(_('&Repeat password:'), p2)
        for p in p1, p2:
            p.setEchoMode(QLineEdit.PasswordEchoOnEdit)
            p.setMinimumWidth(300)
            if username:
                p.setText(user_data[username]['pw'])
        self.showp = sp = QCheckBox(_('&Show password'))
        sp.stateChanged.connect(self.show_password)
        l.addRow(sp)
        self.bb = bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        l.addRow(bb)
        bb.accepted.connect(self.accept), bb.rejected.connect(self.reject)
        (self.uw if not username else self.p1).setFocus(Qt.OtherFocusReason)

    def show_password(self):
        for p in self.p1, self.p2:
            p.setEchoMode(QLineEdit.Normal if self.showp.isChecked() else QLineEdit.PasswordEchoOnEdit)

    @property
    def username(self):
        return self.uw.text().strip()

    @property
    def password(self):
        return self.p1.text()

    def accept(self):
        if not self.uw.isReadOnly():
            un = self.username
            if not un:
                return error_dialog(self, _('Empty username'), _('You must enter a username'), show=True)
            if un in self.user_data:
                return error_dialog(self, _('Username already exists'), _(
                    'A user witht he username {} already exists. Please choose a different username.').format(un), show=True)
            err = validate_username(un)
            if err:
                return error_dialog(self, _('Username is not valid'), err, show=True)
        p1, p2 = self.password, self.p2.text()
        if p1 != p2:
            return error_dialog(self, _('Password do not match'), _(
                'The two passwords you entered do not match!'), show=True)
        if not p1:
            return error_dialog(self, _('Empty password'), _(
                'You must enter a password for this user'), show=True)
        err = validate_password(p1)
        if err:
            return error_dialog(self, _('Invalid password'), err, show=True)
        return QDialog.accept(self)


class User(QWidget):

    changed_signal = pyqtSignal()

    def __init__(self, parent=None):
        QWidget.__init__(self, parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.l = l = QFormLayout(self)
        l.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.username_label = la = QLabel('')
        l.addWidget(la)
        self.cpb = b = QPushButton(_('Change &password'))
        l.addWidget(b)
        b.clicked.connect(self.change_password)

        self.show_user()

    def change_password(self):
        d = NewUser(self.user_data, self, self.username)
        if d.exec_() == d.Accepted:
            self.user_data[self.username]['pw'] = d.password
            self.changed_signal.emit()

    def show_user(self, username=None, user_data=None):
        self.username, self.user_data = username, user_data
        self.cpb.setEnabled(username is not None)
        self.username_label.setText(('<h2>' + username) if username else '')

    def sizeHint(self):
        ans = QWidget.sizeHint(self)
        ans.setWidth(400)
        return ans


class Users(QWidget):

    changed_signal = pyqtSignal()

    def __init__(self, parent=None):
        QWidget.__init__(self, parent)
        self.l = l = QHBoxLayout(self)
        self.lp = lp = QVBoxLayout()
        l.addLayout(lp)

        self.h = h = QHBoxLayout()
        lp.addLayout(h)
        self.add_button = b = QPushButton(QIcon(I('plus.png')), _('&Add user'), self)
        b.clicked.connect(self.add_user)
        h.addWidget(b)
        self.remove_button = b = QPushButton(QIcon(I('minus.png')), _('&Remove user'), self)
        b.clicked.connect(self.remove_user)
        h.addStretch(2), h.addWidget(b)

        self.user_list = w = QListWidget(self)
        w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        lp.addWidget(w)

        self.user_display = u = User(self)
        u.changed_signal.connect(self.changed_signal.emit)
        l.addWidget(u)

    def genesis(self):
        self.user_data = UserManager().user_data
        self.user_list.addItems(sorted(self.user_data, key=primary_sort_key))
        self.user_list.setCurrentRow(0)
        self.user_list.currentItemChanged.connect(self.current_item_changed)
        self.current_item_changed()

    def current_item_changed(self):
        item = self.user_list.currentItem()
        if item is None:
            username = None
        else:
            username = item.text()
        if username not in self.user_data:
            username = None
        self.display_user_data(username)

    def add_user(self):
        d = NewUser(self.user_data, parent=self)
        if d.exec_() == d.Accepted:
            un, pw = d.username, d.password
            self.user_data[un] = create_user_data(pw)
            self.user_list.insertItem(0, un)
            self.user_list.setCurrentRow(0)
            self.display_user_data(un)
            self.changed_signal.emit()

    def remove_user(self):
        u = self.user_list.currentItem()
        if u is not None:
            self.user_list.takeItem(self.user_list.row(u))
            un = u.text()
            self.user_data.pop(un, None)
            self.changed_signal.emit()
            self.current_item_changed()

    def display_user_data(self, username=None):
        self.user_display.show_user(username, self.user_data)

# }}}


class ConfigWidget(ConfigWidgetBase):

    def __init__(self, *args, **kw):
        ConfigWidgetBase.__init__(self, *args, **kw)
        self.l = l = QVBoxLayout(self)
        l.setContentsMargins(0, 0, 0, 0)
        self.tabs_widget = t = QTabWidget(self)
        l.addWidget(t)
        self.main_tab = m = MainTab(self)
        t.addTab(m, _('&Main'))
        m.start_server.connect(self.start_server)
        m.stop_server.connect(self.stop_server)
        m.test_server.connect(self.test_server)
        m.show_logs.connect(self.view_server_logs)
        self.opt_autolaunch_server = m.opt_autolaunch_server
        self.users_tab = ua = Users(self)
        t.addTab(ua, _('&User Accounts'))
        self.advanced_tab = a = AdvancedTab(self)
        sa = QScrollArea(self)
        sa.setWidget(a), sa.setWidgetResizable(True)
        t.addTab(sa, _('&Advanced'))
        for tab in self.tabs:
            if hasattr(tab, 'changed_signal'):
                tab.changed_signal.connect(self.changed_signal.emit)

    @property
    def tabs(self):

        def w(x):
            if isinstance(x, QScrollArea):
                x = x.widget()
            return x

        return (
            w(self.tabs_widget.widget(i)) for i in range(self.tabs_widget.count())
        )

    @property
    def server(self):
        return self.gui.content_server

    def restore_defaults(self):
        ConfigWidgetBase.restore_defaults(self)
        for tab in self.tabs:
            if hasattr(tab, 'restore_defaults'):
                tab.restore_defaults()

    def genesis(self, gui):
        self.gui = gui
        for tab in self.tabs:
            tab.genesis()

        r = self.register
        r('autolaunch_server', config)

    def start_server(self):
        if not self.save_changes():
            return
        self.setCursor(Qt.BusyCursor)
        try:
            self.gui.start_content_server(check_started=False)
            while (not self.server.is_running and self.server.exception is None):
                time.sleep(0.1)
            if self.server.exception is not None:
                error_dialog(
                    self,
                    _('Failed to start content server'),
                    as_unicode(self.gui.content_server.exception)
                ).exec_()
                return
            self.main_tab.update_button_state()
        finally:
            self.unsetCursor()

    def stop_server(self):
        self.server.stop()
        self.stopping_msg = info_dialog(
            self,
            _('Stopping'),
            _('Stopping server, this could take up to a minute, please wait...'),
            show_copy_button=False
        )
        QTimer.singleShot(500, self.check_exited)
        self.stopping_msg.exec_()

    def check_exited(self):
        if getattr(self.server, 'is_running', False):
            QTimer.singleShot(20, self.check_exited)
            return

        self.gui.content_server = None
        self.main_tab.update_button_state()
        self.stopping_msg.accept()

    def test_server(self):
        prefix = self.advanced_tab.opt_url_prefix.text().strip()
        open_url(
            QUrl('http://127.0.0.1:' + str(self.main_tab.opt_port.value()) + prefix)
        )

    def view_server_logs(self):
        from calibre.srv.embedded import log_paths
        log_error_file, log_access_file = log_paths()
        d = QDialog(self)
        d.resize(QSize(800, 600))
        layout = QVBoxLayout()
        d.setLayout(layout)
        layout.addWidget(QLabel(_('Error log:')))
        el = QPlainTextEdit(d)
        layout.addWidget(el)
        try:
            el.setPlainText(
                lopen(log_error_file, 'rb').read().decode('utf8', 'replace')
            )
        except EnvironmentError:
            el.setPlainText('No error log found')
        layout.addWidget(QLabel(_('Access log:')))
        al = QPlainTextEdit(d)
        layout.addWidget(al)
        try:
            al.setPlainText(
                lopen(log_access_file, 'rb').read().decode('utf8', 'replace')
            )
        except EnvironmentError:
            al.setPlainText('No access log found')
        bx = QDialogButtonBox(QDialogButtonBox.Ok)
        layout.addWidget(bx)
        bx.accepted.connect(d.accept)
        d.show()

    def save_changes(self):
        settings = {}
        for tab in self.tabs:
            settings.update(getattr(tab, 'settings', {}))
        users = self.users_tab.user_data
        if settings['auth']:
            if not users:
                error_dialog(
                    self,
                    _('No users specified'),
                    _(
                        'You have turned on the setting to require passwords to access'
                        ' the content server, but you have not created any user accounts.'
                        ' Create at least one user account in the "User Accounts" tab to proceed.'
                    ),
                    show=True
                )
                self.tabs_widget.setCurrentWidget(self.users_tab)
                return False
        ConfigWidgetBase.commit(self)
        change_settings(**settings)
        UserManager().user_data = users
        return True

    def commit(self):
        if not self.save_changes():
            raise AbortCommit()
        warning_dialog(
            self,
            _('Restart needed'),
            _('You need to restart the server for changes to'
              ' take effect'),
            show=True
        )
        return False

    def refresh_gui(self, gui):
        if self.server:
            self.server.user_manager.refresh()


if __name__ == '__main__':
    from calibre.gui2 import Application
    app = Application([])
    test_widget('Sharing', 'Server')
