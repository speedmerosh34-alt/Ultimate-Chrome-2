from flask import Flask, render_template, jsonify, request
import subprocess
import os
import base64

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('browser.html')

@app.route('/screenshot')
def screenshot():
    # Minimal screenshot endpoint
    return jsonify({'data': '', 'status': 'ok'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
