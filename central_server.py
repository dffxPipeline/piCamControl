from flask import Flask, render_template, request, jsonify
import requests
import os
import socket

app = Flask(__name__)

# List of Raspberry Pi IP addresses
raspberry_pi_ips = [
    "192.168.48.115",
    "192.168.48.120",
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
    for ip in raspberry_pi_ips:
        try:
            response = requests.post(f'http://{ip}:5000/record', json={'action': action})
            response.raise_for_status()
        except requests.RequestException as e:
            print(f"Error sending record action to {ip}: {e}")
            success = False
    return jsonify({'success': success})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)