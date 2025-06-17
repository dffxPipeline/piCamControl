import subprocess
import sys
import os
import time
import datetime
import socket
import pkg_resources
import platform
import signal

def is_bookworm():
    """Check if the OS is Raspbian Bookworm."""
    try:
        with open("/etc/os-release", "r") as f:
            os_release = f.read().lower()
            print(f"Contents of /etc/os-release: {os_release}")  # Debugging output
            return "bookworm" in os_release
    except Exception as e:
        print(f"Error reading /etc/os-release: {e}")
        return False

def install(package):
    if package == "python3-picamera2":
        if not is_system_package_installed(package):
            subprocess.check_call(["sudo", "apt", "install", "-y", "ffmpeg"])
            subprocess.check_call(["sudo", "apt", "install", "-y", package])
    elif package == "system_packages":
        system_packages = [
            "libatlas-base-dev",
            "libhdf5-dev",
            "libhdf5-serial-dev"
        ]

        # Check if the OS is Bookworm
        if not is_bookworm():
            system_packages.append("libjasper-dev")  # Include libjasper-dev only if not Bookworm

        subprocess.check_call(["sudo", "apt", "update"])
        for sys_pkg in system_packages:
            if not is_system_package_installed(sys_pkg):
                subprocess.check_call(["sudo", "apt", "install", "-y", sys_pkg])
    elif package == "libcamera-apps":
        if not is_system_package_installed(package):
            subprocess.check_call(["sudo", "apt", "install", "-y", package])
    else:
        if not is_python_package_installed(package):
            pip_command = [sys.executable, "-m", "pip", "install", package]
            if is_bookworm():
                pip_command.append("--break-system-packages")
            subprocess.check_call(pip_command)

def is_python_package_installed(package):
    """Check if a Python package is installed."""
    try:
        pkg_resources.get_distribution(package)
        return True
    except pkg_resources.DistributionNotFound:
        return False

def is_system_package_installed(package):
    """Check if a system package is installed."""
    try:
        result = subprocess.run(["dpkg-query", "-W", "-f='${Status}'", package],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return "install ok installed" in result.stdout.decode("utf-8")
    except Exception:
        return False

# List of required packages
required_packages = [
    "system_packages",
    "flask",
    "adafruit-circuitpython-servokit",
    "adafruit-circuitpython-pca9685",
    "opencv-python",
    "python3-picamera2",
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
    config = picam2.create_preview_configuration(
        main={"format": "RGB888", "size": (1280, 720)}
    )
    picam2.configure(config)
    picam2.start()

    # Check and print camera type
    camera_info = picam2.camera_properties
    camera_model = camera_info.get("Model", "")  # Store the camera model name
    if "64" in camera_model:
        print("Arducam Hawkeye 64 MP Camera found.")
        # Turn on Auto Focus for stream and video
        picam2.set_controls({"AfMode": 1, "AfTrigger": 0})  # Assuming '1' enables Auto Focus
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

def get_central_server_ip():
    """Determine the central server IP based on the host's active network interface."""
    try:
        # Create a socket to determine the actual IP address
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            # Connect to a public IP (Google's DNS) to determine the active interface
            s.connect(("8.8.8.8", 80))
            host_ip = s.getsockname()[0]  # Get the IP address of the active interface
        print(f"Host IP address: {host_ip}")  # Print the host IP address

        # Determine the central server IP based on the host IP
        if host_ip.startswith("192.168.48."):
            central_server_ip = "192.168.48.100"
        else:
            central_server_ip = "192.168.10.100"
        print(f"Central server IP determined: {central_server_ip}")  # Print the central server IP
        return central_server_ip
    except Exception as e:
        print(f"Failed to determine host IP: {e}")
        return "192.168.10.100"  # Default to the original IP

@app.route('/record', methods=['POST'])
def record():
    """Handle start, stop recording, and transfer video requests."""
    global recording_process
    data = request.get_json()
    action = data.get("action")

    if action == "start_recording":
        if recording_process is None:
            try:
                video_output = "video.h264"

                if "64" in camera_model:
                    # Use picamera2 for Arducam Hawkeye 64 MP Camera
                    desired_resolution = (1280, 720)
                    current_config = picam2.camera_configuration()
                    current_resolution = current_config["main"]["size"] if current_config else None

                    if current_resolution != desired_resolution:
                        if picam2.started:
                            picam2.stop()

                        config = picam2.create_video_configuration(
                            main={"size": desired_resolution, "format": "H264"},
                            controls={"FrameDurationLimits": (33333, 33333)}
                        )
                        picam2.configure(config)
                        picam2.start()

                    encoder = H264Encoder()
                    print("Starting video recording with picamera2...")
                    picam2.start_recording(encoder, output=video_output)
                else:
                    # Use rpicam-vid for Raspberry Pi HQ Camera
                    desired_resolution = (1280, 720)
                    print("Starting video recording with rpicam-vid...")
                    recording_process = subprocess.Popen([
                        "rpicam-vid",
                        "--output", video_output,
                        "--width", str(desired_resolution[0]),
                        "--height", str(desired_resolution[1]),
                        "--framerate", "30"
                    ])

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
                if "64" in camera_model:
                    # Stop recording with picamera2
                    picam2.stop_recording()
                else:
                    # Stop recording with rpicam-vid
                    recording_process.terminate()
                    recording_process.wait()

                recording_process = None

                # Wait until the video file is closed
                video_output = "video.h264"
                while os.path.exists(video_output):
                    try:
                        with open(video_output, 'rb'):
                            break
                    except IOError:
                        time.sleep(0.1)

                print("Recording stopped successfully and file is closed.")

                # Convert H.264 to MP4
                mp4_output = "video.mp4"
                if convert_to_mp4(video_output, mp4_output):
                    os.remove(video_output)  # Remove the H.264 file after successful conversion
                    print(f"Converted to MP4 and removed {video_output}.")
                else:
                    print("Failed to convert to MP4. Keeping the H.264 file.")

                return jsonify({"success": True, "message": "Recording stopped and converted to MP4."})
            except Exception as e:
                print(f"Failed to stop recording: {e}")
                return jsonify({"success": False, "error": str(e)})
        else:
            print("No recording is in progress.")
            return jsonify({"success": False, "error": "Not recording"})
    elif action == "transfer_video":
        try:
            # Rename the MP4 file to include the Raspberry Pi name and timestamp
            pi_name = socket.gethostname()
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            mp4_output = "video.mp4"
            new_mp4_output = f"{pi_name}_{timestamp}.mp4"
            os.rename(mp4_output, new_mp4_output)

            # Determine the central server IP
            central_server_ip = get_central_server_ip()
            central_server_path = "piCamControlOutput/"  # Replace with the actual path on the central server
            scp_command = f"scp {new_mp4_output} chadfinnerty@{central_server_ip}:{central_server_path}"
            os.system(scp_command)

            print(f"Video file {new_mp4_output} transferred to central server.")

            # Delete the MP4 file after transfer
            os.remove(new_mp4_output)
            print(f"Video file {new_mp4_output} deleted from local storage.")

            # Send a success response **before** restarting the server
            response = jsonify({"success": True, "message": "Video transferred and deleted successfully."})
            response.status_code = 200

            # Restart the server after sending the response
            def restart_server():
                """Restart the server."""
                print("Restarting server...")

                if is_bookworm():
                    print("Detected Raspbian Bookworm. Applying Bookworm-specific restart logic.")
                    # Get the current process ID (PID)
                    current_pid = os.getpid()
                    print(f"Current process PID: {current_pid}")

                    # Use a subprocess to restart the server after killing the current process
                    python_executable = sys.executable
                    script_path = sys.argv[0]

                    # Start a new process to run the server
                    subprocess.Popen([python_executable, script_path])

                    # Allow some time for the new process to start
                    time.sleep(2)

                    # Terminate the current process
                    os.kill(current_pid, signal.SIGTERM)
                else:
                    print("Non-Bookworm OS detected. Using standard restart logic.")
                    os.execv(sys.executable, ['python'] + sys.argv)

            # Use a background thread to restart the server
            import threading
            threading.Thread(target=restart_server).start()

            return response
        except Exception as e:
            print(f"Failed to transfer video: {e}")
            return jsonify({"success": False, "error": str(e)})

@app.route('/take_photo', methods=['POST'])
def take_photo():
    """Capture a photo and send it to the central server."""
    current_resolution = None  # Initialize to avoid UnboundLocalError
    try:
        # Determine the desired resolution based on the camera type
        if "64" in camera_model:
            # Arducam Hawkeye 64 MP Camera
            desired_resolution = (1280, 720)
        else:
            # Raspberry Pi HQ Camera
            desired_resolution = (4056, 3040)

        # Check if the current configuration matches the desired resolution
        current_config = picam2.camera_configuration()  # Call the method to get the configuration
        current_resolution = current_config["main"]["size"] if current_config else None

        if current_resolution != desired_resolution:
            # Stop the camera before reconfiguring
            if picam2.started:
                picam2.stop()

            # Create and apply the still configuration
            config = picam2.create_still_configuration(
                main={"size": desired_resolution}
            )
            picam2.configure(config)

            # Restart the camera
            picam2.start()

        # Capture the photo
        photo_filename = "photo.png"
        picam2.capture_file(photo_filename)
        print(f"Photo captured: {photo_filename}")

        # Rename the photo file to include the Raspberry Pi name and timestamp
        pi_name = socket.gethostname()
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        new_photo_filename = f"{pi_name}_{timestamp}.png"
        os.rename(photo_filename, new_photo_filename)

        # Determine the central server IP
        central_server_ip = get_central_server_ip()
        central_server_path = "piCamControlOutput/"  # Replace with the actual path on the central server
        scp_command = f"scp {new_photo_filename} chadfinnerty@{central_server_ip}:{central_server_path}"
        os.system(scp_command)

        print(f"Photo file {new_photo_filename} transferred to central server.")

        # Delete the photo file after transfer
        os.remove(new_photo_filename)
        print(f"Photo file {new_photo_filename} deleted from local storage.")

        return jsonify({"success": True, "message": "Photo taken and sent to the central server successfully."})
    except Exception as e:
        print(f"Failed to take photo: {e}")
        return jsonify({"success": False, "error": str(e)})
    finally:
        # Restore the preview configuration if it was changed
        if current_resolution != desired_resolution:
            if picam2.started:
                picam2.stop()
            preview_config = picam2.create_preview_configuration(
                main={"format": "RGB888", "size": (1280, 720)}
            )
            picam2.configure(preview_config)
            picam2.start()

def get_frame_rate(h264_file):
    """Retrieve the frame rate of an H.264 file using ffprobe."""
    try:
        command = [
            "ffprobe",
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=r_frame_rate",
            "-of", "default=noprint_wrappers=1:nokey=1",
            h264_file
        ]
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode == 0:
            frame_rate = result.stdout.decode("utf-8").strip()
            print(f"Frame rate of {h264_file}: {frame_rate} (raw format)")
            # Convert the raw frame rate (e.g., "30000/1001") to a float
            if "/" in frame_rate:
                num, denom = map(int, frame_rate.split("/"))
                frame_rate = num / denom
            print(f"Frame rate of {h264_file}: {frame_rate} FPS")
            return frame_rate
        else:
            print(f"Failed to retrieve frame rate: {result.stderr.decode('utf-8')}")
            return None
    except Exception as e:
        print(f"Error retrieving frame rate: {e}")
        return None

def get_video_metadata(h264_file):
    """Retrieve the pixel format and colorspace of an H.264 file using ffprobe."""
    try:
        command = [
            "ffprobe",
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=pix_fmt,colorspace,color_primaries,color_transfer,color_space",
            "-of", "default=noprint_wrappers=1:nokey=1",
            h264_file
        ]
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode == 0:
            metadata = result.stdout.decode("utf-8").strip()
            print(f"Metadata of {h264_file}:\n{metadata}")
            return metadata
        else:
            print(f"Failed to retrieve metadata: {result.stderr.decode('utf-8')}")
            return None
    except Exception as e:
        print(f"Error retrieving metadata: {e}")
        return None

def convert_to_mp4(h264_file, mp4_file):
    """Convert an H.264 file to MP4 using FFmpeg."""
    try:
        # Print the frame rate before conversion
        get_frame_rate(h264_file)

        # Print the pixel format and colorspace before conversion
        get_video_metadata(h264_file)

        command = [
            "ffmpeg",
            "-y",  # Overwrite output file if it exists
            "-r", "30",  # Force the frame rate to 30 FPS
            "-i", h264_file,  # Input file
            "-c:v", "copy",  # Copy the video stream without re-encoding
            mp4_file  # Output file
        ]
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode == 0:
            print(f"Successfully converted {h264_file} to {mp4_file} at 30 FPS")
            return True
        else:
            print(f"Failed to convert {h264_file} to MP4: {result.stderr.decode('utf-8')}")
            return False
    except Exception as e:
        print(f"Error during conversion: {e}")
        return False

def generate_frames():
    """Continuously capture frames from the camera and stream via Flask."""
    print("Starting video stream...")
    if "64" in camera_model:
        # Use picam2 for Arducam Hawkeye 64 MP Camera
        while True:
            if picam2 is not None:
                frame = picam2.capture_array()
                _, buffer = cv2.imencode('.jpg', frame)
                frame_bytes = buffer.tobytes()

                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            else:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + b'\r\n')
    else:
        # Use rpicam-vid for Raspberry Pi HQ Camera
        try:
            # Start rpicam-vid with MJPEG codec and output to stdout
            process = subprocess.Popen(
                [
                    "rpicam-vid",
                    "--codec", "mjpeg",
                    "--width", "1280",
                    "--height", "720",
                    "--framerate", "30",
                    "-o", "-"
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )

            # Read MJPEG frames from stdout
            while True:
                frame_bytes = process.stdout.read(4096)  # Adjust buffer size as needed
                if not frame_bytes:
                    print("No data received from rpicam-vid. Exiting stream loop.")
                    break

                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        except Exception as e:
            print(f"Error during video streaming with rpicam-vid: {e}")
        finally:
            if process:
                process.terminate()
                process.wait()
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
