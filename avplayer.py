from ctypes import c_void_p

import AVFoundation
from Cocoa import NSURL, NSMakeRect
import CoreMedia
import MediaToolbox
import objc

from PyQt5.QtCore import Qt, pyqtSignal, QTimer, QUrl
from PyQt5.QtWidgets import QWidget
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest


class VideoWidget(QWidget):

    mediaReady = pyqtSignal(bool)
    mousePressed = pyqtSignal()
    doubleClicked = pyqtSignal()
    metadataChanged = pyqtSignal(dict)

    ########################################
    #
    ########################################
    def __init__(self, parent=None):
        super().__init__()

        self.filename = None
        self.is_url = False

        self._volume = 1.
        self._muted = False
        self._metadata = None
        self._is_icy = False

        self._player = None
        self._playerLayer = None

        self._timer_ready = QTimer(self)
        self._timer_ready.setInterval(50)
        self._timer_ready.timeout.connect(self.__check_ready)

        # make window background black
        self.setAutoFillBackground(True)
        p = self.palette()
        p.setColor(self.backgroundRole(), Qt.black)
        self.setPalette(p)

        # cast QWidget to NSView
        self._view = objc.objc_object(c_void_p=c_void_p(int(self.winId())))
        self._view.setWantsLayer_(True)

        MediaToolbox.MTRegisterProfessionalVideoWorkflowFormatReaders()

        # ugly polling for metadata in case of shoutcast streams, causing extra traffic
        # but the native AVPlayerItemMetadataOutput API would be really tricky to implement
        self._timer_metadata = QTimer(self)
        self._timer_metadata.setInterval(8000)
        self._timer_metadata.timeout.connect(self.__check_metadata)

        self._net_manager = QNetworkAccessManager(self)
        self._req_icy = QNetworkRequest()
        self._req_icy.setRawHeader(b'Icy-MetaData', b'1')

    ########################################
    #
    ########################################
    def __parse_http_headers(self, reply):
        res = {}
        for k,v in reply.rawHeaderPairs():
            res[k.data().decode().lower()] = v.data().decode()
        return res

    ########################################
    #
    ########################################
    def __check_ready(self):
        status = self._player.currentItem().status() if self._player.currentItem() else None
        if status:
            self._timer_ready.stop()
            if status != 1:
                self.filename = None

            if self.is_url and not self.has_video():
                self._req_icy.setUrl(QUrl(self.filename))
                reply = self._net_manager.get(self._req_icy)
                def _metadata_available():
                    reply.abort()
                    headers = self.__parse_http_headers(reply)
                    self._is_icy = 'icy-metaint' in headers
                    self.mediaReady.emit(status == 1)  # 2 means failed
                    if self._is_icy:
                        self._metaint = int(headers['icy-metaint'])
                        self.__check_metadata()
                        self._timer_metadata.start()
                reply.metaDataChanged.connect(_metadata_available)
            else:
                self.mediaReady.emit(status == 1)  # 2 means failed
                cm = self._player.currentItem().asset().commonMetadata()
                metadata = {}
                for k in cm:
                    metadata[k.commonKey().lower()] = k.value()
                if metadata:
                    self.metadataChanged.emit(metadata)

    ########################################
    #
    ########################################
    def __check_metadata(self):
        reply = self._net_manager.get(self._req_icy)
        reply.setReadBufferSize(self._metaint + 256)  # ???
        def _loaded(reply=reply):
            if reply.bytesAvailable() >= self._metaint + 256:
                data = reply.readAll().data()[self._metaint:]
                reply.abort()
                try:
                    metadata = {}
                    for line in data[1:data[0] * 16].strip(b'\0').split(b';'):
                        if line:
                            k, v = line.split(b'=', 2)
                            if v.startswith(b"'"):
                                v = v[1:-1]
                            k = k.decode().lower()
                            if k.startswith('stream'):
                                k = k[6:]
                            metadata[k] = v.decode()
                    if metadata != self._metadata:
                        self._metadata = metadata
                        self.metadataChanged.emit(metadata)
                except:
                    print('parsing metadata failed')
        reply.readyRead.connect(_loaded)

    ########################################
    #
    ########################################
    def load_media(self, filename: str):
        if self._player is not None:
            self.close_media()
        self.filename = filename
        self.is_url = filename.startswith('http://') or filename.startswith('https://')
        if self.is_url:
            url = NSURL.URLWithString_(filename)
        else:
            url = NSURL.fileURLWithPath_(filename)
        self._player = AVFoundation.AVPlayer.playerWithURL_(url)

        # create AVPlayerLayer
        self._playerLayer = AVFoundation.AVPlayerLayer.playerLayerWithPlayer_(self._player)
        g = self.geometry()
        self._playerLayer.setFrame_(NSMakeRect(0, 0, g.width(), g.height()))
        self._playerLayer.setAutoresizingMask_(18)  # kCALayerWidthSizable=2 | kCALayerHeightSizable=16
        self._view.layer().addSublayer_(self._playerLayer)
        self._player.setVolume_(0 if self._muted else self._volume)

        self._timer_ready.start()

    ########################################
    #
    ########################################
    def close_media(self):
        self.filename = None
        self._is_icy = False
        if self._player:
            self._player.setRate_(0.)
            self._player = None
        if self._playerLayer:
            self._playerLayer.removeFromSuperlayer()
            self._playerLayer = None
        self.repaint()
        self._timer_metadata.stop()

    ########################################
    #
    ########################################
    def step(self, steps: int=1):
        if self._player is None:
            return
        self._player.currentItem().stepByCount_(steps)

    ########################################
    # as seconds (floaz)
    ########################################
    def get_duration(self):
        if self._player is None:
            return
        cm = self._player.currentItem().duration()
        return cm.value / cm.timescale if not self._is_icy and cm.timescale else 0

    ########################################
    #
    ########################################
    def get_fps(self):
        if self._player is None:
            return
        video_tracks = self._player.currentItem().asset().tracksWithMediaType_(AVFoundation.AVMediaTypeVideo)
        if len(video_tracks):
            return video_tracks[0].nominalFrameRate()

    ########################################
    #T ODO: fails for single video-only stream
    ########################################
    def get_natural_size(self):
        if self._player is None:
            return
        asset = self._player.currentItem().asset()
        video_tracks = asset.tracksWithMediaType_(AVFoundation.AVMediaTypeVideo)
        if len(video_tracks):
            size = video_tracks[0].naturalSize()
            return size.width, size.height
        max_height = 0
        size = None
        for v in asset.variants():
            s = v.videoAttributes().presentationSize()
            if s.height > max_height:
                size = s
                max_height = s.height
        if size:
            return size.width, size.height

    ########################################
    # TODO: fails for single video-only stream
    ########################################
    def has_video(self):
        if self._player is None:
            return False
        asset = self._player.currentItem().asset()
        if len(asset.tracksWithMediaType_(AVFoundation.AVMediaTypeVideo)) > 0:
            return True
        for v in asset.variants():
            s = v.videoAttributes().presentationSize()
            if s.height > 0:
                return True
        return False

    ########################################
    # TODO: fails for single audio-only stream
    ########################################
    def has_audio(self):
        if self._player is None:
            return False
        asset = self._player.currentItem().asset()
        if len(asset.tracksWithMediaType_(AVFoundation.AVMediaTypeAudio)) > 0:
            return True
        # fails for single audio-only stream
        return len(asset.variants()) > 0

    ########################################
    # 0..1 (float)
    ########################################
    def get_volume(self):
        return self._volume

    ########################################
    # 0..1 (float)
    ########################################
    def set_volume(self, volume: float):
        self._volume = volume
        if self._player is None:
            return
        if not self._muted:
            self._player.setVolume_(float(volume))

    ########################################
    #
    ########################################
    def set_muted(self, flag: bool):
        self._muted = flag
        if self._player:
            self._player.setVolume_(0 if flag else self._volume)

    ########################################
    # as seconds (float)
    ########################################
    def seek_to_time(self, sec: float):
        if self._player is None:
            return
        cm = self._player.currentItem().duration()
        cm.value = cm.timescale * sec
        self._player.seekToTime_(cm)

    ########################################
    # as seconds (float)
    ########################################
    def get_time(self):
        if self._player is None:
            return
        cm = self._player.currentTime()
        return cm.value / cm.timescale if cm.timescale else 0

    ########################################
    #
    ########################################
    def play(self):
        if self._player is None:
            return
        self._player.setRate_(1.0)

    ########################################
    #
    ########################################
    def pause(self):
        if self._player is None:
            return
        self._player.setRate_(0.0)

    ########################################
    # returns is_playing as bool
    ########################################
    def toggle_playback(self):
        if self._player is None:
            return False
        rate = 1 - self._player.rate()
        self._player.setRate_(rate)
        return rate > 0

    ########################################
    #
    ########################################
    def mousePressEvent(self, e):
        self.mousePressed.emit()

    ########################################
    #
    ########################################
    def mouseDoubleClickEvent(self, e):
        self.doubleClicked.emit()
