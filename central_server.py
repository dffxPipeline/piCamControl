from flask import Flask, render_template

app = Flask(__name__)

# List of Raspberry Pi IP addresses
raspberry_pi_ips = [
    "192.168.48.115",
    "192.168.48.120",
    # Add all other IP addresses here
]

@app.route('/')
def index():
    """Render HTML page with all camera feeds."""
    return render_template('index.html', raspberry_pi_ips=raspberry_pi_ips)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)