import subprocess
import sys

def install(package):
    if package == "python3-picamera2":
        subprocess.check_call(["sudo", "apt", "install", "-y", package])
    else:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])

# List of required packages
required_packages = [
    "flask",
    "adafruit-circuitpython-servokit",
    "adafruit-circuitpython-pca9685",
    "opencv-python",
    "python3-picamera2"
]

# Install missing packages
for package in required_packages:
    try:
        __import__(package)
    except ImportError:
        install(package)

from flask import Flask, render_template, request, jsonify, Response
from adafruit_servokit import ServoKit
import cv2
from picamera2 import Picamera2
import board
import busio
from adafruit_pca9685 import PCA9685

app = Flask(__name__)

# Check if servos are connected
try:
    i2c = busio.I2C(board.SCL, board.SDA)
    pca = PCA9685(i2c)
    pca.frequency = 50
    pca.deinit()
except Exception as e:
    print("Servos not found. Exiting.")
    exit(1)

# Initialize PCA9685 for servo control
kit = ServoKit(channels=16)

# Servo channel assignments
TILT_SERVO = 0
PAN_SERVO = 1
ZOOM_SERVO = 2  # Only if using a zoom function

# Default servo positions
pan_angle = 90
tilt_angle = 90
zoom_level = 90

# Initialize Arducam Hawkeye 64MP
try:
    picam2 = Picamera2()
    config = picam2.create_preview_configuration(main={"size": (1280, 720)})
    picam2.configure(config)
    picam2.start()
except Picamera2Error as e:
    print("Arducam Hawkeye 64MP Camera not found. Exiting.")
    exit(1)

def set_servo_angle(channel, angle):
    """Clamp and set the servo angle between 0-180 degrees."""
    angle = max(0, min(180, angle))
    kit.servo[channel].angle = angle
    return angle

@app.route('/')
def index():
    """Render HTML page with controls and video stream."""
    return render_template('index.html')

@app.route('/control', methods=['POST'])
def control():
    """Handle servo control requests."""
    global pan_angle, tilt_angle, zoom_level

    data = request.get_json()
    action = data.get("action")

    if action == "pan_left":
        pan_angle = set_servo_angle(PAN_SERVO, pan_angle - 2)
    elif action == "pan_right":
        pan_angle = set_servo_angle(PAN_SERVO, pan_angle + 2)
    elif action == "tilt_up":
        tilt_angle = set_servo_angle(TILT_SERVO, tilt_angle + 2)
    elif action == "tilt_down":
        tilt_angle = set_servo_angle(TILT_SERVO, tilt_angle - 2)
    elif action == "zoom_in":
        zoom_level = set_servo_angle(ZOOM_SERVO, zoom_level + 2)
    elif action == "zoom_out":
        zoom_level = set_servo_angle(ZOOM_SERVO, zoom_level - 2)

    return jsonify({"pan": pan_angle, "tilt": tilt_angle, "zoom": zoom_level})

def generate_frames():
    """Continuously capture frames from the Arducam and stream via Flask."""
    while True:
        frame = picam2.capture_array()
        _, buffer = cv2.imencode('.jpg', frame)
        frame_bytes = buffer.tobytes()

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

@app.route('/video_feed')
def video_feed():
    """Flask route for the video stream."""
    return Response(generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
