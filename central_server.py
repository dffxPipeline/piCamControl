from flask import Flask, render_template, request, jsonify
import requests
import os
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor

app = Flask(__name__)

# Determine the IP address of the machine running this script
def get_host_ip():
    """Determine the local IP address of the machine."""
    try:
        # Create a dummy socket connection to determine the local IP
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))  # Connect to a public DNS server
            host_ip = s.getsockname()[0]  # Get the local IP address
        print(f"Host IP address determined: {host_ip}")
        return host_ip
    except socket.error as e:
        print(f"Error determining host IP: {e}")
        return None

# Adjust the Raspberry Pi IP list based on the host's IP
host_ip = get_host_ip()
if host_ip == "192.168.48.100":
    raspberry_pi_ips = [
        "192.168.48.81",
        #"192.168.48.115",
        "192.168.48.120"
    ]
else:
    raspberry_pi_ips = [
        "192.168.10.111",
        "192.168.10.112",
        "192.168.10.113",
        "192.168.10.114",
        "192.168.10.115",
        "192.168.10.116",
        "192.168.10.121",
        "192.168.10.122",
        "192.168.10.123",
        "192.168.10.124",
        "192.168.10.125",
        "192.168.10.126",
        "192.168.10.131",
        "192.168.10.132",
        "192.168.10.133",
        "192.168.10.134",
        "192.168.10.135",
        "192.168.10.136",
        "192.168.10.141",
        "192.168.10.142",
        "192.168.10.143",
        "192.168.10.144",
        "192.168.10.145",
        "192.168.10.146",
        "192.168.10.151",
        "192.168.10.152",
        #"192.168.10.153",
        "192.168.10.154",
        #"192.168.10.155",
        "192.168.10.156",
        "192.168.10.161",
        "192.168.10.162",
        "192.168.10.163",
        "192.168.10.164",
        "192.168.10.165",
        "192.168.10.166",
        "192.168.10.171",
        "192.168.10.172",
        "192.168.10.173",
        "192.168.10.174",
        "192.168.10.175",
        "192.168.10.176",
        "192.168.10.181",
        "192.168.10.182",
        "192.168.10.183",
        "192.168.10.184",
        "192.168.10.185",
        "192.168.10.186",
        "192.168.10.191",
        "192.168.10.192",
        "192.168.10.193",
        "192.168.10.194",
        "192.168.10.195",
        "192.168.10.196"
        # Add all other IP addresses here
    ]

def get_servos_status():
    servos_status = {}
    for ip in raspberry_pi_ips:
        try:
            response = requests.get(f'http://{ip}:5000/servos_status')
            response.raise_for_status()
            data = response.json()
            servos_status[ip] = data.get("servos_found", False)
        except requests.RequestException as e:
            print(f"Error getting servos status from {ip}: {e}")
            servos_status[ip] = False
    return servos_status

def get_hostnames():
    hostnames = {}
    for ip in raspberry_pi_ips:
        try:
            response = requests.get(f'http://{ip}:5000/hostname')
            response.raise_for_status()
            data = response.json()
            hostnames[ip] = data.get("hostname", "Unknown")
        except requests.RequestException as e:
            print(f"Error getting hostname from {ip}: {e}")
            hostnames[ip] = "Unknown"
    return hostnames

@app.route('/')
def index():
    """Render HTML page with all camera feeds."""
    servos_status = {}
    hostnames = {}
    offline_devices = []

    for ip in raspberry_pi_ips:
        try:
            # Get servos status
            response = requests.get(f'http://{ip}:5000/servos_status', timeout=5)
            response.raise_for_status()
            servos_status[ip] = response.json().get("servos_found", False)

            # Get hostname
            response = requests.get(f'http://{ip}:5000/hostname', timeout=5)
            response.raise_for_status()
            hostnames[ip] = response.json().get("hostname", "Unknown")
        except requests.RequestException:
            # Mark device as offline
            servos_status[ip] = False
            hostnames[ip] = "Offline"
            offline_devices.append(ip)

    return render_template(
        'index.html',
        raspberry_pi_ips=raspberry_pi_ips,
        servos_status=servos_status,
        hostnames=hostnames,
        offline_devices=offline_devices
    )

@app.route('/control', methods=['POST'])
def control():
    action = request.json.get('action')
    ip = request.json.get('ip')
    try:
        response = requests.post(f'http://{ip}:5000/control', json={'action': action})
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as e:
        print(f"Error sending control action to {ip}: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/record', methods=['POST'])
def record():
    action = request.json.get('action')
    success = True
    errors = []

    if action == "stop_recording":
        # Step 1: Stop recording on all Raspberry Pis concurrently
        def stop_recording(ip):
            try:
                response = requests.post(f'http://{ip}:5000/record', json={'action': 'stop_recording'})
                response.raise_for_status()
                if not response.json().get('success', False):
                    raise Exception(response.json().get('error', 'Unknown error'))
                print(f"Recording stopped on {ip}")
            except requests.RequestException as e:
                print(f"Error stopping recording on {ip}: {e}")
                return f"Error stopping recording on {ip}: {e}"

        with ThreadPoolExecutor() as executor:
            results = list(executor.map(stop_recording, raspberry_pi_ips))

        # Collect errors from the results
        errors = [result for result in results if result]
        if errors:
            success = False

        # Step 2: Transfer video files to the central server concurrently
        def transfer_video(ip):
            try:
                print(f"Starting file transfer from {ip}...")
                response = requests.post(f'http://{ip}:5000/record', json={'action': 'transfer_video'})
                response.raise_for_status()
                if not response.json().get('success', False):
                    raise Exception(response.json().get('error', 'Unknown error'))
                print(f"File transfer from {ip} completed successfully.")
            except requests.RequestException as e:
                print(f"Error transferring video from {ip}: {e}")
                return f"Error transferring video from {ip}: {e}"

        with ThreadPoolExecutor() as executor:
            results = list(executor.map(transfer_video, raspberry_pi_ips))

        # Collect errors from the results
        errors.extend([result for result in results if result])
        if errors:
            success = False

    elif action == "start_recording":
        # Start recording on all Raspberry Pis concurrently
        def start_recording(ip):
            try:
                print(f"Starting recording on {ip}...")
                response = requests.post(f'http://{ip}:5000/record', json={'action': 'start_recording'})
                response.raise_for_status()
                if not response.json().get('success', False):
                    raise Exception(response.json().get('error', 'Unknown error'))
                print(f"Recording started on {ip}")
            except requests.RequestException as e:
                print(f"Error starting recording on {ip}: {e}")
                return f"Error starting recording on {ip}: {e}"

        with ThreadPoolExecutor() as executor:
            results = list(executor.map(start_recording, raspberry_pi_ips))

        # Collect errors from the results
        errors = [result for result in results if result]
        if errors:
            success = False

    else:
        errors.append(f"Unknown action: {action}")
        success = False

    return jsonify({'success': success, 'errors': errors})

@app.route('/manage_servers', methods=['POST'])
def manage_servers():
    """Start server.py on each Raspberry Pi if it isn't currently running."""
    success = True
    messages = []
    errors = []

    for ip in raspberry_pi_ips:
        try:
            # Check if server.py is running
            response = requests.get(f'http://{ip}:5000/hostname', timeout=5)
            if response.status_code == 200:
                hostname = response.json().get('hostname', 'Unknown')
                messages.append(f"Server is already running on {hostname} ({ip}).")
            else:
                raise Exception(f"Server not responding on {ip}.")
        except requests.RequestException:
            try:
                # Attempt to start server.py via SSH in the background
                command = f"ssh cfinnerty@{ip} 'nohup python3 piCamControl/server.py &'"
                subprocess.Popen(command, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                messages.append(f"Started server on {ip}.")
            except Exception as e:
                errors.append(f"Error starting server on {ip}: {e}")
                success = False

    return jsonify({'success': success, 'message': messages, 'errors': errors})

@app.route('/stop_servers', methods=['POST'])
def stop_servers():
    """Stop server.py on each Raspberry Pi."""
    success = True
    messages = []
    errors = []

    for ip in raspberry_pi_ips:
        try:
            # Attempt to stop server.py via SSH
            command = f"ssh cfinnerty@{ip} 'pkill -f server.py'"
            subprocess.run(command, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            messages.append(f"Stopped server on {ip}.")
        except subprocess.CalledProcessError as e:
            errors.append(f"Error stopping server on {ip}: {e}")
            success = False

    return jsonify({'success': success, 'message': messages, 'errors': errors})

@app.route('/update_servers', methods=['POST'])
def update_servers():
    """Update the piCamControl repository on each Raspberry Pi."""
    success = True
    messages = []
    errors = []

    # Check if all servers are stopped
    for ip in raspberry_pi_ips:
        try:
            response = requests.get(f'http://{ip}:5000/hostname', timeout=5)
            if response.status_code == 200:
                errors.append(f"Server is still running on {ip}. Please stop all servers before updating.")
                success = False
                return jsonify({'success': success, 'message': messages, 'errors': errors})
        except requests.RequestException:
            # Server is not running, proceed with update
            pass

    # Perform git pull on each Raspberry Pi
    for ip in raspberry_pi_ips:
        try:
            command = f"ssh cfinnerty@{ip} 'cd piCamControl && git pull'"
            subprocess.run(command, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            messages.append(f"Updated repository on {ip}.")
        except subprocess.CalledProcessError as e:
            errors.append(f"Error updating repository on {ip}: {e}")
            success = False

    return jsonify({'success': success, 'message': messages, 'errors': errors})

@app.route('/take_photo', methods=['POST'])
def take_photo():
    """Trigger photo capture on all Raspberry Pis and handle responses."""
    success = True
    messages = []
    errors = []

    # Function to trigger photo capture on a single Raspberry Pi
    def capture_photo(ip):
        try:
            print(f"Triggering photo capture on {ip}...")
            response = requests.post(f'http://{ip}:5000/take_photo', timeout=10)
            response.raise_for_status()
            data = response.json()

            if data.get('success', False):
                print(f"Photo taken successfully on {ip}.")
                return None  # No error
            else:
                error_message = f"Error taking photo on {ip}: {data.get('error', 'Unknown error')}"
                print(error_message)
                return error_message
        except requests.RequestException as e:
            error_message = f"Error communicating with {ip}: {e}"
            print(error_message)
            return error_message

    # Use ThreadPoolExecutor to send requests concurrently
    with ThreadPoolExecutor() as executor:
        results = list(executor.map(capture_photo, raspberry_pi_ips))

    # Collect errors from the results
    errors = [result for result in results if result]
    if errors:
        success = False

    return jsonify({'success': success, 'message': messages, 'errors': errors})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)