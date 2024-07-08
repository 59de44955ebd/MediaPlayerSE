import datetime
import json
import os
import subprocess
import sys
import time
import traceback
import urllib.parse
from xml.dom import minidom

from PyQt5.QtCore import Qt, QResource, QTimer, QTime, QEvent, pyqtSignal, QUrl, QSettings, QRect
from PyQt5.QtGui import QColor, QKeySequence, QCursor
from PyQt5.QtWidgets import (qApp, QMainWindow, QApplication, QWidget, QLabel, QDialog,
        QSizePolicy, QActionGroup, QMessageBox, QFileDialog, QInputDialog,
        QListWidgetItem, QTreeWidgetItem, QMenu, QAction)
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PyQt5 import uic

from dark import palette
from clickableslider import ClickableSlider

APP_NAME = 'MediaPlayerSE'
APP_VERSION = '0.1'

IS_WIN = sys.platform == 'win32'
IS_MAC = sys.platform == 'darwin'
if not IS_WIN and not IS_MAC:
    sys.exit(1)

IS_FROZEN = getattr(sys, 'frozen', False)
if IS_FROZEN:
    if IS_WIN:
        RES_DIR = os.path.join(os.path.dirname(sys.executable), '_internal', 'resources')
    else:
        RES_DIR = os.path.join(os.path.dirname(sys.executable), '..', 'Resources')
else:
    RES_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'resources')

if IS_WIN:
    from ctypes import windll, c_int, byref
    from ctypes.wintypes import HWND, DWORD, LPCVOID

    windll.dwmapi.DwmSetWindowAttribute.argtypes = (HWND, DWORD, LPCVOID, DWORD)
    DWMWA_USE_IMMERSIVE_DARK_MODE = 20

TIME_DISPLAY_UPDATE_PERIOD = 250


NETRADIO_SHOUTCAST = 0
NETRADIO_SOMAFM = 1
NETRADIO_TUNEIN = 2


class Main(QMainWindow):

    ########################################
    #
    ########################################
    def __init__(self, app):
        super().__init__()

        self._settings = QSettings('fx', APP_NAME)

        if IS_MAC and IS_FROZEN:
            app.fileOpened.connect(lambda filename:
                    self.video_widget.load_media(filename))
        self._duration = 0
        self._duration_str = ''
        self._time_format = 'hh:mm:ss'
        self._fullscreen = False
        self._active_item = None
        self._caption = None
        if IS_WIN:
            self._last_play_toggle_time = 0
            windll.dwmapi.DwmSetWindowAttribute(int(self.winId()),
                    DWMWA_USE_IMMERSIVE_DARK_MODE, byref(c_int(1)), 4)

        QApplication.setStyle('Fusion')
        qApp.setPalette(palette)
        with open(os.path.join(RES_DIR, 'style.css'), 'r') as f:
            qApp.setStyleSheet(f.read())

        QResource.registerResource(os.path.join(RES_DIR, 'main.rcc'))
        uic.loadUi(os.path.join(RES_DIR, 'main.ui'), self)

        self.dialog_media_infos = QDialog(self, Qt.WindowCloseButtonHint)
        uic.loadUi(os.path.join(RES_DIR, 'mediainfos.ui'), self.dialog_media_infos)
        if IS_WIN:
            windll.dwmapi.DwmSetWindowAttribute(int(self.dialog_media_infos.winId()),
                    DWMWA_USE_IMMERSIVE_DARK_MODE, byref(c_int(1)), 4)
            windll.uxtheme[135](2)  # SetPreferredAppMode, ForceDark = 2

        # menu
        self.action_open.triggered.connect(self.slot_open)
        self.action_open_url.triggered.connect(self.slot_open_url)
        self.action_close.triggered.connect(self.slot_close_media)
        self.action_show_media_infos.triggered.connect(self.slot_show_media_infos)
        self.action_add_to_favorites.triggered.connect(self.slot_add_to_favorites)
        self.action_toggle_fullscreen.triggered.connect(self.slot_toggle_fullscreen)
        self.action_toggle_play.triggered.connect(self.slot_toggle_playback)
        self.action_step_forward.triggered.connect(lambda: self.video_widget.step(1))
        self.action_step_back.triggered.connect(lambda: self.video_widget.step(-1))
        self.action_skip_forward.triggered.connect(lambda:
            self.video_widget.seek_to_time(self.video_widget.get_time() + 1))
        self.action_skip_back.triggered.connect(lambda:
            self.video_widget.seek_to_time(self.video_widget.get_time() - 1))
        self.action_volume_up.triggered.connect(lambda:
            self.slider_volume.setValue(self.slider_volume.value() + 1))
        self.action_volume_down.triggered.connect(lambda:
            self.slider_volume.setValue(self.slider_volume.value() - 1))
        self.action_toggle_mute.toggled.connect(self.video_widget.set_muted)
        self.action_about.triggered.connect(self.slot_about)

        # statusbar
        self.label_statusbar = QLabel()
        self.label_statusbar.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        if IS_MAC:
            self.label_statusbar.setStyleSheet('font-family: "Andale Mono";')
        self.statusbar.addPermanentWidget(self.label_statusbar)

        # toolbar
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.toolBar.addWidget(spacer)
        self.toolBar.addAction(self.action_toggle_mute)
        self.slider_volume = ClickableSlider(Qt.Horizontal)
        self.slider_volume.setFixedWidth(100)
        self.slider_volume.setRange(0, 100)
        self.slider_volume.valueChanged.connect(lambda value:
                self.video_widget.set_volume(value / 100))
        self.toolBar.addWidget(self.slider_volume)

        self.toolBarSlider.addWidget(self.slider_time)

        ag = QActionGroup(self)
        ag.addAction(self.action_play)
        ag.addAction(self.action_pause)
        ag.addAction(self.action_stop)

        self.action_play.triggered.connect(self.video_widget.play)
        self.action_pause.triggered.connect(self.video_widget.pause)
        self.action_stop.triggered.connect(lambda:
            self.video_widget.pause() or self.video_widget.seek_to_time(0))

        self.video_widget.mediaReady.connect(self.slot_ready)
        self.video_widget.mousePressed.connect(self.slot_toggle_playback)
        self.video_widget.doubleClicked.connect(self.slot_double_clicked)
        self.video_widget.metadataChanged.connect(self.slot_metadata_changed)

        self.slider_time.sliderMoved.connect(lambda value:
                self.video_widget.seek_to_time(value / 10000 * self._duration) if self._duration else None)

        self._timer = QTimer(self)
        self._timer.setInterval(TIME_DISPLAY_UPDATE_PERIOD)
        self._timer.timeout.connect(self.slot_update_time)

        self.slider_volume.setValue(int(100 * self.video_widget.get_volume()))

        self.tabifyDockWidget(self.dockWidgetTV, self.dockWidgetRadio)
        self.tabifyDockWidget(self.dockWidgetRadio, self.dockWidgetFavorites)
        self.dockWidgetTV.hide()
        self.dockWidgetRadio.hide()
        self.dockWidgetFavorites.hide()

        r = QRect(0, 0, 1024, 740)
        r.moveCenter(self.screen().geometry().center())
        self.setGeometry(r)
        self.show()

        self.setMinimumHeight(self.height() - self.video_widget.height())

        self._net_manager = QNetworkAccessManager(self)

        self._setup_radio()
        self._setup_tv()
        self._setup_favorites()

        if len(sys.argv) > 1:
            self.video_widget.load_media(sys.argv[1])

    ########################################
    #
    ########################################
    def _setup_radio(self):
        self.splitterRadio.setStretchFactor(0, 9)
        self.splitterRadio.setStretchFactor(1, 1)

        self.dockWidgetRadio.visibilityChanged.connect(self.action_radio.setChecked)
        self.action_radio.triggered.connect(lambda flag:
                self.dockWidgetRadio.setVisible(flag) or (self.dockWidgetRadio.raise_() if flag else None))

        self.treeWidgetRadioDirectories.itemDoubleClicked.connect(self.slot_radio_directories_item_clicked)

        self.treeWidgetRadioDirectories.sortItems(0, Qt.AscendingOrder)

        self.lineEditRadioSearch.returnPressed.connect(self.slot_radio_search_return_pressed)
        self.listWidgetRadioSearchResults.itemDoubleClicked.connect(self.slot_radio_search_result_double_clicked)

        tree_item = QTreeWidgetItem(['SHOUTcast'])
        tree_item.setData(0, Qt.UserRole, NETRADIO_SHOUTCAST)
        self.treeWidgetRadioDirectories.addTopLevelItem(tree_item)

        tree_item = QTreeWidgetItem(['SomaFM'])
        tree_item.setData(0, Qt.UserRole, NETRADIO_SOMAFM)
        self.treeWidgetRadioDirectories.addTopLevelItem(tree_item)

        tree_item = QTreeWidgetItem(['TuneIn'])
        tree_item.setData(0, Qt.UserRole, NETRADIO_TUNEIN)
        self.treeWidgetRadioDirectories.addTopLevelItem(tree_item)

    ########################################
    #
    ########################################
    def _setup_tv(self):
        self.splitterTV.setStretchFactor(0, 9)
        self.splitterTV.setStretchFactor(1, 1)
        self.dockWidgetTV.visibilityChanged.connect(self.action_tv.setChecked)
        self.action_tv.triggered.connect(lambda flag:
                self.dockWidgetTV.setVisible(flag) or (self.dockWidgetTV.raise_() if flag else None))
        self.listWidgetTVLivestreams.itemDoubleClicked.connect(self.slot_tv_livestreams_item_double_clicked)

        self.lineEditTVSearch.returnPressed.connect(self.slot_tv_search_return_pressed)
        self.listWidgetTVSearchResults.itemDoubleClicked.connect(self.slot_tv_search_result_double_clicked)

        def _loaded(res):
            try:
                for track_id, track in json.loads(res).items():
                	list_item = QListWidgetItem(track['name'])
                	list_item.setData(Qt.UserRole, track['streamUrl'])
                	list_item.setData(Qt.UserRole + 1, track_id)
                	self.listWidgetTVLivestreams.addItem(list_item)
            except:
                pass

        self._http_get('https://api.zapp.mediathekview.de/v1/channelInfoList', _loaded)

    ########################################
    #
    ########################################
    def _setup_favorites(self):
        self.dockWidgetFavorites.visibilityChanged.connect(self.action_favorites.setChecked)
        self.action_favorites.triggered.connect(lambda flag:
                self.dockWidgetFavorites.setVisible(flag) or (self.dockWidgetFavorites.raise_() if flag else None))
        self.listWidgetFavorites.itemDoubleClicked.connect(self.slot_favorite_double_clicked)

        def _favs_context_menu(pos):
            list_item = self.listWidgetFavorites.currentItem()
            if not list_item:
                return
            m = QMenu()
            a = QAction('Delete', m)
            a.triggered.connect(lambda list_item=list_item:
                    self.listWidgetFavorites.takeItem(list_item))
            m.addAction(a)
            m.exec(QCursor.pos())
        self.listWidgetFavorites.customContextMenuRequested.connect(_favs_context_menu)

        favs = self._settings.value('Favorites', None)
        if not favs:
            return
        favs = json.loads(favs)
        for title, url in favs:
            list_item = QListWidgetItem(title)
            list_item.setData(Qt.UserRole, url)
            list_item.setFlags(list_item.flags() | Qt.ItemIsEditable)
            self.listWidgetFavorites.addItem(list_item)

    ########################################
    #
    ########################################
    def _http_get(self, url, callback):
        reply = self._net_manager.get(QNetworkRequest(QUrl(url)))
        reply.finished.connect(lambda: callback(reply.readAll().data()))

    ########################################
    #
    ########################################
    def _reset_active_item(self):
        if self._active_item:
            if type(self._active_item) == QTreeWidgetItem:
                self._active_item.setData(0, Qt.ForegroundRole, None)
            else:
                self._active_item.setData(Qt.ForegroundRole, None)
            self._active_item = None

    ########################################
    #
    ########################################
    def closeEvent(self, e):
        self.video_widget.close_media()

        favs = []
        for row in range(self.listWidgetFavorites.count()):
            list_item = self.listWidgetFavorites.item(row)
            favs.append((list_item.text(), list_item.data(Qt.UserRole)))
        self._settings.setValue('Favorites', json.dumps(favs))

        super().closeEvent(e)

    ########################################
    #
    ########################################
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.accept()

    ########################################
    #
    ########################################
    def dropEvent(self, e):
        self.load_media(e.mimeData().urls()[0].toLocalFile())

    ########################################
    #
    ########################################
    def load_media(self, media_file, caption=None):
        self.statusbar.clearMessage()
        if caption is None:
            self._reset_active_item()
        self._caption = caption
        self.video_widget.load_media(media_file)
        self.activateWindow()

    ########################################
    #
    ########################################
    def slot_ready(self, ok):
        self.slider_time.setValue(0)
        if ok:
            has_video = self.video_widget.has_video()
#            if has_video:
#                w, h = self.video_widget.get_natural_size()
#                dh = self.height() - self.video_widget.height()
#                self.resize(int(w), int(h) + dh)  # resize window to video
            self._duration = self.video_widget.get_duration()
            if self._duration > 0:
                self._time_format = ('hh:mm:ss' if self._duration >= 3600 else 'mm:ss')
                self._duration_str = ' / ' + QTime(0, 0).addMSecs(int(1000 * self._duration)).toString(self._time_format)
            else:
                self._time_format = 'hh:mm:ss'
            self.slider_time.setEnabled(self._duration > 0)
            self.label_statusbar.setVisible(True)
            self.action_toggle_fullscreen.setEnabled(has_video)
            self.action_toggle_play.setEnabled(True)
            self.action_show_media_infos.setEnabled(not self.video_widget.is_url)
            for action in (self.action_add_to_favorites, self.action_close, self.action_play, self.action_pause, self.action_stop):
                action.setEnabled(True)
            for action in (self.action_skip_back, self.action_step_back, self.action_step_forward, self.action_skip_forward):
                action.setEnabled(self._duration > 0)
            self._timer.start()
            self.video_widget.play()
            self.action_play.setChecked(True)
            if self._caption:
                self.setWindowTitle(f'{self._caption} - {APP_NAME}')
            else:
                self.setWindowTitle(f'{os.path.basename(self.video_widget.filename)} - {APP_NAME}')

        else:
            self._timer.stop()
            self.slider_time.setEnabled(False)
            self.label_statusbar.setVisible(False)
            self.action_toggle_fullscreen.setEnabled(False)
            self.action_toggle_play.setEnabled(False)
            for action in (self.action_show_media_infos, self.action_add_to_favorites, self.action_close, self.action_play, self.action_pause, self.action_stop, self.action_skip_back,
                    self.action_step_back, self.action_step_forward, self.action_skip_forward):
                action.setEnabled(False)
            self.action_stop.setChecked(True)
            self.setWindowTitle(APP_NAME)
            self._reset_active_item()

    ########################################
    #
    ########################################
    def slot_open(self):
        filename, _ = QFileDialog.getOpenFileName(self, 'Select media file')
        if filename:
            self.load_media(filename)

    ########################################
    #
    ########################################
    def slot_open_url(self):
        dialog = QInputDialog(self)
        dialog.setWindowTitle('Open URL')
        dialog.setLabelText('Please enter a URL:')
        size = dialog.size()
        size.setWidth(400)
        dialog.resize(size)
        if IS_WIN:
            windll.dwmapi.DwmSetWindowAttribute(int(dialog.winId()),
                    DWMWA_USE_IMMERSIVE_DARK_MODE, byref(c_int(1)), 4)
        res = dialog.exec()
        if not res:
            return
        url = dialog.textValue()
        if url:
            self.load_media(url)

    ########################################
    #
    ########################################
    def slot_close_media(self):
        self._reset_active_item()
        self.video_widget.close_media()
        self.slot_ready(False)

#        self._timer_metadata.stop()
        self.statusbar.clearMessage()

    ########################################
    #
    ########################################
    def slot_about(self):
        msg = ('<b>{} v{}</b><br>(c) 2024 59de44955ebd<br><br>'
            'A simple media player for macOS and Windows, based on '
            'Python 3, PyQt5 and native system media frameworks '
            '(AVFoundation/DirectShow).<br>').format(APP_NAME, APP_VERSION)
        dialog = QMessageBox(QMessageBox.Information, 'About', msg, QMessageBox.Ok, parent=self)
        if IS_WIN:
            windll.dwmapi.DwmSetWindowAttribute(int(dialog.winId()),
                    DWMWA_USE_IMMERSIVE_DARK_MODE, byref(c_int(1)), 4)
        dialog.exec()

    ########################################
    #
    ########################################
    def slot_update_time(self):
        if self._duration > 0:
            self.slider_time.setValue(int(10000 * self.video_widget.get_time() / self._duration))
            self.label_statusbar.setText(QTime(0, 0).addMSecs(int(1000 * self.video_widget.get_time())).toString(self._time_format) + self._duration_str)
        else:
            self.label_statusbar.setText(QTime(0, 0).addMSecs(int(1000 * self.video_widget.get_time())).toString(self._time_format))

    ########################################
    #
    ########################################
    def slot_toggle_playback(self):
        # fixes an issue with DirectShow's message drain sending 2 key events simultaneously
        if IS_WIN:
            t = time.time()
            if t - self._last_play_toggle_time < .01:
                return
            self._last_play_toggle_time = t
        is_playing = self.video_widget.toggle_playback()
        if is_playing is None:
            return
        if is_playing:
            self.action_play.setChecked(True)
        else:
            self.action_pause.setChecked(True)

    ########################################
    #
    ########################################
    def slot_toggle_fullscreen(self):
        if not self.video_widget.has_video():
            return
        self._fullscreen = not self._fullscreen
        if self._fullscreen:
            self.video_widget.setParent(None)
            self.video_widget.showFullScreen()
        else:
            self.video_widget.showNormal()
            self.centralwidget.layout().insertWidget(0, self.video_widget)

    ########################################
    #
    ########################################
    def slot_double_clicked(self):
        self.video_widget.toggle_playback()
        self.slot_toggle_fullscreen()

    ########################################
    #
    ########################################
    def slot_show_media_infos(self):
        if self.video_widget.filename is None or self._duration == 0:
            return
        infos = subprocess.run([os.path.join(RES_DIR, 'mediainfo'), self.video_widget.filename],
                capture_output=True, shell=IS_WIN).stdout.decode().strip()
        self.dialog_media_infos.plainTextEdit.setPlainText(infos)
        self.dialog_media_infos.show()

    ########################################
    #
    ########################################
    def slot_add_to_favorites(self):
    	list_item = QListWidgetItem(self._caption if self._caption else os.path.basename(self.video_widget.filename))
    	list_item.setData(Qt.UserRole, self.video_widget.filename)
    	list_item.setFlags(list_item.flags() | Qt.ItemIsEditable)
    	self.listWidgetFavorites.addItem(list_item)

    ########################################
    #
    ########################################
    def slot_tv_livestreams_item_double_clicked(self, list_item):
        self._reset_active_item()
        list_item.setData(Qt.ForegroundRole, QColor('#2E9ADC'))
        list_item.setSelected(False)
        self._active_item = list_item
        self.activateWindow()
        self.listWidgetTVLivestreams.repaint()
        self.load_media(list_item.data(Qt.UserRole), list_item.text())

        def _loaded(res):
            res = json.loads(res)
            if 'shows' in res:
                show = res['shows'][0]
                tz = datetime.timezone(datetime.timedelta(hours=2))
                t_from = datetime.datetime.fromisoformat(show['startTime']).astimezone(tz).strftime('%H:%M')
                t_to = datetime.datetime.fromisoformat(show['endTime']).astimezone(tz).strftime('%H:%M')
                title = f"{show['title']} - {show['subtitle']}" if 'subtitle' in show and show['subtitle'] else show['title']
                self.statusbar.showMessage(title)
                list_item.setToolTip(f"<p>{t_from} - {t_to}<br><b>{title}</b><br><br>{show['description']}")
            else:
                list_item.setToolTip('')
        self._http_get('https://api.zapp.mediathekview.de/v1/shows/' + list_item.data(Qt.UserRole + 1), _loaded)

    ########################################
    #
    ########################################
    def slot_radio_search_return_pressed(self):
        s = self.lineEditRadioSearch.text()
        if not s:
            return

        if self._active_item and type(self._active_item) == QListWidgetItem and self._active_item.listWidget() == self.listWidgetRadioSearchResults:
            self._active_item = None

        self.listWidgetRadioSearchResults.clear()

        def _loaded(res):
            res = json.loads(res)
            for row in res['body']:
                if 'type' in row and row['type'] == 'audio' and 'URL' in row:
                	list_item = QListWidgetItem(row['text'])
                	list_item.setData(Qt.UserRole, row['URL'])
                	self.listWidgetRadioSearchResults.addItem(list_item)
            self.listWidgetRadioSearchResults.scrollToItem(self.listWidgetRadioSearchResults.item(0))
        self._http_get(f'http://opml.radiotime.com/Search.ashx?render=json&query={urllib.parse.quote(s)}', _loaded)

    ########################################
    #
    ########################################
    def slot_tv_search_return_pressed(self):
        s = self.lineEditTVSearch.text()
        if not s:
            return
        self.listWidgetTVSearchResults.clear()
        q = {
        	'queries': [
            	{'fields': ['title', 'topic', 'description'], 'query': s},  #'description' , 'topic'
            ],
            'future': 0,
        	'size': 500
        }
        url = 'https://mediathekviewweb.de/api/query?query=' + urllib.parse.quote(json.dumps(q))
        def _loaded(res):
            res = json.loads(res)['result']['results']
            for track in res:
            	list_item = QListWidgetItem(f"[{track['channel']}] {track['title']}")
            	list_item.setData(Qt.UserRole, track['url_video_hd'] if 'url_video_hd' in track else track['url_video'] )
            	list_item.setToolTip('<p>' + track['description'] + '</p>')
            	self.listWidgetTVSearchResults.addItem(list_item)
        self._http_get(url, _loaded)

    ########################################
    #
    ########################################
    def slot_radio_search_result_double_clicked(self, list_item):
        self._reset_active_item()
        list_item.setData(Qt.ForegroundRole, QColor('#2E9ADC'))
        list_item.setSelected(False)
        self._active_item = list_item
        self.activateWindow()
        self.listWidgetRadioSearchResults.repaint()

        def _loaded(res):
            stream_url = res.decode().split('\n')[0]
            print(stream_url)
            self.load_media(stream_url, list_item.text())

        self._http_get(list_item.data(Qt.UserRole), _loaded)

    ########################################
    #
    ########################################
    def slot_tv_search_result_double_clicked(self, list_item):
        self._reset_active_item()
        list_item.setData(Qt.ForegroundRole, QColor('#2E9ADC'))
        list_item.setSelected(False)
        self._active_item = list_item
        self.activateWindow()
        self.listWidgetRadioSearchResults.repaint()
        self.load_media(list_item.data(Qt.UserRole), list_item.text())

    ########################################
    #
    ########################################
    def slot_radio_directories_item_clicked(self, tree_item, column):
        if tree_item.childCount():
            return

        provider_id = tree_item.data(0, Qt.UserRole)

        if tree_item.parent() is None:

            if provider_id == NETRADIO_SHOUTCAST:
                def _loaded(res):
                    dom = minidom.parseString(res.decode())
                    elements = dom.getElementsByTagName('genre')
                    for element in elements:
                        child_item = QTreeWidgetItem([element.attributes['name'].value])
                        child_item.setData(0, Qt.UserRole, NETRADIO_SHOUTCAST)
                        child_item.setData(0, Qt.UserRole + 1, element.attributes['id'].value)
                        tree_item.addChild(child_item)
                    tree_item.setExpanded(True)
                self._http_get("http://api.shoutcast.com/genre/primary?k=fa1669MuiRPorUBw&f=xml", _loaded)

            elif provider_id == NETRADIO_SOMAFM:
                def _loaded(res):
                    dom = minidom.parseString(res.decode())
                    elements = dom.getElementsByTagName('channel')
                    for channel in elements:
                        child_item = QTreeWidgetItem([channel.getElementsByTagName('title')[0].childNodes[0].data])
                        child_item.setData(0, Qt.UserRole, NETRADIO_SOMAFM)
                        child_item.setData(0, Qt.UserRole + 1, channel.getElementsByTagName('fastpls')[0].childNodes[0].data)
                        tree_item.addChild(child_item)
                    tree_item.setExpanded(True)
                self._http_get("http://somafm.com/channels.xml", _loaded)

            elif provider_id == NETRADIO_TUNEIN:
                cat_url = "http://opml.radiotime.com/"
                def _loaded(res):
                    dom = minidom.parseString(res.decode())
                    elements = dom.getElementsByTagName('outline')
                    for element in elements:
                        child_item = QTreeWidgetItem([element.attributes['text'].value])
                        child_item.setData(0, Qt.UserRole, NETRADIO_TUNEIN)
                        child_item.setData(0, Qt.UserRole + 1, element.attributes['URL'].value)
                        tree_item.addChild(child_item)
                    tree_item.setExpanded(True)
                self._http_get("http://opml.radiotime.com/", _loaded)

        else:
            if provider_id == NETRADIO_SHOUTCAST:
                current_id = tree_item.data(0, Qt.UserRole + 1)
                if tree_item.parent().parent() is None:
                    def _loaded(res):
                        dom = minidom.parseString(res.decode())
                        elements = dom.getElementsByTagName('genre')
                        for element in elements:
                            child_item = QTreeWidgetItem([element.attributes['name'].value])
                            child_item.setData(0, Qt.UserRole, NETRADIO_SHOUTCAST)
                            child_item.setData(0, Qt.UserRole + 1, element.attributes['id'].value)
                            tree_item.addChild(child_item)
                        tree_item.setExpanded(True)
                    self._http_get("http://api.shoutcast.com/genre/secondary?k=fa1669MuiRPorUBw&f=xml&parentid=" + current_id, _loaded)

                elif tree_item.parent().parent().parent() is None:
                    def _loaded(res):
                        dom = minidom.parseString(res.decode())
                        elements = dom.getElementsByTagName('station')
                        for element in elements:
                            child_item = QTreeWidgetItem([element.attributes['name'].value])
                            child_item.setData(0, Qt.UserRole, NETRADIO_SHOUTCAST)
                            child_item.setData(0, Qt.UserRole + 1, element.attributes['id'].value)
                            tree_item.addChild(child_item)
                        tree_item.setExpanded(True)
                    self._http_get("http://api.shoutcast.com/station/advancedsearch?k=fa1669MuiRPorUBw&f=xml&genre_id=" + current_id, _loaded)

                else:
                    def _loaded(res):
                        # parse .pls
                        data = {}
                        for line in res.decode().split('\n'):
                            if '=' in line:
                                parts = line.split('=', 2)
                                data[parts[0]] = parts[1]
                        if 'File1' in data:
                            self._reset_active_item()
                            self._active_item = tree_item
                            tree_item.setData(0, Qt.ForegroundRole, QColor('#2E9ADC'))
                            tree_item.setSelected(False)
                            self.load_media(data['File1'], tree_item.text(0))
                    self._http_get(f"http://yp.shoutcast.com/sbin/tunein-station.pls?id={current_id}&type=.pls", _loaded)

            elif provider_id == NETRADIO_SOMAFM:
                def _loaded(res):
                    # parse .pls
                    data = {}
                    for line in res.decode().split('\n'):
                        if '=' in line:
                            parts = line.split('=', 2)
                            data[parts[0]] = parts[1]
                    if 'File1' in data:
                        self._reset_active_item()
                        self._active_item = tree_item
                        tree_item.setData(0, Qt.ForegroundRole, QColor('#2E9ADC'))
                        tree_item.setSelected(False)
                        self.load_media(data['File1'], tree_item.text(0))
                self._http_get(tree_item.data(0, Qt.UserRole + 1), _loaded)

            elif provider_id == NETRADIO_TUNEIN:
                def _loaded(res):
                    res = res.decode()
                    if res.startswith('<?xml'):
                        dom = minidom.parseString(res)
                        elements = dom.getElementsByTagName('outline')
                        for element in elements:
                            if 'URL' in element.attributes:
                                child_item = QTreeWidgetItem([element.attributes['text'].value])
                                child_item.setData(0, Qt.UserRole, NETRADIO_TUNEIN)
                                child_item.setData(0, Qt.UserRole + 1, element.attributes['URL'].value)
                                tree_item.addChild(child_item)
                        tree_item.setExpanded(True)
                    else:
                        self._reset_active_item()
                        self._active_item = tree_item
                        tree_item.setData(0, Qt.ForegroundRole, QColor('#2E9ADC'))
                        tree_item.setSelected(False)
                        url = res.split('\n')[0]
                        self.load_media(url, tree_item.text(0))
                self._http_get(tree_item.data(0, Qt.UserRole + 1), _loaded)

    ########################################
    #
    ########################################
    def slot_favorite_double_clicked(self, list_item):
        self._reset_active_item()
        list_item.setData(Qt.ForegroundRole, QColor('#2E9ADC'))
        list_item.setSelected(False)
        self._active_item = list_item
        self.activateWindow()
        self.listWidgetFavorites.repaint()
        self.load_media(list_item.data(Qt.UserRole), list_item.text())

    ########################################
    # macos: title, artist/author, description, albumname, type
    # win: author, title, description
    ########################################
    def slot_metadata_changed(self, metadata):
        if metadata:
            if 'artist' in metadata:
                metadata['author'] = metadata['artist']
            if 'title' in metadata and 'author' in metadata:
                self.statusbar.showMessage(f"Title: {metadata['title']}  |  Author: {metadata['author']}")
            elif 'author' in metadata:
                self.statusbar.showMessage(f"Author: {metadata['author']}")
            elif 'title' in metadata:
                self.statusbar.showMessage(f"Title: {metadata['title']}")
        else:
            self.statusbar.clearMessage()


if __name__ == '__main__':
    sys.excepthook = traceback.print_exception
    if IS_MAC and IS_FROZEN:
        class MyApplication(QApplication):
            fileOpened = pyqtSignal(str)
            def event(self, e):
                if e.type() == QEvent.FileOpen:
                    self.fileOpened.emit(e.file())
                return super().event(e)
        app = MyApplication(sys.argv)
    else:
        app = QApplication(sys.argv)
    app.setAttribute(Qt.AA_DontShowIconsInMenus)
    main = Main(app)
    sys.exit(app.exec_())
