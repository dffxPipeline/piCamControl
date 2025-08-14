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
from picamera2 import Picamera2, libcamera
from picamera2.encoders import H264Encoder
from picamera2.outputs import FfmpegOutput
from libcamera import controls
import board
import busio
from adafruit_pca9685 import PCA9685

app = Flask(__name__)

servos_found = False
picam2 = None  # Define picam2 outside the try block
recording_process = None  # To keep track of the recording process
camera_model = ""  # Variable to store the camera model name
is_recording = False  # Tracks recording state for picamera2

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
    camera_info = picam2.camera_properties
    camera_model = camera_info.get("Model", "")  # Store the camera model name

    if "64" in camera_model:
        print("Arducam Hawkeye 64 MP Camera found.")
        if is_bookworm():  # Only rotate if the OS is Bookworm
            print("Detected Raspbian Bookworm. Applying 180-degree rotation.")
            config = picam2.create_preview_configuration(
                main={"format": "RGB888", "size": (1280, 720)},
                transform=libcamera.Transform(hflip=1, vflip=1)  # Rotate 180 degrees
            )
        else:
            print("Non-Bookworm OS detected. No rotation applied.")
            config = picam2.create_preview_configuration(
                main={"format": "RGB888", "size": (1280, 720)}
            )
        # Turn on Auto Focus for stream and video
        picam2.set_controls({"AfMode": 1, "AfTrigger": 0})  # Assuming '1' enables Auto Focus
    else:
        print("Raspberry Pi HQ Camera found.")
        # No rotation for other cameras
        config = picam2.create_preview_configuration(
            main={"format": "RGB888", "size": (1280, 720)}
        )

    picam2.configure(config)
    picam2.start()
    
    # Apply anti-flicker settings after camera starts (works for both camera types)
    try:
        print("Applying anti-flicker settings...")
        # Let camera settle first
        time.sleep(1.0)
        
        # Apply comprehensive anti-flicker settings
        picam2.set_controls({
            "AeEnable": True,
            "AeExposureMode": controls.AeExposureModeEnum.Normal,
            "AeMeteringMode": controls.AeMeteringModeEnum.CentreWeighted,
            # Anti-flicker for 60Hz mains (change to 20000 for 50Hz regions)
            "AeFlickerMode": controls.AeFlickerModeEnum.Manual,
            "AeFlickerPeriod": 16667,   # 60Hz period in microseconds
            "AwbMode": controls.AwbModeEnum.Auto,
            # Improve image quality
            "NoiseReductionMode": controls.draft.NoiseReductionModeEnum.HighQuality,
            "Sharpness": 1.0,
            "Contrast": 1.0,  # Reset to neutral
            "Brightness": 0.0,  # Reset brightness to neutral
        })
        print("Anti-flicker settings applied successfully")
        time.sleep(2.0)  # Give settings time to take effect
        
        # For persistent banding issues, try manual exposure synchronized to power frequency
        try:
            # Get current auto-exposure result
            metadata = picam2.capture_metadata()
            current_exposure = metadata.get("ExposureTime", 16667)
            
            # Calculate synchronized exposure (multiple of flicker period)
            flicker_period = 16667  # 60Hz - change to 20000 for 50Hz
            sync_exposure = round(current_exposure / flicker_period) * flicker_period
            
            # Ensure reasonable exposure time - moderate settings for balanced brightness
            if sync_exposure < flicker_period * 2:  # Minimum 2x flicker period 
                sync_exposure = flicker_period * 2
            elif sync_exposure > flicker_period * 8:  # Reasonable cap for normal lighting
                sync_exposure = flicker_period * 8
                
            print(f"Setting synchronized manual exposure: {sync_exposure}μs (was {current_exposure}μs)")
            
            # Apply manual exposure synchronized to power line frequency
            picam2.set_controls({
                "AeEnable": False,
                "ExposureTime": sync_exposure,
                "AnalogueGain": 2.0  # Moderate gain increase
            })
            time.sleep(1.0)
            print("Manual anti-flicker exposure applied")
            
        except Exception as e:
            print(f"Manual exposure adjustment failed, using auto anti-flicker: {e}")
            
    except Exception as e:
        print(f"Failed to apply anti-flicker settings: {e}")
        
    # Settings are now applied - no need for duplicate preview controls since manual exposure is active
    print("Camera initialization complete with optimized brightness settings")
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
    global recording_process, is_recording
    data = request.get_json()
    action = data.get("action")

    if action == "start_recording":
        if not is_recording and recording_process is None:
            try:
                if "64" in camera_model:
                    video_output = "video.h264"
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
                    is_recording = True  # Set the recording flag
                else:
                    video_output = "video.mjpeg"
                    pts_output = "timestamp.pts"
                    # Stop picamera2 to release the camera resource
                    if picam2.started:
                        picam2.stop()
                    picam2.close()  # Explicitly release the camera resources

                    # Use rpicam-vid for Raspberry Pi HQ Camera
                    desired_resolution = (4056, 3040)
                    print("Starting video recording with rpicam-vid...")

                    # Determine the --sync flag based on the IP address
                    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                        s.connect(("8.8.8.8", 80))
                        host_ip = s.getsockname()[0]

                    central_server_ip = get_central_server_ip()
                    print(f"Central server IP used for sync: {central_server_ip}")  # Print the central server IP
                    if central_server_ip == "192.168.10.100":
                        sync_flag = f"--sync={'server' if host_ip == '192.168.10.111' else 'client'}"
                    else:
                        sync_flag = f"--sync={'server' if host_ip == '192.168.48.120' else 'client'}"

                    recording_process = subprocess.Popen([
                        "rpicam-vid",
                        "--output", video_output,
                        "--mode", "4056:3040:12:P",
                        "--width", str(desired_resolution[0]),
                        "--height", str(desired_resolution[1]),
                        "--shutter", "16666",  # 1/60 second - compromise between motion blur and brightness
                        #"--gain", "4.0",       # Increased analog gain for maximum brightness
                        "--codec", "mjpeg",
                        #"--quality", "100",
                        "--framerate", "24",
                        sync_flag,
                        "--timeout", "0",  # Disable the 5-second timeout
                        "--save-pts", pts_output
                    ])

                return jsonify({"success": True, "message": "Recording started successfully."})
            except Exception as e:
                print(f"Failed to start recording: {e}")
                return jsonify({"success": False, "error": str(e)})
        else:
            print("Recording is already in progress.")
            return jsonify({"success": False, "error": "Already recording"})

    elif action == "stop_recording":
        if is_recording or recording_process is not None:
            try:
                print("Stopping video recording...")
                if "64" in camera_model and is_recording:
                    # Stop recording with picamera2
                    picam2.stop_recording()
                    is_recording = False  # Reset the recording flag
                elif recording_process is not None:
                    # Stop recording with rpicam-vid
                    recording_process.send_signal(signal.SIGINT)  # Graceful stop
                    recording_process.wait()
                    recording_process = None

                # Wait until the video file is closed
                video_output = "video.mjpeg" if "64" not in camera_model else "video.h264"
                while os.path.exists(video_output):
                    try:
                        with open(video_output, 'rb'):
                            break
                    except IOError:
                        time.sleep(0.1)

                print("Recording stopped successfully and file is closed.")

                # Check file extension and convert if needed
                if video_output.endswith(".h264"):
                    mp4_output = "video.mp4"
                    if convert_to_mp4(video_output, mp4_output):
                        os.remove(video_output)  # Remove the H.264 file after successful conversion
                        print(f"Converted to MP4 and removed {video_output}.")
                        return jsonify({"success": True, "message": "Recording stopped and converted to MP4."})
                    else:
                        print("Failed to convert to MP4. Keeping the H.264 file.")
                        return jsonify({"success": False, "error": "Failed to convert to MP4."})
                else:
                    # For .mjpeg, no conversion needed
                    return jsonify({"success": True, "message": "Recording stopped successfully."})
            except Exception as e:
                print(f"Failed to stop recording: {e}")
                return jsonify({"success": False, "error": str(e)})
        else:
            print("No recording is in progress.")
            return jsonify({"success": False, "error": "Not recording"})
    elif action == "transfer_video":
        try:
            # Determine which file to transfer
            if os.path.exists("video.mp4"):
                original_output = "video.mp4"
                ext = "mp4"
            elif os.path.exists("video.mjpeg"):
                original_output = "video.mjpeg"
                ext = "mjpeg"
            elif os.path.exists("video.h264"):
                original_output = "video.h264"
                ext = "h264"
            else:
                return jsonify({"success": False, "error": "No video file found to transfer."})

            # Rename the file to include the Raspberry Pi name and timestamp
            pi_name = socket.gethostname()
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            new_output = f"{pi_name}_{timestamp}.{ext}"
            os.rename(original_output, new_output)

            # If a .pts file exists, rename it to match the video file (but with .pts extension)
            pts_file = "timestamp.pts"
            new_pts_file = f"{pi_name}_{timestamp}.pts"
            if os.path.exists(pts_file):
                os.rename(pts_file, new_pts_file)
            else:
                new_pts_file = None

            # Determine the central server IP
            central_server_ip = get_central_server_ip()
            central_server_path = "piCamControlOutput/"  # Replace with the actual path on the central server

            # Transfer video file
            scp_command = f"scp {new_output} chadfinnerty@{central_server_ip}:{central_server_path}"
            os.system(scp_command)

            # Transfer pts file if it exists
            if new_pts_file:
                scp_pts_command = f"scp {new_pts_file} chadfinnerty@{central_server_ip}:{central_server_path}"
                os.system(scp_pts_command)

            print(f"Video file {new_output} transferred to central server.")
            if new_pts_file:
                print(f"PTS file {new_pts_file} transferred to central server.")

            # Delete the files after transfer
            os.remove(new_output)
            print(f"Video file {new_output} deleted from local storage.")
            if new_pts_file:
                os.remove(new_pts_file)
                print(f"PTS file {new_pts_file} deleted from local storage.")

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
    """Handle photo capture and transfer requests."""
    data = request.get_json()
    action = data.get("action")
    
    if action == "capture_photo":
        return capture_photo()
    elif action == "transfer_photo":
        return transfer_photo()
    else:
        return jsonify({"success": False, "error": "Unknown action"})

def capture_photo():
    """Capture a photo and save it locally."""
    current_resolution = None  # Initialize to avoid UnboundLocalError
    try:
        # Determine the desired resolution based on the camera type
        if "64" in camera_model:
            # Arducam Hawkeye 64 MP Camera - keep original resolution
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

            # Create and apply the still configuration with high quality settings
            config = picam2.create_still_configuration(
                main={"size": desired_resolution, "format": "RGB888"},
                buffer_count=1
            )
            picam2.configure(config)

            # Restart the camera
            picam2.start()

        # ---- Use the existing anti-flicker settings ----
        # Camera already has optimized settings applied at startup
        try:
            time.sleep(0.5)  # Brief wait for stability
        except Exception:
            pass

        # Capture the photo with original filename format
        photo_filename = "photo.png"
        picam2.capture_file(photo_filename)
        print(f"Photo captured: {photo_filename}")

        # Rename the photo file to include the Raspberry Pi name and timestamp
        pi_name = socket.gethostname()
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        new_photo_filename = f"{pi_name}_{timestamp}.png"
        os.rename(photo_filename, new_photo_filename)

        return jsonify({"success": True, "message": "Photo captured successfully.", "filename": new_photo_filename})
    except Exception as e:
        print(f"Failed to capture photo: {e}")
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
            
            # Re-apply the optimized anti-flicker settings
            try:
                # Apply same settings as startup
                picam2.set_controls({
                    "AeEnable": True,
                    "AeExposureMode": controls.AeExposureModeEnum.Normal,
                    "AeMeteringMode": controls.AeMeteringModeEnum.CentreWeighted,
                    "AeFlickerMode": controls.AeFlickerModeEnum.Manual,
                    "AeFlickerPeriod": 16667,   # 60Hz period
                    "AwbMode": controls.AwbModeEnum.Auto,
                    "NoiseReductionMode": controls.draft.NoiseReductionModeEnum.HighQuality,
                    "Sharpness": 1.0,
                    "Contrast": 1.0,  # Reset to neutral
                    "Brightness": 0.0,  # Reset brightness to neutral
                })
                time.sleep(0.5)
                
                # Reapply manual exposure if it was working
                try:
                    flicker_period = 16667
                    picam2.set_controls({
                        "AeEnable": False,
                        "ExposureTime": flicker_period * 3,  # Moderate exposure time
                        "AnalogueGain": 2.0  # Match startup gain
                    })
                except Exception:
                    pass  # Fall back to auto if manual fails
                    
                print("Optimized anti-flicker settings restored to preview")
            except Exception as e:
                print(f"Failed to restore optimized settings: {e}")

def transfer_photo():
    """Transfer the most recent photo to the central server."""
    try:
        # Find the most recent photo file
        photo_files = [f for f in os.listdir('.') if f.endswith('.png') and '_' in f]
        if not photo_files:
            return jsonify({"success": False, "error": "No photo file found to transfer."})
        
        # Get the most recent photo file
        photo_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
        photo_filename = photo_files[0]

        # Determine the central server IP
        central_server_ip = get_central_server_ip()
        central_server_path = "piCamControlOutput/"  # Replace with the actual path on the central server
        scp_command = f"scp {photo_filename} chadfinnerty@{central_server_ip}:{central_server_path}"
        os.system(scp_command)

        print(f"Photo file {photo_filename} transferred to central server.")

        # Delete the photo file after transfer
        os.remove(photo_filename)
        print(f"Photo file {photo_filename} deleted from local storage.")

        return jsonify({"success": True, "message": "Photo transferred and deleted successfully."})
    except Exception as e:
        print(f"Failed to transfer photo: {e}")
        return jsonify({"success": False, "error": str(e)})

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
