from flask import Flask, render_template
#import board
#import busio
#from adafruit_pca9685 import PCA9685
import requests

app = Flask(__name__)

# List of Raspberry Pi IP addresses
raspberry_pi_ips = [
    "192.168.48.115",
    "192.168.48.120",
    # Add all other IP addresses here
]

import random

def get_servos_status():
    try:
        # Choose a random Raspberry Pi IP address
        server_ip = random.choice(raspberry_pi_ips)
        response = requests.get(f'http://{server_ip}:5000/servos_status')
        response.raise_for_status()
        data = response.json()
        return data.get("servos_found", False)
    except requests.RequestException as e:
        print(f"Error getting servos status: {e}")
        return False

# Example usage
servos_found = get_servos_status()
print(f"Servos found: {servos_found}")

@app.route('/')
def index():
    """Render HTML page with all camera feeds."""
    return render_template('index.html', raspberry_pi_ips=raspberry_pi_ips, servos_found=servos_found)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)