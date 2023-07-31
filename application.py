# coding: utf8

from PySide2 import QtCore, QtWidgets
from PySide2.QtCore import *
from PySide2.QtGui import *

import sys
import time
import math

from autobahn.twisted.websocket import WebSocketServerProtocol, WebSocketServerFactory, listenWS
from twisted.internet import reactor
from twisted.python import log
from twisted.web.server import Site
from twisted.web.static import File

import json
import os
import urllib.request, urllib.error, urllib.parse
import webbrowser
import glob

import numpy
import cv2
from cv2 import * # OpenCV imports
import psutil # CPU usage

if getattr(sys, 'frozen', False):
	_applicationPath = os.path.dirname(sys.executable)
elif __file__:
	_applicationPath = os.path.dirname(__file__)

_settingsFilePath = os.path.join(_applicationPath, 'settings.ini')

GroupBoxStyleSheet = "QGroupBox { border: 1px solid #AAAAAA;margin-top: 12px;} QGroupBox::title {top: -5px;left: 10px;}"


def shiftImage(in_img, x, y):
	_img = in_img
	if(x >= 0):
		_img = _img[0:_img.shape[0], x:_img.shape[1]]
	else:
		_img = copyMakeBorder(_img,0,0,abs(x),0,BORDER_CONSTANT, value=[255,255,255])
	if(y >= 0):
		_img = _img[y:_img.shape[0], 0:_img.shape[1]]
	else:
		_img = copyMakeBorder(_img,abs(y),0,0,0,BORDER_CONSTANT, value=[255,255,255])
	return _img

def autocrop(image, threshold=0):
	"""Crops any edges below or equal to threshold
	Crops blank image to 1x1.
	Returns cropped image.
	"""
	if(image is None):
		size = 1, 1, 1
		image = numpy.zeros(size, dtype=numpy.uint8)

	if len(image.shape) == 3:
		flatImage = numpy.max(image, 2)
	else:
		flatImage = image
	assert len(flatImage.shape) == 2

	rows = numpy.where(numpy.max(flatImage, 0) > threshold)[0]
	if rows.size:
		cols = numpy.where(numpy.max(flatImage, 1) > threshold)[0]
		image = image[cols[0]: cols[-1] + 1, rows[0]: rows[-1] + 1]
	else:
		image = image[:1, :1]

	return image

DIGITS_LOOKUP = {
    (1, 1, 1, 1, 1, 1, 0): 0,
    (0, 1, 1, 0, 0, 0, 0): 1,
    (1, 1, 0, 1, 1, 0, 1): 2,
    (1, 1, 1, 1, 0, 0, 1): 3,
    (0, 1, 1, 0, 0, 1, 1): 4,
    (1, 0, 1, 1, 0, 1, 1): 5,
    (1, 0, 1, 1, 1, 1, 1): 6,
    (1, 1, 1, 0, 0, 0, 0): 7,
    (1, 1, 1, 1, 1, 1, 1): 8,
    (1, 1, 1, 0, 0, 1, 1): 9,
    (0, 0, 0, 0, 0, 0, 0): ''
}

def parseSingleDigit(segment_image, previous_digit):
	##### check for individual elements #####
		# seg A - 0:20, 20:30, # seg B - 20:30, 30:50, # seg C - 40:50, 30:50, # seg D - 50:70, 20:30, # seg E - 40:50, 0:20, # seg F - 20:30, 0:20, # seg G - 30:40, 20:30	
	segments = {
		"a": numpy.mean(segment_image[0:20,20:30]) < 200,
		"b": numpy.mean(segment_image[20:30,30:50]) < 200,
		"c": numpy.mean(segment_image[40:50,30:50]) < 200,
		"d": numpy.mean(segment_image[50:70,20:30]) < 200,
		"e": numpy.mean(segment_image[40:50,0:20]) < 200,
		"f": numpy.mean(segment_image[20:30,0:20]) < 200,
		"g": numpy.mean(segment_image[30:40,20:30]) < 200
	}

	if tuple(segments.values()) in DIGITS_LOOKUP.keys():
		digit = DIGITS_LOOKUP[tuple(segments.values())]
	else:
		digit = previous_digit

	return digit

class MainWindow(QtWidgets.QMainWindow):
	def __init__(self, parent=None):
		super(MainWindow, self).__init__(parent)

		######## QSettings #########
		self.qsettings = QSettings(_settingsFilePath, QSettings.IniFormat)
		self.qsettings.setFallbacksEnabled(False)

		######## ACTIONS ###########
		exitItem = QtWidgets.QAction('Exit', self)
		exitItem.setStatusTip('Exit application...')
		exitItem.triggered.connect(self.close)

		self.openChromaKeyDisplay = QtWidgets.QAction('Open Key Output for Vision Mixer', self)
		self.openChromaKeyDisplay.setStatusTip('Open chroma-key output display for the vision mixer...')
		self.openChromaKeyDisplay.triggered.connect(lambda: webbrowser.open_new("http://localhost:8080/"))
		######## END ACTIONS ###########


		menubar = self.menuBar()
		fileMenu = menubar.addMenu('&File')
		fileMenu.addAction(self.openChromaKeyDisplay)
		fileMenu.addSeparator()
		fileMenu.addAction(exitItem)


		self.main_widget = Window(self)
		self.setCentralWidget(self.main_widget)
		self.statusBar()
		self.setWindowTitle('Score OCR and TV Graphic Control')
		self.resize(1000,400)
		self.show()


class Window(QtWidgets.QWidget):
	def __init__(self, parent):
		super(Window, self).__init__(parent)
		grid = QtWidgets.QGridLayout()
		self.qsettings = QSettings(_settingsFilePath, QSettings.IniFormat)
		self.qsettings.setFallbacksEnabled(False)

		self.updateScoreboard = QtWidgets.QPushButton("Update")
		self.updateScoreboard.clicked.connect(self.sendCommandToBrowser)

		self.GCOCRCoordinates = {
			"clock_1": [QtWidgets.QLabel("Clock *0:00"), QtWidgets.QLineEdit(""), QtWidgets.QLineEdit(""), QtWidgets.QLineEdit(""), QtWidgets.QLineEdit(""), QtWidgets.QLabel("0"), QtWidgets.QLabel("0"), QtWidgets.QLabel("*"), QtWidgets.QLabel("-")],
			"clock_2": [QtWidgets.QLabel("Clock 0*:00"), QtWidgets.QLineEdit(""), QtWidgets.QLineEdit(""), QtWidgets.QLineEdit(""), QtWidgets.QLineEdit(""), QtWidgets.QLabel("0"), QtWidgets.QLabel("0"), QtWidgets.QLabel("*"), QtWidgets.QLabel("-")],
			"clock_3": [QtWidgets.QLabel("Clock 00:*0"), QtWidgets.QLineEdit(""), QtWidgets.QLineEdit(""), QtWidgets.QLineEdit(""), QtWidgets.QLineEdit(""), QtWidgets.QLabel("0"), QtWidgets.QLabel("0"), QtWidgets.QLabel("*"), QtWidgets.QLabel("-")],
			"clock_4": [QtWidgets.QLabel("Clock 00:0*"), QtWidgets.QLineEdit(""), QtWidgets.QLineEdit(""), QtWidgets.QLineEdit(""), QtWidgets.QLineEdit(""), QtWidgets.QLabel("0"), QtWidgets.QLabel("0"), QtWidgets.QLabel("*"), QtWidgets.QLabel("-")],
			"clock_colon": [QtWidgets.QLabel("Clock :"), QtWidgets.QLineEdit(""), QtWidgets.QLineEdit(""), QtWidgets.QLineEdit(""), QtWidgets.QLineEdit(""), QtWidgets.QLabel("0"), QtWidgets.QLabel("0"), QtWidgets.QLabel("*"), QtWidgets.QLabel("-")],
			"shot_clock_1": [QtWidgets.QLabel("Shot Clock *0"), QtWidgets.QLineEdit(""), QtWidgets.QLineEdit(""), QtWidgets.QLineEdit(""), QtWidgets.QLineEdit(""), QtWidgets.QLabel("0"), QtWidgets.QLabel("0"), QtWidgets.QLabel("*"), QtWidgets.QLabel("-")],
			"shot_clock_2": [QtWidgets.QLabel("Shot Clock 0*"), QtWidgets.QLineEdit(""), QtWidgets.QLineEdit(""), QtWidgets.QLineEdit(""), QtWidgets.QLineEdit(""), QtWidgets.QLabel("0"), QtWidgets.QLabel("0"), QtWidgets.QLabel("*"), QtWidgets.QLabel("-")],
			"shot_clock_decimal": [QtWidgets.QLabel("Shot Clock ."), QtWidgets.QLineEdit(""), QtWidgets.QLineEdit(""), QtWidgets.QLineEdit(""), QtWidgets.QLineEdit(""), QtWidgets.QLabel("0"), QtWidgets.QLabel("0"), QtWidgets.QLabel("*"), QtWidgets.QLabel("-")]
		}

		self.SCssocrArguments = QtWidgets.QLineEdit(self.qsettings.value("SCssocrArguments", "crop 0 0 450 200 mirror horiz shear 10 mirror horiz gray_stretch 100 254 invert remove_isolated -T "))
		self.SCrotation = QtWidgets.QLineEdit(self.qsettings.value("SCrotation", "0"))
		self.SCskewx = QtWidgets.QLineEdit(self.qsettings.value("SCskewx", "5"))
		self.SCerosion = QtWidgets.QLineEdit(self.qsettings.value("SCerosion", "2"))
		self.SCthreshold = QtWidgets.QLineEdit(self.qsettings.value("SCthreshold", "127"))
		self.SCcropLeft = QtWidgets.QLineEdit(self.qsettings.value("LCrop", "0"))
		self.SCcropTop = QtWidgets.QLineEdit(self.qsettings.value("TCrop", "0"))
		self.SCvideoCaptureIndex = QtWidgets.QLineEdit(self.qsettings.value("SCvideoCaptureIndex", '0'))
		self.SCwaitKey = QtWidgets.QLineEdit(self.qsettings.value("SCwaitKey", '300'))
		self.startSCOCRButton = QtWidgets.QPushButton("Start OCR")
		self.startSCOCRButton.clicked.connect(self.init_SCOCRWorker)
		self.terminateSCOCRButton = QtWidgets.QPushButton("Stop OCR")
		self.terminateSCOCRButton.clicked.connect(self.terminate_SCOCRWorker)

		self.slider_skewx = QtWidgets.QSlider()
		self.slider_skewx.setOrientation(Qt.Horizontal)
		self.slider_skewx.setMinimum(-90)
		self.slider_skewx.setMaximum(90)
		self.slider_skewx.setValue(int(self.qsettings.value("SCskewx", "5")))

		self.previewImageRaw = QtWidgets.QLabel("")
		self.previewImageProcessed = QtWidgets.QLabel("")

		self.CPUpercentage = QtWidgets.QLabel("0 %")
		self.gameClock = QtWidgets.QLabel("00:00")
		self.shotClock = QtWidgets.QLabel("00")

		self.initializeOCRCoordinatesList()

		grid.addWidget(self.createGC_OCR_Group(), 0, 2, 4, 1) # MUST BE HERE, initializes all QObject lists
		grid.addWidget(self.createParametersGroup(), 4, 1, 1, 1) # MUST BE HERE, initializes all QObject lists
		grid.addWidget(self.createCameraPreviewGroup(), 0, 1, 4, 1) # MUST BE HERE, initializes all QObject lists
		grid.addWidget(self.createDebugGroup(), 5, 1, 2, 1) # MUST BE HERE, initializes all QObject lists
		grid.addWidget(self.updateScoreboard, 6, 0, 1, 1) # MUST BE HERE, initializes all QObject lists
		
		self.init_WebSocketsWorker() # Start ws:// server at port 9000
		#self.init_OCRWorker() # Start OpenCV, open webcam

		grid.setColumnStretch(0,100)
		grid.setColumnStretch(1,100)
		grid.setColumnStretch(2,100)

		grid.setHorizontalSpacing(10)
		grid.setVerticalSpacing(10)
		self.setLayout(grid)

	def closeEvent(self, event):
		self.terminate_SCOCRWorker()
	
	def initializeOCRCoordinatesList(self):
		_loadedGCOCRCoordinates = self.qsettings.value("OCRcoordinates")

		for key, param in self.GCOCRCoordinates.items():
			for index, qobj in enumerate(param):
				qobj.setText(_loadedGCOCRCoordinates[key][index])

	def sendCommandToBrowser(self):
		msg = {
			'gameID': '',
			'ticker': '',
			'game_over': '',
			'guest': { 
						'imagePath': '',
						'color': ''
			},
			'home': { 
						'imagePath': '',
						'color': ''
			}
		}

		msg['guest']['imagePath'] = self.teamAImagePath.text()
		msg['guest']['color'] = self.teamAColor.text()
		msg['home']['imagePath'] = self.teamBImagePath.text()
		msg['home']['color'] = self.teamBColor.text()
		msg['gameID'] = self.gameID.text().strip()
		msg["game_over"] = self.gameOverCheckBox.isChecked()


		if self.tickerRadioGroup.checkedId() == 0:
			msg["ticker"] = self.tickerTextLineEdit.text()


		print(msg)
		self.webSocketsWorker.send(json.dumps(msg));

	def init_WebSocketsWorker(self):
		self.webSocketsWorker = WebSocketsWorker()
		self.webSocketsWorker.error.connect(self.close)
		self.webSocketsWorker.start()# Call to start WebSockets server

	def init_SCOCRWorker(self):
		self.SCOCRWorker = SCOCRWorker(self.returnOCRCoordinatesList(), self.SCssocrArguments.text(), self.SCwaitKey.text(), self.SCvideoCaptureIndex.text(), self.SCrotation.text(), self.SCskewx.text(), self.SCerosion.text(), self.SCthreshold.text(), self.SCcropLeft.text(), self.SCcropTop.text())
		self.SCOCRWorker.error.connect(self.close)
		self.SCOCRWorker.recognizedDigits.connect(self.SCOCRhandler)
		self.SCOCRWorker.processedFrameFlag.connect(lambda: self.CPUpercentage.setText('CPU: ' + str(psutil.cpu_percent()) + "%"))
		self.SCOCRWorker.QImageFrame.connect(self.SCOCRPreviewImageHandler)
		self.SCOCRWorker.run() # Call to start OCR openCV thread

	def terminate_SCOCRWorker(self):
		self.SCOCRWorker.kill()
		del(self.SCOCRWorker)

	def SCOCRPreviewImageHandler(self, QImageFrame):
		_pixmapRaw = QPixmap.fromImage(QImageFrame[0])
		_pixmapProcessed = QPixmap.fromImage(QImageFrame[1])
		self.previewImageRaw.setPixmap(_pixmapRaw.scaled(500, 500, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
		self.previewImageProcessed.setPixmap(_pixmapProcessed.scaled(500, 500, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))

	def SCOCRhandler(self, digitDict): # Receives [self.digitL, self.digitR] from SCOCRWorker
		self.GCOCRCoordinates["clock_1"][8].setText(str(digitDict["clock_1"]))
		self.GCOCRCoordinates["clock_2"][8].setText(str(digitDict["clock_2"]))
		self.GCOCRCoordinates["clock_3"][8].setText(str(digitDict["clock_3"]))
		self.GCOCRCoordinates["clock_4"][8].setText(str(digitDict["clock_4"]))
		self.GCOCRCoordinates["clock_colon"][8].setText(str(digitDict["clock_colon"]))
		self.GCOCRCoordinates["shot_clock_1"][8].setText(str(digitDict["shot_clock_1"]))
		self.GCOCRCoordinates["shot_clock_2"][8].setText(str(digitDict["shot_clock_2"]))
		self.GCOCRCoordinates["shot_clock_decimal"][8].setText(str(digitDict["shot_clock_decimal"]))

		msg_game = {
			"shot_clock": digitDict["shot_clock"],
			"clock": digitDict["clock"],
		}

		packet = {
			"game": msg_game
		}

		self.gameClock.setText(msg_game["clock"])
		self.shotClock.setText(msg_game["shot_clock"])
		self.webSocketsWorker.send(json.dumps(packet))

	def returnOCRCoordinatesList(self): # Returns 1:1 copy of self.GCOCRCoordinates without QObjects
		response = {
			"clock_1": ["", "", "", "", "", "", "", "", ""],
			"clock_2": ["", "", "", "", "", "", "", "", ""],
			"clock_3": ["", "", "", "", "", "", "", "", ""],
			"clock_4": ["", "", "", "", "", "", "", "", ""],
			"clock_colon": ["", "", "", "", "", "", "", "", ""],
			"shot_clock_1": ["", "", "", "", "", "", "", "", ""],
			"shot_clock_2": ["", "", "", "", "", "", "", "", ""],
			"shot_clock_decimal": ["", "", "", "", "", "", "", "", ""]
		}
		for key, param in self.GCOCRCoordinates.items():
			for index, qobj in enumerate(param):
				response[key][index] = qobj.text()

		return response

	def widthHeightAutoFiller(self): # Calculates width and height, then saves to settings.ini file
		for key, value in self.GCOCRCoordinates.items():
			tl_X = int('0' + value[1].text()) # '0' to avoid int('') empty string error
			tl_Y = int('0' + value[2].text())
			br_X = int('0' + value[3].text())
			br_Y = int('0' + value[4].text())
			value[5].setText(str(br_X - tl_X))
			value[6].setText(str(br_Y - tl_Y))

		self.qsettings.setValue("OCRcoordinates", self.returnOCRCoordinatesList())
		self.qsettings.setValue("SCssocrArguments", self.SCssocrArguments.text())
		self.qsettings.setValue("SCrotation", self.SCrotation.text())
		self.qsettings.setValue("SCskewx", self.SCskewx.text())
		self.qsettings.setValue("SCThreshold", self.SCthreshold.text())
		self.qsettings.setValue("SCerosion", self.SCerosion.text())
		self.qsettings.setValue("TCrop", self.SCcropTop.text())
		self.qsettings.setValue("LCrop", self.SCcropLeft.text())
		self.qsettings.setValue("SCwaitKey", self.SCwaitKey.text())
		self.qsettings.setValue("SCvideoCaptureIndex", self.SCvideoCaptureIndex.text())
		
		try:
			self.SCOCRWorker.importOCRCoordinates(self.returnOCRCoordinatesList())
			self.SCOCRWorker.ssocrArguments = self.SCssocrArguments.text()
			self.SCOCRWorker.rotation = int(self.SCrotation.text())
			self.SCOCRWorker.skewx = int(self.SCskewx.text())
			self.SCOCRWorker.threshold = int(self.SCthreshold.text())
			self.SCOCRWorker.erosion = int(self.SCerosion.text())
			self.SCOCRWorker.cropLeft = int(self.SCcropLeft.text())
			self.SCOCRWorker.cropTop = int(self.SCcropTop.text())
			self.SCOCRWorker.waitKey = self.SCwaitKey.text()
		except:
			pass

	def createGC_OCR_Group(self):
		groupBox = QtWidgets.QGroupBox("Bounding Boxes")
		groupBox.setStyleSheet(GroupBoxStyleSheet)

		grid = QtWidgets.QGridLayout()
		grid.setHorizontalSpacing(10)
		grid.setVerticalSpacing(2)

		dividerLine = QtWidgets.QFrame()
		dividerLine.setFrameShape(QtWidgets.QFrame.HLine)
		dividerLine.setFrameShadow(QtWidgets.QFrame.Sunken)

		_tlLabel = QtWidgets.QLabel("Top-Left")
		_brLabel = QtWidgets.QLabel("Bottom-Right")
		_tlLabel.setAlignment(Qt.AlignCenter)
		_brLabel.setAlignment(Qt.AlignCenter)
		grid.addWidget(_tlLabel, 0, 1, 1, 2)
		grid.addWidget(_brLabel, 0, 3, 1, 2)

		grid.addWidget(QtWidgets.QLabel(""), 1, 0)
		grid.addWidget(QtWidgets.QLabel("X"), 1, 1)
		grid.addWidget(QtWidgets.QLabel("Y"), 1, 2)
		grid.addWidget(QtWidgets.QLabel("X"), 1, 3)
		grid.addWidget(QtWidgets.QLabel("Y"), 1, 4)
		grid.addWidget(QtWidgets.QLabel("Width"), 1, 5)
		grid.addWidget(QtWidgets.QLabel("Height"), 1,6)
		grid.addWidget(QtWidgets.QLabel("Scan"), 1,7)
		grid.addWidget(QtWidgets.QLabel("OCR"), 1,8)

		for key, param in self.GCOCRCoordinates.items(): # Right justify parameter QLabels
			param[0].setAlignment(Qt.AlignRight)
			param[1].setValidator(QIntValidator()) # Require integer pixel input
			param[2].setValidator(QIntValidator())
			param[3].setValidator(QIntValidator())
			param[4].setValidator(QIntValidator())
			param[1].setMaxLength(3) # Set 3 digit maximum for pixel coordinates
			param[2].setMaxLength(3)
			param[3].setMaxLength(3)
			param[4].setMaxLength(3)
			param[1].editingFinished.connect(self.widthHeightAutoFiller) # On change in X or Y, update width + height
			param[2].editingFinished.connect(self.widthHeightAutoFiller)
			param[3].editingFinished.connect(self.widthHeightAutoFiller)
			param[4].editingFinished.connect(self.widthHeightAutoFiller)
			param[5].setAlignment(Qt.AlignCenter)
			param[6].setAlignment(Qt.AlignCenter)
			param[7].setAlignment(Qt.AlignCenter)
			param[8].setAlignment(Qt.AlignCenter)
			_img = QImage(15, 21, QImage.Format_RGB888)
			_img.fill(0)
			param[7].setPixmap(QPixmap.fromImage(_img))



		for index, qobj in enumerate(self.GCOCRCoordinates["clock_1"]):
			grid.addWidget(qobj, 2, index)
		for index, qobj in enumerate(self.GCOCRCoordinates["clock_2"]):
			grid.addWidget(qobj, 3, index)
		for index, qobj in enumerate(self.GCOCRCoordinates["clock_3"]):
			grid.addWidget(qobj, 4, index)
		for index, qobj in enumerate(self.GCOCRCoordinates["clock_4"]):
			grid.addWidget(qobj, 5, index)
		for index, qobj in enumerate(self.GCOCRCoordinates["clock_colon"]):
			grid.addWidget(qobj, 6, index)
		for index, qobj in enumerate(self.GCOCRCoordinates["shot_clock_1"]):
			grid.addWidget(qobj, 17, index)
		for index, qobj in enumerate(self.GCOCRCoordinates["shot_clock_2"]):
			grid.addWidget(qobj, 18, index)
		for index, qobj in enumerate(self.GCOCRCoordinates["shot_clock_decimal"]):
			grid.addWidget(qobj, 19, index)


		grid.setColumnMinimumWidth(1, 30)
		grid.setColumnMinimumWidth(2, 30)
		grid.setColumnMinimumWidth(3, 30)
		grid.setColumnMinimumWidth(4, 30)

		groupBox.setLayout(grid)
		return groupBox

	def createParametersGroup(self):
		groupBox = QtWidgets.QGroupBox("Camera Parameters")
		groupBox.setStyleSheet(GroupBoxStyleSheet)

		grid = QtWidgets.QGridLayout()
		grid.setHorizontalSpacing(10)
		grid.setVerticalSpacing(5)

		grid.addWidget(QtWidgets.QLabel("Rotation"), 0, 0, 1, 1)
		grid.addWidget(QtWidgets.QLabel("Skew X"), 0, 1, 1, 1)
		grid.addWidget(QtWidgets.QLabel("Threshold"), 0, 2, 1, 1)
		grid.addWidget(QtWidgets.QLabel("Erosions"), 0, 3, 1, 1)
		grid.addWidget(QtWidgets.QLabel("Top Crop"), 0, 4, 1, 1)
		grid.addWidget(QtWidgets.QLabel("Left Crop"), 0, 5, 1, 1)
		grid.addWidget(QtWidgets.QLabel("WaitKey"), 2, 0)
		grid.addWidget(QtWidgets.QLabel("Webcam Index"), 2, 1)
		grid.addWidget(self.SCrotation, 1, 0, 1, 1)
		grid.addWidget(self.SCskewx, 1, 1, 1, 1)
		grid.addWidget(self.SCthreshold, 1, 2, 1, 1)
		grid.addWidget(self.SCerosion, 1, 3, 1, 1)
		grid.addWidget(self.SCcropTop, 1, 4, 1, 1)
		grid.addWidget(self.SCcropLeft, 1, 5, 1, 1)
		grid.addWidget(self.SCwaitKey, 3, 0)
		grid.addWidget(self.SCvideoCaptureIndex, 3, 1)
		grid.addWidget(self.startSCOCRButton, 3, 2)
		grid.addWidget(self.terminateSCOCRButton, 3, 3)
		grid.addWidget(self.slider_skewx, 4, 0, columnSpan=-1)

		self.SCssocrArguments.editingFinished.connect(self.widthHeightAutoFiller)
		self.SCrotation.editingFinished.connect(self.widthHeightAutoFiller)
		self.SCskewx.editingFinished.connect(self.widthHeightAutoFiller)
		self.SCerosion.editingFinished.connect(self.widthHeightAutoFiller)
		self.SCthreshold.editingFinished.connect(self.widthHeightAutoFiller)
		self.SCwaitKey.editingFinished.connect(self.widthHeightAutoFiller)
		self.SCvideoCaptureIndex.editingFinished.connect(self.widthHeightAutoFiller)
		self.SCcropLeft.editingFinished.connect(self.widthHeightAutoFiller)
		self.SCcropTop.editingFinished.connect(self.widthHeightAutoFiller)

		self.slider_skewx.valueChanged.connect(self.widthHeightAutoFiller)

		grid.setColumnStretch(0,50)
		grid.setColumnStretch(1,25)
		grid.setColumnStretch(2,25)
		groupBox.setLayout(grid)
		return groupBox

	def createDebugGroup(self):
		groupBox = QtWidgets.QGroupBox("Debug")
		groupBox.setStyleSheet(GroupBoxStyleSheet)

		grid = QtWidgets.QGridLayout()
		grid.setHorizontalSpacing(10)
		grid.setVerticalSpacing(5)

		largeFont = QFont()
		largeFont.setPointSize(22)

		self.CPUpercentage.setFont(largeFont)
		self.gameClock.setFont(largeFont)
		self.shotClock.setFont(largeFont)

		grid.addWidget(self.CPUpercentage, 0, 0)
		grid.addWidget(self.gameClock, 0, 1)
		grid.addWidget(self.shotClock, 0, 2)

		groupBox.setLayout(grid)
		return groupBox

	def createCameraPreviewGroup(self):
		groupBox = QtWidgets.QGroupBox("Preview")
		groupBox.setStyleSheet(GroupBoxStyleSheet)

		grid = QtWidgets.QGridLayout()
		grid.setHorizontalSpacing(5)
		grid.setVerticalSpacing(5)

		_img = QPixmap.fromImage(QImage(200, 113, QImage.Format_RGB888))
		_img.fill(0)
		self.previewImageRaw.setPixmap(_img)
		self.previewImageProcessed.setPixmap(_img)
		self.previewImageRaw.setAlignment(Qt.AlignCenter)
		self.previewImageProcessed.setAlignment(Qt.AlignCenter)

		grid.addWidget(self.previewImageRaw, 0, 0)
		grid.addWidget(self.previewImageProcessed, 1, 0)

		groupBox.setLayout(grid)
		return groupBox


class WebSocketsWorker(QtCore.QThread):
	updateProgress = QtCore.Signal(list)
	error = QtCore.Signal(str)
	socket_opened = QtCore.Signal(int)

	class BroadcastServerProtocol(WebSocketServerProtocol):
		def onOpen(self):
			self.factory.register(self)

		def onMessage(self, payload, isBinary):
			if not isBinary:
				msg = "{} from {}".format(payload.decode('utf8'), self.peer)
				self.factory.broadcast(msg)

		def connectionLost(self, reason):
			WebSocketServerProtocol.connectionLost(self, reason)
			self.factory.unregister(self)

	class BroadcastServerFactory(WebSocketServerFactory):
		def __init__(self, url, debug=False, debugCodePaths=False):
			WebSocketServerFactory.__init__(self, url)
			self.clients = []
			self.tickcount = 0
			#self.tick()

		def tick(self):
			self.tickcount += 1
			self.broadcast("tick %d from server" % self.tickcount)
			reactor.callLater(0.5, self.tick)

		def register(self, client):
			if client not in self.clients:
				print(("registered client {}".format(client.peer)))
				self.clients.append(client)

		def unregister(self, client):
			if client in self.clients:
				print(("unregistered client {}".format(client.peer)))
				self.clients.remove(client)

		def broadcast(self, msg):
			#print("broadcasting message '{}' ..".format(msg))
			for c in self.clients:
				c.sendMessage(msg.encode('utf8'))
				#print("message {} sent to {}".format(msg, c.peer))

		def returnClients(self):
			return
			#for c in self.clients:
				#print(c.peer)


	def __init__(self):
		QtCore.QThread.__init__(self)
		self.factory = self.BroadcastServerFactory("ws://localhost:9000", debug=False, debugCodePaths=False)

	def run(self):
		self.factory.protocol = self.BroadcastServerProtocol
		try:
			listenWS(self.factory)
		except:
			self.error.emit("Fail")
		webdir = File(_applicationPath)
		webdir.indexNames = ['index.php', 'index.html']
		web = Site(webdir)
		try:
			reactor.listenTCP(8080, web)
			self.socket_opened.emit(1)
		except: 
			self.error.emit("Fail")
		reactor.run(installSignalHandlers=0)

	def send(self, data):
		reactor.callFromThread(self.factory.broadcast, data)
		self.updateProgress.emit([self.factory.returnClients()])

class SingleDigit():
	def __init__(self, name):
		self.name = name
		self.coords = []
		self.value = ""
		self.enabled = False


class SCOCRWorker(QtCore.QThread):
	error = QtCore.Signal(int)
	recognizedDigits = QtCore.Signal(dict)
	QImageFrame = QtCore.Signal(list)
	processedFrameFlag = QtCore.Signal(int)

	def __init__(self, OCRCoordinatesList, ssocrArguments, waitKey, videoCaptureIndex, rotation, skewx, erosion, threshold, cropLeft, cropTop):
		QtCore.QThread.__init__(self)

		self.ssocrArguments = ssocrArguments
		self.waitKey = waitKey
		self.coords = OCRCoordinatesList
		self.videoCaptureIndex = videoCaptureIndex
		self.rotation = int(rotation)
		self.skewx = int(skewx)
		self.erosion = int(erosion)
		self.threshold = int(threshold)
		self.cropLeft = int(cropLeft)
		self.cropTop = int(cropTop)
		self.mouse_coordinates = [0, 0]
		self.cam = None # VideoCapture object, created in run()
		
		self.retOCRDigits  = {
			"clock_1": "",
			"clock_2": "",
			"clock_3": "",
			"clock_4": "",
			"clock_colon": "",
			"shot_clock_1": "",
			"shot_clock_2": "",
			"shot_clock_decimal": ""
		}

		self.digit1 = SingleDigit("clock_1")

	def mouse_hover_coordinates(self, event, x, y, flags, param):
		if event == cv2.EVENT_MOUSEMOVE:
			self.mouse_coordinates = [x, y]
	
	def importOCRCoordinates(self, OCRCoordinatesList):
		self.coords = OCRCoordinatesList

	def processSingleDigit(self, inputImage, coords):
		croppedImage = inputImage[int('0' + coords[2]):int('0' + coords[4]), int('0' + coords[1]):int('0' + coords[3])]
		croppedImage = autocrop(cv2.threshold(croppedImage, 127, 255, cv2.THRESH_BINARY_INV)[1], 10)

		processedDigitImage = cv2.resize(croppedImage, (50, 70), 1, 1, cv2.INTER_NEAREST)

		return processedDigitImage

	def kill(self):
		self._isRunning = False
		self.terminate()

	def run(self):
		try:
			#self.cam = VideoCapture(int(self.videoCaptureIndex))   # 0 -> index of camera

			#self.cam.set(cv2.CAP_PROP_POS_FRAMES, 100)					# run from frame 100
			self.cam = cv2.VideoCapture('test_images/test_video.mp4')	# start video

			print("Webcam native resolution: ", self.cam.get(cv2.CAP_PROP_FRAME_WIDTH), self.cam.get(cv2.CAP_PROP_FRAME_HEIGHT))
			self.cam.set(cv2.CAP_PROP_FRAME_WIDTH, 960)
			self.cam.set(cv2.CAP_PROP_FRAME_HEIGHT, 540)

			cv2.namedWindow("Bounding Boxes", cv2.WINDOW_AUTOSIZE)
			cv2.moveWindow("Bounding Boxes", 500, 0)

			#cv2.namedWindow("Test 1", cv2.WINDOW_AUTOSIZE)
			#cv2.namedWindow("Test 2", cv2.WINDOW_AUTOSIZE)
			#cv2.moveWindow("Test 1", 600, 0)
			#cv2.moveWindow("Test 2", 660, 0)

			cv2.setMouseCallback("Bounding Boxes", self.mouse_hover_coordinates)

			self._isRunning = True

			while self._isRunning:
				if self.cam is None or not self.cam.isOpened():
					break

				success, img = self.cam.read()

				if success:
					##### CROP IMAGE ######
					img_cropped = cv2.copyMakeBorder(img, 0, 0, 0, 0, cv2.BORDER_REPLICATE)
					if(self.cropLeft >= 0):
						img_cropped = img_cropped[0:img_cropped.shape[0], self.cropLeft:img_cropped.shape[1]]
					elif(self.cropLeft < 0):
						img_cropped = cv2.copyMakeBorder(img_cropped,0,0,abs(self.cropLeft),0,cv2.BORDER_CONSTANT, value=[255,255,255])
					if(self.cropTop >= 0):
						img_cropped = img_cropped[self.cropTop:img_cropped.shape[0], 0:img_cropped.shape[1]]
					elif(self.cropTop < 0):
						img_cropped = cv2.copyMakeBorder(img_cropped,abs(self.cropTop),0,0,0,cv2.BORDER_CONSTANT, value=[255,255,255])

					##### OPENCV PROCESSING ######
					img_HSV = cv2.cvtColor(img_cropped, cv2.COLOR_BGR2HSV)

					rows,cols,_ = img_HSV.shape

					# rotate image
					M = cv2.getRotationMatrix2D((cols/2,rows/2), self.rotation, 1)
					img_HSV = cv2.warpAffine(img_HSV, M, (cols,rows))	

					# shear image
					M_sh = numpy.float32([[1, math.tan(self.skewx*math.pi/180), 0],
             						[0, 1, 0],
            						[0, 0, 1]])
					img_HSV = cv2.warpPerspective(img_HSV, M_sh,(cols,rows))

					# treshold and erode
					h, s, img_v = cv2.split(img_HSV)
					ret3, img_th = cv2.threshold(img_v, self.threshold, 255, cv2.THRESH_BINARY)
					img_processed = cv2.erode(img_th, numpy.ones((2,2),numpy.uint8), iterations = self.erosion)

					##### PROCESS SINGLE DIGITS #####
					test_clock_resized_1 = self.processSingleDigit(img_processed, self.coords["clock_1"])
					test_clock_resized_2 = self.processSingleDigit(img_processed, self.coords["clock_2"])
					test_clock_resized_3 = self.processSingleDigit(img_processed, self.coords["clock_3"])
					test_clock_resized_4 = self.processSingleDigit(img_processed, self.coords["clock_4"])
					test_shot_clock_resized_1 = self.processSingleDigit(img_processed, self.coords["shot_clock_1"])
					test_shot_clock_resized_2 = self.processSingleDigit(img_processed, self.coords["shot_clock_2"])

					##### SHOW PROCESSED IMAGES #####				
					self.retOCRDigits["clock_1"] = parseSingleDigit(test_clock_resized_1, self.retOCRDigits["clock_1"])
					self.retOCRDigits["clock_2"] = parseSingleDigit(test_clock_resized_2, self.retOCRDigits["clock_2"])
					self.retOCRDigits["clock_3"] = parseSingleDigit(test_clock_resized_3, self.retOCRDigits["clock_3"])
					self.retOCRDigits["clock_4"] = parseSingleDigit(test_clock_resized_4, self.retOCRDigits["clock_4"])
					self.retOCRDigits["shot_clock_1"] = parseSingleDigit(test_shot_clock_resized_1, self.retOCRDigits["shot_clock_1"])
					self.retOCRDigits["shot_clock_2"] = parseSingleDigit(test_shot_clock_resized_2, self.retOCRDigits["shot_clock_2"])

					##### COMPARE MATRICES TO REFERENCE DIGITS #####
					shot_clock_decimal = img_processed[int('0' + self.coords["shot_clock_decimal"][2]):int('0' + self.coords["shot_clock_decimal"][4]), int('0' + self.coords["shot_clock_decimal"][1]):int('0' + self.coords["shot_clock_decimal"][3])]
					clock_colon = img_processed[int('0' + self.coords["clock_colon"][2]):int('0' + self.coords["clock_colon"][4]), int('0' + self.coords["clock_colon"][1]):int('0' + self.coords["clock_colon"][3])]
					self.retOCRDigits["clock_colon"] = str(clock_colon.mean())[:3]
					self.retOCRDigits["shot_clock_decimal"] = str(shot_clock_decimal.mean())[:3]

					##### CLOCKS FORMATTING ######
					if(clock_colon.mean() < 100): # If has colon
						self.retOCRDigits["clock"] = str(self.retOCRDigits["clock_1"]) + str(self.retOCRDigits["clock_2"]) + ":" + str(self.retOCRDigits["clock_3"]) + str(self.retOCRDigits["clock_4"]) 
					else:
						self.retOCRDigits["clock"] = str(self.retOCRDigits["clock_1"]) + str(self.retOCRDigits["clock_2"]) + "." + str(self.retOCRDigits["clock_3"])
					
					if(shot_clock_decimal.mean() > 100): # If >10s
						self.retOCRDigits["shot_clock"] = str(self.retOCRDigits["shot_clock_1"]) + str(self.retOCRDigits["shot_clock_2"])
					else:
						self.retOCRDigits["shot_clock"] = str(self.retOCRDigits["shot_clock_1"]) + '.' + str(self.retOCRDigits["shot_clock_2"])

					##### SHOW PRELIMINARY PROCESSED IMAGE WITH BOUNDING BOXES, X, Y #####
					img_disp = cv2.copyMakeBorder(img_processed, 0, 0, 0, 0, cv2.BORDER_REPLICATE)
					img_disp = cv2.cvtColor(img_disp, cv2.COLOR_GRAY2RGB)

					cv2.putText(img_disp, str(self.mouse_coordinates[0]) + ", " + str(self.mouse_coordinates[1]), (5, 15), cv2.FONT_ITALIC, 0.4, (255,255,0))

					# show bounding boxes and preliminary numbers
					for coord in self.coords:
						cv2.rectangle(img_disp, (int('0' + self.coords[coord][1]), int('0' + self.coords[coord][2])), (int('0' + self.coords[coord][3]), int('0' + self.coords[coord][4])), (0,0,255), 1)

					cv2.imshow("Bounding Boxes", img_disp)

					##### SEND QIMAGE TO DISPLAY IN PYSIDE WINDOW #####
					height, width, bPC = img.shape
					_ret_QImageRaw = QImage(img.data, width, height, bPC * width, QImage.Format_RGB888).rgbSwapped()
					height, width, bPC = img_disp.shape
					_ret_QImageProcessed = QImage(img_disp.data, width, height, bPC * width, QImage.Format_RGB888).rgbSwapped()
					self.QImageFrame.emit([_ret_QImageRaw, _ret_QImageProcessed])


					cv2.waitKey(int(self.waitKey))
					self.processedFrameFlag.emit(1)
					self.recognizedDigits.emit(self.retOCRDigits)



		except Exception as e:
			print(e)
			# self.error.emit(1)

if __name__ == '__main__':
	app = QtWidgets.QApplication(sys.argv)
	ex = MainWindow()
	sys.exit(app.exec_())
