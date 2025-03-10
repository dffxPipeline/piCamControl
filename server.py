import subprocess
import sys
import os
import time
import datetime
import socket

def install(package):
    if package == "picamera2":
        subprocess.check_call(["sudo", "apt", "install", "-y", "ffmpeg"])
        subprocess.check_call(["sudo", "apt", "install", "-y", package])
    elif package == "system_packages":
        system_packages = [
            "libatlas-base-dev",
            "libhdf5-dev",
            "libhdf5-serial-dev",
            "libjasper-dev"
        ]
        subprocess.check_call(["sudo", "apt", "update"])
        for sys_pkg in system_packages:
            subprocess.check_call(["sudo", "apt", "install", "-y", sys_pkg])
    elif package == "libcamera-apps":
        subprocess.check_call(["sudo", "apt", "install", "-y", package])
    else:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])

# List of required packages
required_packages = [
    "system_packages",
    "flask",
    "adafruit-circuitpython-servokit",
    "adafruit-circuitpython-pca9685",
    "opencv-python",
    "picamera2",
    "libcamera-apps"
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
from picamera2.encoders import H264Encoder
from picamera2.outputs import FfmpegOutput
import board
import busio
from adafruit_pca9685 import PCA9685

app = Flask(__name__)

servos_found = False
picam2 = None  # Define picam2 outside the try block
recording_process = None  # To keep track of the recording process
camera_model = ""  # Variable to store the camera model name

# Check if servos are connected
try:
    i2c = busio.I2C(board.SCL, board.SDA)
    pca = PCA9685(i2c)
    pca.frequency = 50
    pca.deinit()
    servos_found = True
except Exception as e:
    print("Servos not found.")

# Initialize camera
try:
    picam2 = Picamera2()
    config = picam2.create_preview_configuration(main={"size": (1280, 720)})
    picam2.configure(config)
    picam2.start()
    
    # Check and print camera type
    camera_info = picam2.camera_properties
    camera_model = camera_info.get("Model", "")  # Store the camera model name
    if "64" in camera_model:
        print("Arducam Hawkeye 64 MP Camera found.")
        # Turn on Auto Focus for stream and video
        picam2.set_controls({"AfMode": 1 ,"AfTrigger": 0})  # Assuming '1' enables Auto Focus
    else:
        print("Raspberry Pi HQ Camera found.")
except Exception as e:
    print("Camera not found. Exiting.")
    exit(1)

if servos_found:
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

def set_servo_angle(channel, angle):
    """Clamp and set the servo angle between 0-180 degrees."""
    angle = max(0, min(180, angle))
    kit.servo[channel].angle = angle
    return angle

@app.route('/')
def index():
    """Render HTML page with controls and video stream."""
    return render_template('index.html', servos_found=servos_found)

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

@app.route('/servos_status', methods=['GET'])
def servos_status():
    """Endpoint to get the status of servos."""
    return jsonify({"servos_found": servos_found})

def is_camera_in_use():
    """Check if the camera is being used by another process and print the details."""
    try:
        result = subprocess.run(['lsof', '/dev/video0'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.stdout != b'':
            print("Camera is in use by the following processes:")
            print(result.stdout.decode('utf-8'))
            return True
        return False
    except Exception as e:
        print(f"Error checking camera usage: {e}")
        return False

@app.route('/record', methods=['POST'])
def record():
    """Handle start and stop recording requests."""
    global recording_process
    data = request.get_json()
    action = data.get("action")

    if action == "start_recording":
        if recording_process is None:
            try:
                video_output = "video.h264"
                encoder = H264Encoder()
                print("Starting video recording...")
                #if "64" in camera_model:
                    #picam2.set_controls({"AfMode": 1 ,"AfTrigger": 0})  # Ensure Auto Focus is on
                picam2.start_recording(encoder, output=video_output)
                print("Recording started successfully.")
                recording_process = True
                return jsonify({"success": True, "message": "Recording started successfully."})
            except Exception as e:
                print(f"Failed to start recording: {e}")
                return jsonify({"success": False, "error": str(e)})
        else:
            print("Recording is already in progress.")
            return jsonify({"success": False, "error": "Already recording"})
    elif action == "stop_recording":
        if recording_process is not None:
            try:
                print("Stopping video recording...")
                picam2.stop_recording()
                recording_process = None
                
                # Add a delay to ensure the recording process is terminated
                #time.sleep(2)
                
                # Wait until the video file is closed
                video_output = "video.h264"
                while os.path.exists(video_output):
                    try:
                        with open(video_output, 'rb'):
                            break
                    except IOError:
                        time.sleep(0.1)
                
                print("Recording stopped successfully and file is closed.")
                
                # Rename the video file to include the Raspberry Pi name and timestamp
                pi_name = socket.gethostname()
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                new_video_output = f"{pi_name}_{timestamp}.h264"
                os.rename(video_output, new_video_output)
                
                # Transfer the file to the central server
                central_server_ip = "192.168.48.100"  # Replace with the actual IP address of the central server
                central_server_path = "piCamControlOutput/"  # Replace with the actual path on the central server
                scp_command = f"scp {new_video_output} chadfinnerty@{central_server_ip}:{central_server_path}"
                os.system(scp_command)
                
                print(f"Video file {new_video_output} transferred to central server.")
                
                # Delete the video file after transfer
                os.remove(new_video_output)
                print(f"Video file {new_video_output} deleted from local storage.")
                
                # Restart the server.py script
                print("Restarting server...")
                os.execv(sys.executable, ['python'] + sys.argv)
                
                return jsonify({"success": True, "message": "Recording stopped successfully, file renamed, transferred, and deleted."})
            except Exception as e:
                print(f"Failed to stop recording: {e}")
                return jsonify({"success": False, "error": str(e)})
        else:
            print("No recording is in progress.")
            return jsonify({"success": False, "error": "Not recording"})

def generate_frames():
    """Continuously capture frames from the camera and stream via Flask."""
    print("Starting video stream...")
    while True:
        if picam2 is not None:
            #if "64" in camera_model:
                #picam2.set_controls({"AfMode": 1 ,"AfTrigger": 0})  # Ensure Auto Focus is on
            frame = picam2.capture_array()
            _, buffer = cv2.imencode('.jpg', frame)
            frame_bytes = buffer.tobytes()

            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        else:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + b'\r\n')
    print("Stopping video stream...")

@app.route('/video_feed')
def video_feed():
    """Flask route for the video stream."""
    return Response(generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/hostname', methods=['GET'])
def hostname():
    """Endpoint to get the hostname of the Raspberry Pi."""
    return jsonify({"hostname": socket.gethostname()})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
