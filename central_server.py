from flask import Flask, render_template, request, jsonify
import requests
import os
import socket

app = Flask(__name__)

# List of Raspberry Pi IP addresses
raspberry_pi_ips = [
    #"192.168.10.111",
    #"192.168.10.112",
    #"192.168.10.113",
    #"192.168.10.114",
    #"192.168.10.115",
    #"192.168.10.116",
    #"192.168.10.121",
    #"192.168.10.122",
    #"192.168.10.123",
    #"192.168.10.124",
    #"192.168.10.125",
    #"192.168.10.126",
    #"192.168.10.131",
    #"192.168.10.132",
    #"192.168.10.133",
    #"192.168.10.134",
    #"192.168.10.135",
    #"192.168.10.136",
    #"192.168.10.141",
    #"192.168.10.142",
    #"192.168.10.143",
    #"192.168.10.144",
    #"192.168.10.145",
    #"192.168.10.146",
    #"192.168.10.151",
    #"192.168.10.152",
    #"192.168.10.153",
    #"192.168.10.154",
    #"192.168.10.155",
    #"192.168.10.156",
    #"192.168.10.161",
    #"192.168.10.162",
    #"192.168.10.163",
    #"192.168.10.164",
    #"192.168.10.165",
    #"192.168.10.166",
    #"192.168.10.171",
    #"192.168.10.172",
    #"192.168.10.173",
    #"192.168.10.174",
    #"192.168.10.175",
    #"192.168.10.176",
    #"192.168.10.181",
    #"192.168.10.182",
    #"192.168.10.183",
    #"192.168.10.184",
    #"192.168.10.185",
    #"192.168.10.186",
    #"192.168.10.191",
    #"192.168.10.192",
    #"192.168.10.193",
    #"192.168.10.194",
    #"192.168.10.195",
    #"192.168.10.196",
    "192.168.48.115",
    "192.168.48.120"
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
    servos_status = get_servos_status()
    hostnames = get_hostnames()
    return render_template('index.html', raspberry_pi_ips=raspberry_pi_ips, servos_status=servos_status, hostnames=hostnames)

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
        # Step 1: Stop recording on all Raspberry Pis
        for ip in raspberry_pi_ips:
            try:
                response = requests.post(f'http://{ip}:5000/record', json={'action': 'stop_recording'})
                response.raise_for_status()
                if not response.json().get('success', False):
                    raise Exception(response.json().get('error', 'Unknown error'))
            except requests.RequestException as e:
                print(f"Error stopping recording on {ip}: {e}")
                success = False
                errors.append(f"Error stopping recording on {ip}: {e}")

        # Step 2: Transfer video files to the central server and delete them
        for ip in raspberry_pi_ips:
            try:
                response = requests.post(f'http://{ip}:5000/record', json={'action': 'transfer_video'})
                response.raise_for_status()
                if not response.json().get('success', False):
                    raise Exception(response.json().get('error', 'Unknown error'))
            except requests.RequestException as e:
                print(f"Error transferring video from {ip}: {e}")
                success = False
                errors.append(f"Error transferring video from {ip}: {e}")

    else:
        # Start recording on all Raspberry Pis
        for ip in raspberry_pi_ips:
            try:
                response = requests.post(f'http://{ip}:5000/record', json={'action': action})
                response.raise_for_status()
                if not response.json().get('success', False):
                    raise Exception(response.json().get('error', 'Unknown error'))
            except requests.RequestException as e:
                print(f"Error starting recording on {ip}: {e}")
                success = False
                errors.append(f"Error starting recording on {ip}: {e}")

    return jsonify({'success': success, 'errors': errors})

@app.route('/manage_servers', methods=['POST'])
def manage_servers():
    """Start or restart server.py on each Raspberry Pi."""
    success = True
    messages = []
    errors = []

    for ip in raspberry_pi_ips:
        try:
            # Check if server.py is running
            response = requests.get(f'http://{ip}:5000/hostname', timeout=5)
            if response.status_code == 200:
                # Restart server.py
                restart_response = requests.post(f'http://{ip}:5000/control', json={'action': 'restart_server'})
                if restart_response.status_code == 200:
                    hostname = response.json().get('hostname', 'Unknown')
                    messages.append(f"Restarted server on {hostname} ({ip}).")
                else:
                    raise Exception(f"Failed to restart server on {ip}.")
            else:
                raise Exception(f"Server not responding on {ip}.")
        except requests.RequestException:
            try:
                # Attempt to start server.py via SSH
                hostname = socket.gethostbyaddr(ip)[0]
                os.system(f"ssh cfinnerty@{ip} 'python3 piCamControl/server.py &'")
                messages.append(f"Started server on {hostname} ({ip}).")
            except Exception as e:
                errors.append(f"Error starting server on {ip}: {e}")
                success = False

    return jsonify({'success': success, 'message': messages, 'errors': errors})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)