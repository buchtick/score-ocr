# coding: utf8

from PySide6 import QtCore, QtWidgets
from PySide6.QtCore import *
from PySide6.QtGui import *

from datetime import datetime

import sys

import logging
import logging.config

import json
import os
import urllib.request, urllib.error, urllib.parse
import webbrowser

from ocrworker import ScOcrWorker, ScOcrWorkerParams
from wsworker import WebSocketsWorker

if getattr(sys, 'frozen', False):
	_applicationPath = os.path.dirname(sys.executable)
elif __file__:
	_applicationPath = os.path.dirname(__file__)

logging.config.fileConfig('logging.conf')

_settingsFilePath = os.path.join(_applicationPath, 'settings.ini')

GroupBoxStyleSheet = "QGroupBox { border: 1px solid #AAAAAA;margin-top: 12px;} QGroupBox::title {top: -5px;left: 10px;}"

class MainWindow(QtWidgets.QMainWindow):
	def __init__(self, parent=None):
		super(MainWindow, self).__init__(parent)
		logging.info("Application startup")

		######## QSettings #########
		self.qsettings = QSettings(_settingsFilePath, QSettings.IniFormat)
		self.qsettings.setFallbacksEnabled(False)

		######## ACTIONS ###########
		saveSetting = QAction('Export settings', self)
		saveSetting.triggered.connect(self.handleExportSettings)

		loadSetting = QAction('Import settings', self)
		loadSetting.triggered.connect(self.handleImportSettings)

		exitItem = QAction('Exit', self)
		exitItem.setStatusTip('Exit application...')
		exitItem.triggered.connect(self.close)
		######## END ACTIONS ###########

		menubar = self.menuBar()
		fileMenu = menubar.addMenu('&File')
		fileMenu.addAction(saveSetting)
		fileMenu.addAction(loadSetting)
		fileMenu.addAction(exitItem)


		self.main_widget = Window(self)
		self.setCentralWidget(self.main_widget)
		self.statusBar()
		self.setWindowTitle('Score OCR and TV Graphic Control')
		self.resize(1000,400)
		self.show()

	def closeEvent(self, event):
		self.main_widget.close()

	def handleExportSettings(self):
		logging.info("Triggered setting export.")
		pass

	def handleImportSettings(self):
		logging.info("Triggered setting import.")
		pass

class OcrCoordinateGui():
	def __init__(self, name, coords = None):
		self.id = id(self)
		self.name = name
		self.value = ""
		self.name_field = QtWidgets.QLineEdit(self.name)
		self.tl_coord_field_x = QtWidgets.QLineEdit("")
		self.tl_coord_field_y = QtWidgets.QLineEdit("")
		self.br_coord_field_x = QtWidgets.QLineEdit("")
		self.br_coord_field_y = QtWidgets.QLineEdit("")
		self.lbl_width = QtWidgets.QLabel("0")
		self.lbl_height = QtWidgets.QLabel("0")
		self.lbl_value = QtWidgets.QLabel("")

		self.tl_coord_field_x.textChanged.connect(self.on_update)
		self.br_coord_field_x.textChanged.connect(self.on_update)
		self.tl_coord_field_y.textChanged.connect(self.on_update)
		self.br_coord_field_y.textChanged.connect(self.on_update)

		self.name_field.textChanged.connect(self.on_name_update)

		self.lbl_width.setAlignment(Qt.AlignCenter)
		self.lbl_height.setAlignment(Qt.AlignCenter)
		self.lbl_value.setAlignment(Qt.AlignCenter)
		self.tl_coord_field_x.setValidator(QIntValidator()) # Require integer pixel input
		self.tl_coord_field_y.setValidator(QIntValidator())
		self.br_coord_field_x.setValidator(QIntValidator())
		self.br_coord_field_y.setValidator(QIntValidator())
		self.tl_coord_field_x.setMaxLength(3) # Set 3 digit maximum for pixel coordinates
		self.tl_coord_field_y.setMaxLength(3)
		self.br_coord_field_x.setMaxLength(3)
		self.br_coord_field_y.setMaxLength(3)


		if coords is not None:
			self.set_coords(coords)

	def __del__(self):
		self.name_field.deleteLater()
		self.tl_coord_field_x.deleteLater()
		self.tl_coord_field_y.deleteLater()
		self.br_coord_field_x.deleteLater()
		self.br_coord_field_y.deleteLater()
		self.lbl_width.deleteLater()
		self.lbl_height.deleteLater()
		self.lbl_value.deleteLater()
		print("Destructor called.")

	def get_text_coords(self):
		return [self.tl_coord_field_x.text(), self.tl_coord_field_y.text(), self.br_coord_field_x.text(), self.br_coord_field_y.text()]
	
	def get_coords(self):
		return [int('0' + self.tl_coord_field_x.text()), int('0' + self.tl_coord_field_y.text()), int(self.br_coord_field_x.text()), int(self.br_coord_field_y.text())]
	
	def set_coords(self, coords):
		self.tl_coord_field_x.setText(coords[0])
		self.tl_coord_field_y.setText(coords[1])
		self.br_coord_field_x.setText(coords[2])
		self.br_coord_field_y.setText(coords[3])

	def on_update(self, value):
		self.lbl_height.setText(str(int('0' + self.br_coord_field_y.text()) - int('0' +  self.tl_coord_field_y.text())))
		self.lbl_width.setText(str(int('0' + self.br_coord_field_x.text()) - int('0' +  self.tl_coord_field_x.text())))

	def on_name_update(self, value):
		self.name = self.name_field.text()

class Window(QtWidgets.QWidget):
	def __init__(self, parent):
		super(Window, self).__init__(parent)
		
		self.qsettings = QSettings(_settingsFilePath, QSettings.IniFormat)
		self.qsettings.setFallbacksEnabled(False)
		
		#parameters for OCR Worker - gets populated on clicking Start OCR
		self.ocr_worker = None
		self.ocr_worker_params = None
		self.ws_worker = None

		#digit coordinates list
		self.g_ocr_coords = []

		self.init_ocr_coordinates_list()

		self.previewZoomLevel = 0

		#construct the GUI
		grid = QtWidgets.QGridLayout()
		self.g_ocr_group = self.ui_create_ocr_group()
		grid.addWidget(self.g_ocr_group, 0, 1, 4, 1) # MUST BE HERE, initializes all QObject lists
		grid.addWidget(self.ui_create_camera_preview_group(), 0, 0, 4, 1) # MUST BE HERE, initializes all QObject lists
		grid.addWidget(self.ui_create_parameters_group(), 4, 0, 2, 1) # MUST BE HERE, initializes all QObject lists
		grid.addWidget(self.ui_create_debug_group(), 4, 1, 2, 1) # MUST BE HERE, initializes all QObject lists

		grid.setColumnStretch(0,100)
		grid.setColumnStretch(1,50)

		grid.setHorizontalSpacing(10)
		grid.setVerticalSpacing(10)

		self.setLayout(grid)

		#initialize worker threads
		self.init_ocr_worker()
		self.init_ws_worker()

	def handle_preview_video_zoom(self,event):
		if event.angleDelta().y() < 0:
			self.previewZoomLevel -= 1
		else:
			self.previewZoomLevel += 1	

	def handle_preview_video_click(self, event):
		print("Clicked on. X: ", event.position().x(), ", Y:", event.position().y())

	def handle_processed_video_click(self, event):
		print("Clicked on. X: ", event.position().x(), ", Y:", event.position().y())

	def closeEvent(self, event):
		if self.ocr_worker._isRunning:
			self.terminate_ocr_worker()

	def sendCommandToBrowser(self):

		current_time = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

		response = {}
		response["timestamp"] = current_time
		for key, param in enumerate(self.g_ocr_coords):
			response[param.name] = param.value

		self.ws_worker.send(json.dumps(response))

	def init_ws_worker(self):
		self.ws_worker = WebSocketsWorker(serverAddress=self.SCwebsocketAddress.text())
		self.ws_worker.error.connect(self.close)
		self.ws_worker.start()# Call to start WebSockets server

	def init_ocr_worker(self):
		self.ocr_worker_params = ScOcrWorkerParams(
				waitKey=self.SCwaitKey.text(),
				videoCaptureIndex=self.SCvideoCaptureIndex.text(),
				rotation=self.SCrotation.text(),
				skewx=self.SCskewx.text(),
				skewy=self.SCskewy.text(),
				erosion=self.SCerosion.text(),
				dilate=self.SCdilate.text(),
				threshold=self.SCthreshold.text(),
				cropLeft=self.SCcropLeft.text(),
				cropTop=self.SCcropTop.text(),
				autocrop_enabled=False,
				autocrop_coords=[0,0,0,0]
				)

		self.ocr_worker = ScOcrWorker(self.g_ocr_coords, self.ocr_worker_params)
		self.ocr_worker.error.connect(self.close)
		self.ocr_worker.allDigitGroups.connect(self.handler_ocr_result_groups)
		self.ocr_worker.QImageFrame.connect(self.handler_ocr_preview_image)

	def start_ocr_worker(self):
		if self.ocr_worker is not None:
			self.ocr_worker.run()

	def pause_ocr_worker(self):
		if self.ocr_worker is not None:
			self.ocr_worker.pause()

	def terminate_ocr_worker(self):
		if self.ocr_worker is not None:
			self.ocr_worker.kill()

	@Slot(list)
	def handler_ocr_preview_image(self, QImageFrame):
		_pixmapRaw = QPixmap.fromImage(QImageFrame[0])
		_pixmapProcessed = QPixmap.fromImage(QImageFrame[1])
		self.previewImageRaw.setPixmap(_pixmapRaw.scaled(300, 300, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
		self.previewImageProcessed.setPixmap(_pixmapProcessed.scaled(self.previewImageProcessed.width(), self.previewImageProcessed.height(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))

	@Slot(object)
	def handler_ocr_result_groups(self, digit_groups):
		for i, digitgrp in enumerate(digit_groups):
			self.g_ocr_coords[i].lbl_value.setText(str(digitgrp.value))
			self.g_ocr_coords[i].value = digitgrp.value

		self.sendCommandToBrowser()

	def get_ocr_coodinates_list(self):
		response = {}
		for key, param in enumerate(self.g_ocr_coords):
			response[param.id] = [param.name, param.get_text_coords()]

		return response

	def init_ocr_coordinates_list(self):
		_loaded_coords = self.qsettings.value("newOCRcoordinates")

		if _loaded_coords:
			self.g_ocr_coords.clear()
			for key,coord in _loaded_coords.items():
				self.g_ocr_coords.append(OcrCoordinateGui(coord[0],coord[1]))
	
	def handler_digit_add(self):
		self.g_ocr_coords.append(OcrCoordinateGui("new_digit"))
		self.ui_update_ocr_group()
		self.update_state()

	def handler_digit_remove(self):
		self.g_ocr_coords.pop() # handle pop from empty list
		self.ui_update_ocr_group()
		self.update_state()

	def update_sliders(self):
		self.skewXSlider.setValue(int(self.SCskewx.text()))
		self.skewYSlider.setValue(int(self.SCskewy.text()))
		self.threshSlider.setValue(int(self.SCthreshold.text()))
		self.erosionSlider.setValue(int(self.SCerosion.text()))
		self.dilateSlider.setValue(int(self.SCdilate.text()))
		self.update_state()

	def update_state(self):

		self.SCskewx.setText(str(self.skewXSlider.value()))
		self.SCskewy.setText(str(self.skewYSlider.value()))
		self.SCthreshold.setText(str(self.threshSlider.value()))
		self.SCerosion.setText(str(self.erosionSlider.value()))
		self.SCdilate.setText(str(self.dilateSlider.value()))

 		# saves coords list without graphics objects
		self.qsettings.setValue("newOCRcoordinates", self.get_ocr_coodinates_list())

		# save other parameters
		self.qsettings.setValue("SCrotation", self.SCrotation.text())
		self.qsettings.setValue("SCskewx", self.SCskewx.text())
		self.qsettings.setValue("SCskewy", self.SCskewy.text())
		self.qsettings.setValue("SCThreshold", self.SCthreshold.text())
		self.qsettings.setValue("SCerosion", self.SCerosion.text())
		self.qsettings.setValue("SCdilate", self.SCdilate.text())
		self.qsettings.setValue("TCrop", self.SCcropTop.text())
		self.qsettings.setValue("LCrop", self.SCcropLeft.text())
		self.qsettings.setValue("SCwaitKey", self.SCwaitKey.text())
		self.qsettings.setValue("SCvideoCaptureIndex", self.SCvideoCaptureIndex.text())
		self.qsettings.setValue("SCwebsocketAddress", self.SCwebsocketAddress.text())
		
		try:
			self.ocr_worker_params = ScOcrWorkerParams(
				waitKey=self.SCwaitKey.text(),
				videoCaptureIndex=self.SCvideoCaptureIndex.text(),
				rotation=self.SCrotation.text(),
				skewx=self.SCskewx.text(),
				skewy=self.SCskewy.text(),
				erosion=self.SCerosion.text(),
				dilate=self.SCdilate.text(),
				threshold=self.SCthreshold.text(),
				cropLeft=self.SCcropLeft.text(),
				cropTop=self.SCcropTop.text(),
				autocrop_enabled=False,
				autocrop_coords=[0,0,0,0]
				)
			self.ocr_worker.update_params(self.ocr_worker_params)
			self.ocr_worker.update_ocr_coordinates(self.g_ocr_coords)
		except Exception as e:
			print("Unable to update OCR worker params. OCR probably not running.")
			pass

	def ui_update_ocr_group(self):

		def add_update_widget(grid, widget, row, col):
			if grid.itemAtPosition(row, col) is None:
				grid.addWidget(widget, row, col)
			else:
				grid.replaceWidget(grid.itemAtPosition(row, col).widget(),widget)

		self.g_ocr_group.setStyleSheet(GroupBoxStyleSheet)

		grid = self.g_ocr_group.layout()

		for index, param in enumerate(self.g_ocr_coords):
			row_index = index + 2

			param.name_field.editingFinished.connect(self.update_state)
			param.tl_coord_field_x.editingFinished.connect(self.update_state) # On change in X or Y, update width + height
			param.tl_coord_field_y.editingFinished.connect(self.update_state)
			param.br_coord_field_x.editingFinished.connect(self.update_state)
			param.br_coord_field_y.editingFinished.connect(self.update_state)

			add_update_widget(grid, param.name_field, row_index, 0)
			add_update_widget(grid, param.tl_coord_field_x, row_index, 1)
			add_update_widget(grid, param.tl_coord_field_y, row_index, 2)
			add_update_widget(grid, param.br_coord_field_x, row_index, 3)
			add_update_widget(grid, param.br_coord_field_y, row_index, 4)
			add_update_widget(grid, param.lbl_width, row_index, 5)
			add_update_widget(grid, param.lbl_height, row_index, 6)
			add_update_widget(grid, param.lbl_value, row_index, 7)
		
		grid.setRowStretch(grid.rowCount(), 1)
		grid.setColumnMinimumWidth(1, 30)
		grid.setColumnMinimumWidth(2, 30)
		grid.setColumnMinimumWidth(3, 30)
		grid.setColumnMinimumWidth(4, 30)

	def ui_create_ocr_group(self):
		groupBox = QtWidgets.QGroupBox("Bounding Boxes")
		groupBox.setStyleSheet(GroupBoxStyleSheet)

		grid = QtWidgets.QGridLayout()
		grid.setHorizontalSpacing(10)
		grid.setVerticalSpacing(2)

		dividerLine = QtWidgets.QFrame()
		dividerLine.setFrameShape(QtWidgets.QFrame.HLine)
		dividerLine.setFrameShadow(QtWidgets.QFrame.Sunken)

		self.add_ocr_digit_button = QtWidgets.QPushButton("Add digit")
		self.add_ocr_digit_button.clicked.connect(self.handler_digit_add)
		self.remove_ocr_digit_button = QtWidgets.QPushButton("Remove digit")
		self.remove_ocr_digit_button.clicked.connect(self.handler_digit_remove)

		grid.addWidget(self.add_ocr_digit_button, 0, 5)
		grid.addWidget(self.remove_ocr_digit_button, 0 , 6)

		_tlLabel = QtWidgets.QLabel("Top-Left")
		_brLabel = QtWidgets.QLabel("Bottom-Right")
		_tlLabel.setAlignment(Qt.AlignHCenter)
		_brLabel.setAlignment(Qt.AlignHCenter)
		grid.addWidget(_tlLabel, 0, 1, 1, 2)
		grid.addWidget(_brLabel, 0, 3, 1, 2)

		grid.addWidget(QtWidgets.QLabel(""), 1, 0)
		grid.addWidget(QtWidgets.QLabel("X"), 1, 1, alignment=Qt.AlignHCenter)
		grid.addWidget(QtWidgets.QLabel("Y"), 1, 2, alignment=Qt.AlignHCenter)
		grid.addWidget(QtWidgets.QLabel("X"), 1, 3, alignment=Qt.AlignHCenter)
		grid.addWidget(QtWidgets.QLabel("Y"), 1, 4, alignment=Qt.AlignHCenter)
		grid.addWidget(QtWidgets.QLabel("Width"), 1, 5, alignment=Qt.AlignHCenter)
		grid.addWidget(QtWidgets.QLabel("Height"), 1, 6, alignment=Qt.AlignHCenter)
		grid.addWidget(QtWidgets.QLabel("OCR"), 1, 7, alignment=Qt.AlignHCenter)

		for index, param in enumerate(self.g_ocr_coords):
			row_index = index + 2

			param.name_field.editingFinished.connect(self.update_state)
			param.tl_coord_field_x.editingFinished.connect(self.update_state) # On change in X or Y, update width + height
			param.tl_coord_field_y.editingFinished.connect(self.update_state)
			param.br_coord_field_x.editingFinished.connect(self.update_state)
			param.br_coord_field_y.editingFinished.connect(self.update_state)

			grid.addWidget(param.name_field, row_index, 0)
			grid.addWidget(param.tl_coord_field_x, row_index, 1)
			grid.addWidget(param.tl_coord_field_y, row_index, 2)
			grid.addWidget(param.br_coord_field_x, row_index, 3)
			grid.addWidget(param.br_coord_field_y, row_index, 4)
			grid.addWidget(param.lbl_width, row_index, 5)
			grid.addWidget(param.lbl_height, row_index, 6)
			grid.addWidget(param.lbl_value, row_index, 7)

		grid.setRowStretch(grid.rowCount(), 1)
		grid.setColumnMinimumWidth(1, 30)
		grid.setColumnMinimumWidth(2, 30)
		grid.setColumnMinimumWidth(3, 30)
		grid.setColumnMinimumWidth(4, 30)

		groupBox.setLayout(grid)
		return groupBox

	def ui_create_parameters_group(self):
		groupBox = QtWidgets.QGroupBox("Camera Parameters")
		groupBox.setStyleSheet(GroupBoxStyleSheet)

		#define widgets
		self.SCrotation = QtWidgets.QLineEdit(self.qsettings.value("SCrotation", "0"))
		self.SCskewx = QtWidgets.QLineEdit(self.qsettings.value("SCskewx", "5"))
		self.SCskewy = QtWidgets.QLineEdit(self.qsettings.value("SCskewy", "5"))
		self.SCerosion = QtWidgets.QLineEdit(self.qsettings.value("SCerosion", "2"))
		self.SCdilate = QtWidgets.QLineEdit(self.qsettings.value("SCdilate", "0"))
		self.SCthreshold = QtWidgets.QLineEdit(self.qsettings.value("SCthreshold", "127"))
		self.SCcropLeft = QtWidgets.QLineEdit(self.qsettings.value("LCrop", "0"))
		self.SCcropTop = QtWidgets.QLineEdit(self.qsettings.value("TCrop", "0"))
		self.SCvideoCaptureIndex = QtWidgets.QLineEdit(self.qsettings.value("SCvideoCaptureIndex", '0'))
		self.SCwebsocketAddress = QtWidgets.QLineEdit(self.qsettings.value("SCwebsocketAddress", 'ws://localhost:9000'))
		self.SCwaitKey = QtWidgets.QLineEdit(self.qsettings.value("SCwaitKey", '300'))

		self.skewXSlider = QtWidgets.QSlider(Qt.Orientation.Horizontal)
		self.skewXSlider.setMinimum(-45)
		self.skewXSlider.setMaximum(45)
		self.skewXSlider.setValue(int(self.qsettings.value("SCskewx", "0")))

		self.skewYSlider = QtWidgets.QSlider(Qt.Orientation.Horizontal)
		self.skewYSlider.setMinimum(-45)
		self.skewYSlider.setMaximum(45)
		self.skewYSlider.setValue(int(self.qsettings.value("SCskewy", "0")))

		self.threshSlider = QtWidgets.QSlider(Qt.Orientation.Horizontal)		
		self.threshSlider.setMinimum(0)
		self.threshSlider.setMaximum(255)
		self.threshSlider.setValue(int(self.qsettings.value("SCthreshold", "0")))

		self.erosionSlider = QtWidgets.QSlider(Qt.Orientation.Horizontal)		
		self.erosionSlider.setMinimum(0)
		self.erosionSlider.setMaximum(25)
		self.erosionSlider.setValue(int(self.qsettings.value("SCerosion", "0")))

		self.dilateSlider = QtWidgets.QSlider(Qt.Orientation.Horizontal)		
		self.dilateSlider.setMinimum(0)
		self.dilateSlider.setMaximum(25)
		self.dilateSlider.setValue(int(self.qsettings.value("SCdilate", "0")))

		self.chkAutocrop = QtWidgets.QCheckBox()
		self.chkAutocrop.setCheckState(Qt.CheckState.Unchecked)

		grid = QtWidgets.QGridLayout()
		grid.setHorizontalSpacing(10)
		grid.setVerticalSpacing(5)
		grid.setAlignment(Qt.AlignmentFlag.AlignTop)

		#compose the grid
		layoutRow = 0
		grid.addWidget(QtWidgets.QLabel("Autocrop enabled"), layoutRow, 0, 1, 1)

		layoutRow += 1
		grid.addWidget(self.chkAutocrop, layoutRow, 0)

		layoutRow += 1
		grid.addWidget(QtWidgets.QLabel("Rotation"), layoutRow, 0, 1, 1)
		grid.addWidget(QtWidgets.QLabel("Skew X"), layoutRow, 1, 1, 1)
		grid.addWidget(QtWidgets.QLabel("Skew Y"), layoutRow, 2, 1, 1)
		grid.addWidget(QtWidgets.QLabel("Threshold"), layoutRow, 3, 1, 1)
		grid.addWidget(QtWidgets.QLabel("Erosion"), layoutRow, 4, 1, 1)
		grid.addWidget(QtWidgets.QLabel("Dilate"), layoutRow, 5, 1, 1)

		layoutRow += 1
		grid.addWidget(self.SCrotation, layoutRow, 0, 1, 1)
		grid.addWidget(self.SCskewx, layoutRow, 1, 1, 1)
		grid.addWidget(self.SCskewy, layoutRow, 2, 1, 1)
		grid.addWidget(self.SCthreshold, layoutRow, 3, 1, 1)
		grid.addWidget(self.SCerosion, layoutRow, 4, 1, 1)
		grid.addWidget(self.SCdilate, layoutRow, 5, 1, 1)

		layoutRow += 1
		grid.addWidget(QtWidgets.QLabel("WaitKey"), layoutRow, 0)
		grid.addWidget(self.skewXSlider, layoutRow, 1)
		grid.addWidget(self.skewYSlider, layoutRow, 2)
		grid.addWidget(self.threshSlider, layoutRow, 3)
		grid.addWidget(self.erosionSlider, layoutRow, 4)
		grid.addWidget(self.dilateSlider, layoutRow, 5)

		layoutRow += 1
		grid.addWidget(self.SCwaitKey, layoutRow, 0)
		grid.addWidget(QtWidgets.QLabel("Top Crop"), layoutRow, 4, 1, 1)
		grid.addWidget(QtWidgets.QLabel("Left Crop"), layoutRow, 5, 1, 1)

		layoutRow += 1
		grid.addWidget(self.SCcropTop, layoutRow, 4)
		grid.addWidget(self.SCcropLeft, layoutRow, 5)

		layoutRow += 1
		grid.addWidget(QtWidgets.QLabel("Source"), layoutRow, 0, 1, 1)
		grid.addWidget(self.SCvideoCaptureIndex, layoutRow, 1, 1, 5)

		layoutRow += 1
		grid.addWidget(QtWidgets.QLabel("WS address"), layoutRow, 0, 1, 1)
		grid.addWidget(self.SCwebsocketAddress, layoutRow, 1, 1, 5)

		self.SCrotation.editingFinished.connect(self.update_state)

		self.SCskewx.editingFinished.connect(self.update_sliders)
		self.SCskewy.editingFinished.connect(self.update_sliders)
		self.SCerosion.editingFinished.connect(self.update_sliders)
		self.SCdilate.editingFinished.connect(self.update_sliders)
		self.SCthreshold.editingFinished.connect(self.update_sliders)

		self.SCwaitKey.editingFinished.connect(self.update_state)
		self.SCvideoCaptureIndex.editingFinished.connect(self.update_state)
		self.SCwebsocketAddress.editingFinished.connect(self.update_state)
		self.SCcropLeft.editingFinished.connect(self.update_state)
		self.SCcropTop.editingFinished.connect(self.update_state)

		self.skewXSlider.valueChanged.connect(self.update_state)
		self.skewYSlider.valueChanged.connect(self.update_state)
		self.threshSlider.valueChanged.connect(self.update_state)
		self.erosionSlider.valueChanged.connect(self.update_state)
		self.dilateSlider.valueChanged.connect(self.update_state)

		grid.setColumnStretch(0,50)
		grid.setColumnStretch(1,25)
		grid.setColumnStretch(2,25)
		groupBox.setLayout(grid)
		return groupBox

	def ui_create_debug_group(self):
		groupBox = QtWidgets.QGroupBox("Debug")
		groupBox.setStyleSheet(GroupBoxStyleSheet)

		#define widgets
		self.startSCOCRButton = QtWidgets.QPushButton("Start OCR")
		self.pauseSCOCRButton = QtWidgets.QPushButton("Pause OCR")
		self.terminateSCOCRButton = QtWidgets.QPushButton("Stop OCR")

		self.previewImageRaw = QtWidgets.QLabel("")
		self.previewImageRaw.mousePressEvent = self.handle_preview_video_click
		self.previewImageRaw.mouseReleaseEvent = self.handle_preview_video_click

		self.startSCOCRButton.clicked.connect(self.start_ocr_worker)
		self.pauseSCOCRButton.clicked.connect(self.pause_ocr_worker)
		self.terminateSCOCRButton.clicked.connect(self.terminate_ocr_worker)

		grid = QtWidgets.QGridLayout()
		grid.setHorizontalSpacing(10)
		grid.setVerticalSpacing(5)

		_img = QPixmap.fromImage(QImage(200, 113, QImage.Format_RGB888))
		_img.fill(0)
		self.previewImageRaw.setPixmap(_img)
		self.previewImageRaw.setAlignment(Qt.AlignCenter)

		grid.addWidget(self.previewImageRaw, 0, 0, 1, 3)
		grid.addWidget(self.startSCOCRButton, 1, 0)
		grid.addWidget(self.pauseSCOCRButton, 1, 1)
		grid.addWidget(self.terminateSCOCRButton, 1, 2)

		groupBox.setLayout(grid)
		return groupBox

	def ui_create_camera_preview_group(self):
		groupBox = QtWidgets.QGroupBox("Preview")
		groupBox.setStyleSheet(GroupBoxStyleSheet)

		#define widgets
		self.previewImageProcessed = QtWidgets.QLabel("")
		self.previewImageProcessed.wheelEvent = self.handle_preview_video_zoom
		self.previewImageProcessed.mousePressEvent = self.handle_processed_video_click
		self.previewImageProcessed.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Ignored)

		grid = QtWidgets.QGridLayout()
		grid.setHorizontalSpacing(5)
		grid.setVerticalSpacing(5)

		_img = QPixmap.fromImage(QImage(200, 113, QImage.Format_RGB888))
		_img.fill(0)
		self.previewImageProcessed.setPixmap(_img)
		self.previewImageProcessed.setAlignment(Qt.AlignCenter)

		grid.addWidget(self.previewImageProcessed, 1, 0)

		groupBox.setLayout(grid)
		return groupBox

if __name__ == '__main__':
	app = QtWidgets.QApplication(sys.argv)
	ex = MainWindow()
	sys.exit(app.exec())
