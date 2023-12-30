# coding: utf8

from PySide6 import QtCore
from PySide6.QtGui import *

from enum import Enum

import math
import numpy
import cv2
from cv2 import * # OpenCV imports

DIGITS_LOOKUP = {
    (1, 1, 1, 1, 1, 1, 0): 0,
    (0, 1, 1, 0, 0, 0, 0): 1,
    (1, 1, 0, 1, 1, 0, 1): 2,
    (1, 1, 1, 1, 0, 0, 1): 3,
    (0, 1, 1, 0, 0, 1, 1): 4,
    (1, 0, 1, 1, 0, 1, 1): 5,
    (0, 0, 1, 1, 1, 1, 1): 6,	#6 with activated high segment
    (1, 0, 1, 1, 1, 1, 1): 6,	#6 with activated high segment
    (1, 1, 1, 0, 0, 0, 0): 7,
    (1, 1, 1, 1, 1, 1, 1): 8,
    (1, 1, 1, 0, 0, 1, 1): 9,
    (1, 1, 1, 1, 0, 1, 1): 9,	#9 with activated low segment
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

class DigitGroupType(Enum):
	AUTOFIND = 1
	SINGLE = 2

class DigitGroup():
	def __init__(self, name):
		self.type = DigitGroupType.AUTOFIND
		self.search_coords = ["","","",""]
		self.digits = []
		self.enabled = False

	def findDigits(self):
		return

class SingleDigit():
	def __init__(self, name):
		self.name = name
		self.coords = ["","","",""]
		self.value = ""
		self.enabled = False

	def process_image(self, image):
		croppedImage = image[int('0' + self.coords[1]):int('0' + self.coords[3]), int('0' + self.coords[0]):int('0' + self.coords[2])]
		croppedImage = autocrop(cv2.threshold(croppedImage, 127, 255, cv2.THRESH_BINARY_INV)[1], 10)

		processedDigitImage = cv2.resize(croppedImage, (50, 70), 1, 1, cv2.INTER_NEAREST)

		self.value = parseSingleDigit(processedDigitImage,self.value)

class ScOcrWorkerParams():
	def __init__(self, waitKey, videoCaptureIndex, rotation, skewx, skewy, erosion, dilate, threshold, cropLeft, cropTop):
		self.waitKey = waitKey
		self.videoCaptureIndex = videoCaptureIndex
		self.rotation = int(rotation)
		self.skewx = int(skewx)
		self.skewy = int(skewy)
		self.erosion = int(erosion)
		self.dilate = int(dilate)
		self.threshold = int(threshold)
		self.cropLeft = int(cropLeft)
		self.cropTop = int(cropTop)
		self.mouse_coordinates = [0, 0]
		
class ScOcrWorker(QtCore.QThread):
	error = QtCore.Signal(int)
	recognizedDigits = QtCore.Signal(dict)
	alldigits = QtCore.Signal(object) #should be Signal(dict) but there's a bug in PySide6
	QImageFrame = QtCore.Signal(list)
	processedFrameFlag = QtCore.Signal(int)

	def __init__(self, ocr_coords, params):
		QtCore.QThread.__init__(self)

		self._isRunning = False
		self._isPaused = False
		self.processing_timer = 10

		self.digits = {}

		self.waitKey = params.waitKey
		self.coords = ocr_coords #coordinates list without graphics
		self.videoCaptureIndex = params.videoCaptureIndex
		self.rotation = int(params.rotation)
		self.skewx = int(params.skewx)
		self.skewy = int(params.skewy)
		self.erosion = int(params.erosion)
		self.dilate = int(params.dilate)
		self.threshold = int(params.threshold)
		self.cropLeft = int(params.cropLeft)
		self.cropTop = int(params.cropTop)
		self.mouse_coordinates = [0, 0]
		self.cam = None # VideoCapture object, created in run()
		self.video_device = None

		self.update_ocr_coordinates(ocr_coords)

	def update_params(self, new_params):
		self.waitKey = new_params.waitKey
		self.videoCaptureIndex = new_params.videoCaptureIndex
		self.rotation = int(new_params.rotation)
		self.skewx = int(new_params.skewx)
		self.skewy = int(new_params.skewy)
		self.erosion = int(new_params.erosion)
		self.dilate = int(new_params.dilate)
		self.threshold = int(new_params.threshold)
		self.cropLeft = int(new_params.cropLeft)
		self.cropTop = int(new_params.cropTop)
	
	def update_ocr_coordinates(self, ocr_coords):
		self.coords = ocr_coords
		
		self.digits.clear()
	
		for i, coord in enumerate(self.coords):
			self.digits[i] = SingleDigit(coord.name)
			self.digits[i].coords = coord.get_text_coords()

	def processSingleDigit(self, inputImage, coords):
		croppedImage = inputImage[int('0' + coords[2]):int('0' + coords[4]), int('0' + coords[1]):int('0' + coords[3])]
		croppedImage = autocrop(cv2.threshold(croppedImage, 127, 255, cv2.THRESH_BINARY_INV)[1], 10)

		processedDigitImage = cv2.resize(croppedImage, (50, 70), 1, 1, cv2.INTER_NEAREST)

		return processedDigitImage

	def pause(self):
		if self._isPaused:
			self._isPaused = False
		else:
			self._isPaused = True

	def kill(self):
		self._isRunning = False
		self.cam.release()
		self.quit()

	def adjust_img_geometry(self, img):
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
						[math.tan(self.skewy*math.pi/180), 1, 0],
						[0, 0, 1]])
		img_processed = cv2.warpPerspective(img_HSV, M_sh,(cols,rows))
		return img_processed
	
	def adjust_img_morphology(self, img):
		# treshold and erode
		h, s, img_v = cv2.split(img)
		ret3, img_th = cv2.threshold(img_v, self.threshold, 255, cv2.THRESH_BINARY)
		img_processed = cv2.erode(img_th, numpy.ones((2,2),numpy.uint8), iterations = self.erosion)
		img_processed = cv2.dilate(img_processed, numpy.ones((2,2),numpy.uint8), iterations = self.dilate)

		return img_processed

	def run(self):
		try:
			if self.videoCaptureIndex is None:
				self.cam = cv2.VideoCapture('test_images/test_video.mp4')	# start video
				#self.cam = cv2.VideoCapture('rtsp://rtspstream:856ae07f2949bbd02059a83eeb0a12ba@zephyr.rtsp.stream/pattern')	# start video
			else:
				self.cam = cv2.VideoCapture(self.videoCaptureIndex)

			print("Webcam native resolution: ", self.cam.get(cv2.CAP_PROP_FRAME_WIDTH), self.cam.get(cv2.CAP_PROP_FRAME_HEIGHT))
			self.cam.set(cv2.CAP_PROP_FRAME_WIDTH, 960)
			self.cam.set(cv2.CAP_PROP_FRAME_HEIGHT, 540)

			self._isRunning = True

			while self._isRunning:
				# close the OCR session if cam is not available or is closed
				if self.cam is None or not self.cam.isOpened() or not self._isRunning:
					break

				# pause the OCR session
				if self._isPaused:
					cv2.waitKey(int(self.waitKey))
					continue

				# READ THE FRAME
				success, img = self.cam.read()

				# get out if the frame is not captured
				if not success:
					break

				img_transformed = self.adjust_img_geometry(img)
				img_processed = self.adjust_img_morphology(img_transformed)

				#process all digits
				for digit in self.digits:
					self.digits[digit].process_image(img_processed)

				##### SHOW PRELIMINARY PROCESSED IMAGE WITH BOUNDING BOXES, X, Y #####
				img_disp = cv2.copyMakeBorder(img_processed, 0, 0, 0, 0, cv2.BORDER_REPLICATE)
				img_disp = cv2.cvtColor(img_disp, cv2.COLOR_GRAY2RGB)

				cv2.putText(img_disp, str(self.mouse_coordinates[0]) + ", " + str(self.mouse_coordinates[1]), (5, 15), cv2.FONT_ITALIC, 0.4, (255,255,0))


				# show bounding boxes and preliminary numbers
				for digit in self.digits:
					cv2.rectangle(img_disp, (int('0' + self.digits[digit].coords[0]), int('0' + self.digits[digit].coords[1])), (int('0' + self.digits[digit].coords[2]), int('0' + self.digits[digit].coords[3])), (0,0,255), 2)

				##### SEND QIMAGE TO DISPLAY IN PYSIDE WINDOW #####
				height, width, bPC = img.shape
				_ret_QImageRaw = QImage(img.data, width, height, bPC * width, QImage.Format_RGB888).rgbSwapped()
				height, width, bPC = img_disp.shape
				_ret_QImageProcessed = QImage(img_disp.data, width, height, bPC * width, QImage.Format_RGB888).rgbSwapped()
				self.QImageFrame.emit([_ret_QImageRaw, _ret_QImageProcessed])


				cv2.waitKey(40)
				if self._isRunning:
					self.alldigits.emit(self.digits)
					self.processedFrameFlag.emit(1)
				
		except Exception as e:
			print(e)
			# self.error.emit(1)