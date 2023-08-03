# coding: utf8

from PySide2 import QtCore, QtWidgets
from PySide2.QtCore import *
from PySide2.QtGui import *

from datetime import datetime

import sys

import json
import os
import urllib.request, urllib.error, urllib.parse
import webbrowser

import psutil # CPU usage

from ocrworker import ScOcrWorker, ScOcrWorkerParams
from wsworker import WebSocketsWorker

if getattr(sys, 'frozen', False):
	_applicationPath = os.path.dirname(sys.executable)
elif __file__:
	_applicationPath = os.path.dirname(__file__)

_settingsFilePath = os.path.join(_applicationPath, 'settings.ini')

GroupBoxStyleSheet = "QGroupBox { border: 1px solid #AAAAAA;margin-top: 12px;} QGroupBox::title {top: -5px;left: 10px;}"

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

	def closeEvent(self, event):
		self.main_widget.close()

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
		grid = QtWidgets.QGridLayout()
		self.qsettings = QSettings(_settingsFilePath, QSettings.IniFormat)
		self.qsettings.setFallbacksEnabled(False)

		self.updateScoreboard = QtWidgets.QPushButton("Update")
		self.updateScoreboard.clicked.connect(self.sendCommandToBrowser)
		
		self.ocr_worker = None
		#parameters for OCR Worker - gets populated on clicking Start OCR
		self.ocr_worker_params = []
		self.g_ocr_coords = []

		self.init_ocr_coordinates_list_new()

		self.SCssocrArguments = QtWidgets.QLineEdit(self.qsettings.value("SCssocrArguments", "crop 0 0 450 200 mirror horiz shear 10 mirror horiz gray_stretch 100 254 invert remove_isolated -T "))
		self.SCrotation = QtWidgets.QLineEdit(self.qsettings.value("SCrotation", "0"))
		self.SCskewx = QtWidgets.QLineEdit(self.qsettings.value("SCskewx", "5"))
		self.SCerosion = QtWidgets.QLineEdit(self.qsettings.value("SCerosion", "2"))
		self.SCthreshold = QtWidgets.QLineEdit(self.qsettings.value("SCthreshold", "127"))
		self.SCcropLeft = QtWidgets.QLineEdit(self.qsettings.value("LCrop", "0"))
		self.SCcropTop = QtWidgets.QLineEdit(self.qsettings.value("TCrop", "0"))
		self.SCvideoCaptureIndex = QtWidgets.QLineEdit(self.qsettings.value("SCvideoCaptureIndex", '0'))
		self.SCwebsocketAddress = QtWidgets.QLineEdit(self.qsettings.value("SCwebsocketAddress", 'ws://localhost:9000'))
		self.SCwaitKey = QtWidgets.QLineEdit(self.qsettings.value("SCwaitKey", '300'))
		self.startSCOCRButton = QtWidgets.QPushButton("Start OCR")
		self.startSCOCRButton.clicked.connect(self.init_SCOCRWorker)
		self.pauseSCOCRButton = QtWidgets.QPushButton("Pause OCR")
		self.pauseSCOCRButton.clicked.connect(self.pause_ocr_worker)
		self.terminateSCOCRButton = QtWidgets.QPushButton("Stop OCR")
		self.terminateSCOCRButton.clicked.connect(self.terminate_SCOCRWorker)

		self.slider_skewx = QtWidgets.QSlider()
		self.slider_skewx.setOrientation(Qt.Horizontal)
		self.slider_skewx.setMinimum(-45)
		self.slider_skewx.setMaximum(45)
		self.slider_skewx.setValue(int(self.qsettings.value("SCskewx", "-6")))

		self.previewImageRaw = QtWidgets.QLabel("")
		self.previewImageProcessed = QtWidgets.QLabel("")

		self.CPUpercentage = QtWidgets.QLabel("0 %")
		self.gameClock = QtWidgets.QLabel("00:00")
		self.shotClock = QtWidgets.QLabel("00")

		#grid.addWidget(self.ui_create_ocr_tree_group(), 0, 3, 6, 1) # MUST BE HERE, initializes all QObject lists
		self.g_ocr_group = self.ui_create_ocr_group()
		grid.addWidget(self.g_ocr_group, 0, 1, 4, 1) # MUST BE HERE, initializes all QObject lists
		grid.addWidget(self.ui_create_camera_preview_group(), 0, 0, 4, 1) # MUST BE HERE, initializes all QObject lists
		grid.addWidget(self.ui_create_parameters_group(), 4, 0, 2, 1) # MUST BE HERE, initializes all QObject lists
		grid.addWidget(self.ui_create_debug_group(), 4, 1, 1, 1) # MUST BE HERE, initializes all QObject lists
		grid.addWidget(self.updateScoreboard, 5, 1, 1, 1) # MUST BE HERE, initializes all QObject lists
		
		self.init_WebSocketsWorker()

		grid.setColumnStretch(0,100)
		grid.setColumnStretch(1,50)
		grid.setColumnStretch(2,100)

		grid.setHorizontalSpacing(10)
		grid.setVerticalSpacing(10)

		self.setLayout(grid)

	def closeEvent(self, event):
		self.terminate_SCOCRWorker()

	def sendCommandToBrowser(self):

		current_time = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

		response = {}
		response["timestamp"] = current_time
		for key, param in enumerate(self.g_ocr_coords):
			response[param.name] = param.value

		self.webSocketsWorker.send(json.dumps(response))

	def init_WebSocketsWorker(self):
		self.webSocketsWorker = WebSocketsWorker(serverAddress=self.SCwebsocketAddress.text())
		self.webSocketsWorker.error.connect(self.close)
		self.webSocketsWorker.start()# Call to start WebSockets server

	def init_SCOCRWorker(self):
		self.ocr_worker_params = ScOcrWorkerParams(
				ssocrArguments=self.SCssocrArguments.text(),
				waitKey=self.SCwaitKey.text(),
				videoCaptureIndex=self.SCvideoCaptureIndex.text(),
				rotation=self.SCrotation.text(),
				skewx=self.SCskewx.text(),
				erosion=self.SCerosion.text(),
				threshold=self.SCthreshold.text(),
				cropLeft=self.SCcropLeft.text(),
				cropTop=self.SCcropTop.text()
				)

		self.ocr_worker = ScOcrWorker(self.g_ocr_coords, self.ocr_worker_params)
		self.ocr_worker.error.connect(self.close)
		self.ocr_worker.alldigits.connect(self.ocr_result_handler_new)
		self.ocr_worker.processedFrameFlag.connect(lambda: self.CPUpercentage.setText('CPU: ' + str(psutil.cpu_percent()) + "%"))
		self.ocr_worker.QImageFrame.connect(self.ocr_preview_image_handler)
		self.ocr_worker.run() # Call to start OCR openCV thread

	def pause_ocr_worker(self):
		self.ocr_worker.pause()

	def terminate_SCOCRWorker(self):
		if self.ocr_worker is not None:
			self.ocr_worker.quit()
			self.ocr_worker.kill()
			del(self.ocr_worker)

	def ocr_preview_image_handler(self, QImageFrame):
		_pixmapRaw = QPixmap.fromImage(QImageFrame[0])
		_pixmapProcessed = QPixmap.fromImage(QImageFrame[1])
		self.previewImageRaw.setPixmap(_pixmapRaw.scaled(600, 600, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
		self.previewImageProcessed.setPixmap(_pixmapProcessed.scaled(600, 600, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))

	def ocr_result_handler_new(self, digits):
		for digit in digits:
			self.g_ocr_coords[digit].lbl_value.setText(str(digits[digit].value))
			self.g_ocr_coords[digit].value = digits[digit].value
		
		self.sendCommandToBrowser()

	def get_ocr_coodinates_list(self):
		response = {}
		for key, param in enumerate(self.g_ocr_coords):
			response[param.id] = [param.name, param.get_text_coords()]

		return response

	def init_ocr_coordinates_list_new(self):
		_loaded_coords = self.qsettings.value("newOCRcoordinates")

		if _loaded_coords:
			self.g_ocr_coords.clear()
			for key,coord in _loaded_coords.items():
				self.g_ocr_coords.append(OcrCoordinateGui(coord[0],coord[1]))
	
	def add_digit_handler(self):
		self.g_ocr_coords.append(OcrCoordinateGui("new_digit"))
		self.ui_update_ocr_group()
		self.update_state()

	def remove_digit_handler(self):
		self.g_ocr_coords.pop() # handle pop from empty list
		self.ui_update_ocr_group()
		self.update_state()

	def update_state(self):
 		# saves coords list without graphics objects
		self.qsettings.setValue("newOCRcoordinates", self.get_ocr_coodinates_list())

		# save other parameters
		self.qsettings.setValue("SCssocrArguments", self.SCssocrArguments.text())
		self.qsettings.setValue("SCrotation", self.SCrotation.text())
		self.qsettings.setValue("SCskewx", self.SCskewx.text())
		self.qsettings.setValue("SCThreshold", self.SCthreshold.text())
		self.qsettings.setValue("SCerosion", self.SCerosion.text())
		self.qsettings.setValue("TCrop", self.SCcropTop.text())
		self.qsettings.setValue("LCrop", self.SCcropLeft.text())
		self.qsettings.setValue("SCwaitKey", self.SCwaitKey.text())
		self.qsettings.setValue("SCvideoCaptureIndex", self.SCvideoCaptureIndex.text())
		self.qsettings.setValue("SCwebsocketAddress", self.SCwebsocketAddress.text())
		self.qsettings.setValue("SCskewx", self.slider_skewx.value())
		
		try:
			self.ocr_worker_params = ScOcrWorkerParams(
				ssocrArguments=self.SCssocrArguments.text(),
				waitKey=self.SCwaitKey.text(),
				videoCaptureIndex=self.SCvideoCaptureIndex.text(),
				rotation=self.SCrotation.text(),
				skewx=self.SCskewx.text(),
				erosion=self.SCerosion.text(),
				threshold=self.SCthreshold.text(),
				cropLeft=self.SCcropLeft.text(),
				cropTop=self.SCcropTop.text()
				)
			self.ocr_worker.update_params(self.ocr_worker_params)
			self.ocr_worker.update_ocr_coordinates(self.g_ocr_coords)
		except:
			pass
	
	def ui_create_ocr_tree_group(self):
		groupBox = QtWidgets.QGroupBox("Tree Bounding Boxes")
		groupBox.setStyleSheet(GroupBoxStyleSheet)

		tree =  QtWidgets.QTreeWidget()

		tree.setHeaderHidden(False)
		tree.setColumnCount(3)
		tree.setHeaderLabels(["name", "x coords", "y coords"])

		testitem = QtWidgets.QTreeWidgetItem(None, ["testitem", "aaaa", "bbbb"])
		testitem2 = QtWidgets.QTreeWidgetItem(None, ["testitem2", "cccc", "dddd"])

		items = []
		for i in range(10):
			items.append(QtWidgets.QTreeWidgetItem(None, ["test"]))
		tree.insertTopLevelItems(0, items)

		items[2].addChild(testitem)

		items[5].addChild(testitem2)

		layout = QtWidgets.QVBoxLayout()

		layout.addWidget(tree)

		groupBox.setLayout(layout)

		return groupBox

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
		self.add_ocr_digit_button.clicked.connect(self.add_digit_handler)
		self.remove_ocr_digit_button = QtWidgets.QPushButton("Remove digit")
		self.remove_ocr_digit_button.clicked.connect(self.remove_digit_handler)

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
		grid.addWidget(self.SCrotation, 1, 0, 1, 1)
		grid.addWidget(self.SCskewx, 1, 1, 1, 1)
		grid.addWidget(self.SCthreshold, 1, 2, 1, 1)
		grid.addWidget(self.SCerosion, 1, 3, 1, 1)
		grid.addWidget(self.SCcropTop, 1, 4, 1, 1)
		grid.addWidget(self.SCcropLeft, 1, 5, 1, 1)
		grid.addWidget(self.SCwaitKey, 3, 0)
		grid.addWidget(self.startSCOCRButton, 3, 2)
		grid.addWidget(self.pauseSCOCRButton, 3, 3)
		grid.addWidget(self.terminateSCOCRButton, 3, 4)
		#grid.addWidget(self.slider_skewx, 4, 0, 1, 3)
		
		grid.addWidget(QtWidgets.QLabel("Camera source"), 4, 0, 1, 6)
		grid.addWidget(self.SCvideoCaptureIndex, 5, 0, 1, 6)

		grid.addWidget(QtWidgets.QLabel("Websocket address"), 6, 0, 1, 6)
		grid.addWidget(self.SCwebsocketAddress, 7, 0, 1, 6)

		self.SCssocrArguments.editingFinished.connect(self.update_state)
		self.SCrotation.editingFinished.connect(self.update_state)
		self.SCskewx.editingFinished.connect(self.update_state)
		self.SCerosion.editingFinished.connect(self.update_state)
		self.SCthreshold.editingFinished.connect(self.update_state)
		self.SCwaitKey.editingFinished.connect(self.update_state)
		self.SCvideoCaptureIndex.editingFinished.connect(self.update_state)
		self.SCwebsocketAddress.editingFinished.connect(self.update_state)
		self.SCcropLeft.editingFinished.connect(self.update_state)
		self.SCcropTop.editingFinished.connect(self.update_state)
		self.slider_skewx.valueChanged.connect(self.update_state)

		grid.setColumnStretch(0,50)
		grid.setColumnStretch(1,25)
		grid.setColumnStretch(2,25)
		groupBox.setLayout(grid)
		return groupBox

	def ui_create_debug_group(self):
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

	def ui_create_camera_preview_group(self):
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

if __name__ == '__main__':
	app = QtWidgets.QApplication(sys.argv)
	ex = MainWindow()
	sys.exit(app.exec_())
