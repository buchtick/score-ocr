# coding: utf8

from PySide6 import QtCore
from PySide6.QtGui import *

from enum import Enum

import logging

import math
import numpy
import cv2
import array
from cv2 import * # OpenCV imports

#lookup table for seven-segment recognition
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
		self.name = name
		self.type = DigitGroupType.AUTOFIND
		self.coords = ["","","",""]
		self.coords_num = [0,0,0,0]
		self.digits = []
		self.enabled = False

	@property
	def value(self):
		value = ""
		for digit in sorted(self.digits, key=lambda x: x.coords_num[0]):
			value += str(digit.value)
		return value

	def processDigits(self, image):
		croppedImage = image[self.coords_num[1]:self.coords_num[3], self.coords_num[0]:self.coords_num[2]]
		contours, hierarchy = cv2.findContours(croppedImage, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

		logging.debug("Number of contours found: %s", str(len(contours)))

		#go through contours and update/create digits
		for contour in contours:
			x,y,w,h = cv2.boundingRect(contour)
			area = w*h
			if (area) > 700:
				#find centroids
				M = cv2.moments(contour)
				cx = int(M['m10']/M['m00'])
				cy = int(M['m01']/M['m00'])
				inDigit = False
				for digit in self.digits:
					#check if contour centroid is in this stored digit
					if (digit.coords_num[0] < cx < digit.coords_num[2]) and (digit.coords_num[1] < cy < digit.coords_num[3]):
						inDigit = True
						if (digit.contour_area < area or digit.contour_width < w or digit.contour_height < h):
							digit.coords = [str(x), str(y), str(x+w), str(y+h)]
							digit.coords_num = [x, y, x+w, y+h]
						break

				if not inDigit:
					newDigit = SingleDigit(self.name)
					newDigit.enabled = True
					newDigit.coords = [str(x), str(y), str(x+w), str(y+h)]
					newDigit.coords_num = [x, y, x+w, y+h]
					self.digits.append(newDigit)
		
		for digit in self.digits:
			digit.process_image(croppedImage)

class SingleDigit():
	def __init__(self, name):
		self.name = name
		self.coords = ["","","",""]
		self.coords_num = [0,0,0,0]
		self.value = ""
		self.enabled = False

	@property
	def contour_height(self):
		return self.coords_num[3] - self.coords_num[1]
	
	@property
	def contour_width(self):
		return self.coords_num[2] - self.coords_num[0]
	
	@property
	def contour_area(self):
		return self.contour_width * self.contour_height

	def process_image(self, image, offsetx = 0, offsety = 0):
		croppedImage = image[self.coords_num[1]+offsety:self.coords_num[3]+offsety, self.coords_num[0]+offsetx:self.coords_num[2]+offsetx]
		croppedImage = autocrop(cv2.threshold(croppedImage, 127, 255, cv2.THRESH_BINARY_INV)[1], 10)

		processedDigitImage = cv2.resize(croppedImage, (50, 70), 1, 1, cv2.INTER_NEAREST)

		self.value = parseSingleDigit(processedDigitImage,self.value)

class ScOcrWorkerParams():
	def __init__(self, waitKey, videoCaptureIndex, rotation, skewx, skewy, erosion, dilate, threshold, cropLeft, cropTop, autocrop_enabled, autocrop_coords):
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
		self.autocrop_enabled = autocrop_enabled
		self.autocrop_coords = autocrop_coords
		
class ScOcrWorker(QtCore.QThread):
	error = QtCore.Signal(int)
	allDigitGroups = QtCore.Signal(object)
	alldigits = QtCore.Signal(object) #should be Signal(dict) but there's a bug in PySide6
	QImageFrame = QtCore.Signal(list)
	processedFrameFlag = QtCore.Signal(int)

	def __init__(self, ocr_coords, params):
		QtCore.QThread.__init__(self)
		self._isRunning = False
		self._isPaused = False

		self.digits = []

		self.digit_groups = []

		#ocr worker parameters
		self.params = params

		self.coords = ocr_coords #coordinates list without graphics

		self.cam = None # VideoCapture object, created in run()
		self.video_device = None

		self.update_ocr_coordinates(ocr_coords)

	def update_params(self, new_params):
		self.params = new_params

	def update_ocr_coordinates(self, ocr_coords):
		self.coords = ocr_coords
		
		self.digits.clear()

		self.digit_groups.clear()
	
		for i, coord in enumerate(self.coords):
			newDigitGrp = DigitGroup(coord.name)
			newDigitGrp.coords = coord.get_text_coords()
			newDigitGrp.coords_num = coord.get_coords()
			self.digit_groups.append(newDigitGrp)

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
		if (self.params.autocrop_enabled):
			#TODO, just return the input image for now
			img_processed = img
		else:
			##### CROP IMAGE ######
			img_cropped = cv2.copyMakeBorder(img, 0, 0, 0, 0, cv2.BORDER_REPLICATE)
			if(self.params.cropLeft >= 0):
				img_cropped = img_cropped[0:img_cropped.shape[0], self.params.cropLeft:img_cropped.shape[1]]
			elif(self.params.cropLeft < 0):
				img_cropped = cv2.copyMakeBorder(img_cropped,0,0,abs(self.params.cropLeft),0,cv2.BORDER_CONSTANT, value=[255,255,255])
			if(self.params.cropTop >= 0):
				img_cropped = img_cropped[self.params.cropTop:img_cropped.shape[0], 0:img_cropped.shape[1]]
			elif(self.params.cropTop < 0):
				img_cropped = cv2.copyMakeBorder(img_cropped,abs(self.params.cropTop),0,0,0,cv2.BORDER_CONSTANT, value=[255,255,255])

			##### OPENCV PROCESSING ######
			img_HSV = cv2.cvtColor(img_cropped, cv2.COLOR_BGR2HSV)
			rows,cols,_ = img_HSV.shape

			# rotate image
			M = cv2.getRotationMatrix2D((cols/2,rows/2), self.params.rotation, 1)
			img_HSV = cv2.warpAffine(img_HSV, M, (cols,rows))	

			# shear image
			M_sh = numpy.float32([[1, math.tan(self.params.skewx*math.pi/180), 0],
							[math.tan(self.params.skewy*math.pi/180), 1, 0],
							[0, 0, 1]])
			img_processed = cv2.warpPerspective(img_HSV, M_sh,(cols,rows))

		return img_processed
	
	def adjust_img_morphology(self, img):
		# treshold and erode
		h, s, img_v = cv2.split(img)
		ret3, img_th = cv2.threshold(img_v, self.params.threshold, 255, cv2.THRESH_BINARY)
		img_processed = cv2.erode(img_th, numpy.ones((2,2),numpy.uint8), iterations = self.params.erosion)
		img_processed = cv2.dilate(img_processed, numpy.ones((2,2),numpy.uint8), iterations = self.params.dilate)

		return img_processed

	def run(self):
		try:
			if self.params.videoCaptureIndex is None:
				self.cam = cv2.VideoCapture('test_images/test_video.mp4')	# start video
				#self.cam = cv2.VideoCapture('rtsp://rtspstream:856ae07f2949bbd02059a83eeb0a12ba@zephyr.rtsp.stream/pattern')	# start video
			else:
				self.cam = cv2.VideoCapture(self.params.videoCaptureIndex)

			logging.info("Webcam native resolution: %u %u", self.cam.get(cv2.CAP_PROP_FRAME_WIDTH), self.cam.get(cv2.CAP_PROP_FRAME_HEIGHT))
			self.cam.set(cv2.CAP_PROP_FRAME_WIDTH, 960)
			self.cam.set(cv2.CAP_PROP_FRAME_HEIGHT, 540)

			self._isRunning = True

			while self._isRunning:
				# close the OCR session if cam is not available or is closed
				if self.cam is None or not self.cam.isOpened() or not self._isRunning:
					break

				# pause the OCR session
				if self._isPaused:
					pass
				else:
					success, img = self.cam.read()

				# get out if the frame is not captured
				if not success:
					break

				img_transformed = self.adjust_img_geometry(img)
				img_processed = self.adjust_img_morphology(img_transformed)

				##### SHOW PRELIMINARY PROCESSED IMAGE WITH BOUNDING BOXES, X, Y #####
				img_disp = cv2.copyMakeBorder(img_processed, 0, 0, 0, 0, cv2.BORDER_REPLICATE)
				img_disp = cv2.cvtColor(img_disp, cv2.COLOR_GRAY2RGB)

				# show bounding boxes and preliminary numbers
				shapes = numpy.zeros(img_disp.shape, numpy.uint8)

				# for digit in self.digits:
				# 	digit.process_image(img_processed)

				# 	cv2.rectangle(img_disp, (digit.coords_num[0], digit.coords_num[1]), (digit.coords_num[2], digit.coords_num[3]), (0,0,255), 1)
				# 	cv2.putText(img_disp, str(digit.value), (digit.coords_num[2] - 10, digit.coords_num[3] + 10), cv2.FONT_ITALIC, 0.4, (255,255,0))

				for digitgrp in self.digit_groups:
					digitgrp.processDigits(img_processed)
					cv2.rectangle(shapes, (digitgrp.coords_num[0], digitgrp.coords_num[1]), (digitgrp.coords_num[2], digitgrp.coords_num[3]), (0,0,255), cv2.FILLED)
					cv2.putText(img_disp, str(digitgrp.value), (digitgrp.coords_num[2] - 10, digitgrp.coords_num[3] + 10), cv2.FONT_ITALIC, 0.4, (255,255,0))
					for digit in digitgrp.digits:
						cv2.rectangle(shapes, (digitgrp.coords_num[0] + digit.coords_num[0], digitgrp.coords_num[1] + digit.coords_num[1]), (digitgrp.coords_num[0] + digit.coords_num[2], digitgrp.coords_num[1] + digit.coords_num[3]), (0,255,0), cv2.FILLED)

				alpha = 0.6

				img_disp = cv2.addWeighted(img_disp, 1, shapes, 1-alpha, 0.5)

				##### SEND QIMAGE TO DISPLAY IN PYSIDE WINDOW #####
				height, width, bPC = img.shape
				_ret_QImageRaw = QImage(img.data, width, height, bPC * width, QImage.Format_RGB888).rgbSwapped()
				height, width, bPC = img_disp.shape
				_ret_QImageProcessed = QImage(img_disp.data, width, height, bPC * width, QImage.Format_RGB888).rgbSwapped()
				self.QImageFrame.emit([_ret_QImageRaw, _ret_QImageProcessed])

				cv2.waitKey(40)
				if self._isRunning:
					self.alldigits.emit(self.digits)
					self.allDigitGroups.emit(self.digit_groups)
					self.processedFrameFlag.emit(1)
				
		except Exception as e:
			print(e)
			# self.error.emit(1)