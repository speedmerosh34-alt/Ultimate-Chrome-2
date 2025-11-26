from flask import Flask, jsonify, request
from selenium.webdriver import Chrome, ChromeOptions
import threading
import time
import sys

app = Flask(__name__)

driver = None
init_lock = threading.Lock()
init_complete = threading.Event()
last_screenshot = None
last_screenshot_time = 0

HTML_CONTENT = '''<!DOCTYPE html>
<html>
<head>
    <title>Browser</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #000;
            display: flex;
            flex-direction: column;
            height: 100vh;
            overflow: hidden;
        }
        .toolbar {
            background: #222;
            padding: 12px 15px;
            display: flex;
            gap: 8px;
            align-items: center;
            border-bottom: 1px solid #444;
            flex-wrap: wrap;
        }
        .toolbar input {
            flex: 1;
            min-width: 300px;
            padding: 8px 12px;
            border: 1px solid #444;
            border-radius: 4px;
            background: #333;
            color: #fff;
            font-size: 14px;
        }
        .toolbar button {
            padding: 8px 16px;
            background: #0066cc;
            color: white;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-weight: 600;
            transition: background 0.2s;
        }
        .toolbar button:hover { background: #0052a3; }
        .toolbar button:active { background: #003d7a; }
        .info {
            color: #888;
            font-size: 13px;
            padding: 0 8px;
            white-space: nowrap;
        }
        .browser-container {
            flex: 1;
            overflow: auto;
            background: white;
            display: flex;
            align-items: center;
            justify-content: center;
            position: relative;
        }
        #screenshot {
            max-width: 100%;
            max-height: 100%;
            object-fit: contain;
            cursor: pointer;
            box-shadow: 0 2px 10px rgba(0,0,0,0.3);
        }
        .loading {
            color: #888;
            font-size: 14px;
        }
        .status-bar {
            background: #222;
            padding: 8px 15px;
            border-top: 1px solid #444;
            font-size: 12px;
            color: #888;
            display: flex;
            gap: 20px;
        }
        .status-item { display: flex; gap: 6px; align-items: center; }
        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #0f0;
        }
        .status-dot.error { background: #f00; }
    </style>
</head>
<body>
    <div class="toolbar">
        <input type="text" id="urlInput" placeholder="Enter URL..." value="https://google.com">
        <button onclick="navigateTo()">Go</button>
        <button onclick="refreshScreenshot()">Refresh</button>
        <span class="info" id="loadingIndicator">Loading...</span>
    </div>
    
    <div class="browser-container">
        <div id="content">
            <div class="loading">Initializing browser...</div>
        </div>
    </div>

    <div class="status-bar">
        <div class="status-item">
            <div class="status-dot" id="statusDot"></div>
            <span id="statusText">Connecting...</span>
        </div>
        <div class="status-item" id="urlStatus"></div>
    </div>

    <script>
        const urlInput = document.getElementById('urlInput');
        const content = document.getElementById('content');
        const loadingIndicator = document.getElementById('loadingIndicator');
        const statusText = document.getElementById('statusText');
        const statusDot = document.getElementById('statusDot');
        const urlStatus = document.getElementById('urlStatus');

        async function refreshScreenshot() {
            try {
                loadingIndicator.textContent = 'Capturing...';
                const response = await fetch('/api/screenshot');
                if (!response.ok) throw new Error('Capture failed');
                
                const data = await response.json();
                const img = document.createElement('img');
                img.id = 'screenshot';
                img.src = 'data:image/png;base64,' + data.screenshot;
                img.onclick = handleClick;
                
                content.innerHTML = '';
                content.appendChild(img);
                
                statusDot.classList.remove('error');
                statusText.textContent = '✓ Connected';
                urlStatus.textContent = data.url || '';
                urlInput.value = data.url || urlInput.value;
                loadingIndicator.textContent = 'Ready';
                
            } catch (e) {
                statusDot.classList.add('error');
                statusText.textContent = '✗ Error: ' + e.message;
                loadingIndicator.textContent = 'Error';
                content.innerHTML = `<div class="loading" style="color: #f00;">Error: ${e.message}</div>`;
            }
        }

        async function navigateTo() {
            const url = urlInput.value || 'https://google.com';
            try {
                loadingIndicator.textContent = 'Navigating...';
                const response = await fetch('/api/navigate', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url })
                });
                if (!response.ok) throw new Error('Navigation failed');
                
                await new Promise(r => setTimeout(r, 1200));
                await refreshScreenshot();
            } catch (e) {
                statusDot.classList.add('error');
                statusText.textContent = '✗ ' + e.message;
                loadingIndicator.textContent = 'Failed';
            }
        }

        async function handleClick(e) {
            const rect = e.target.getBoundingClientRect();
            const x = Math.round((e.clientX - rect.left) * (e.target.naturalWidth / rect.width));
            const y = Math.round((e.clientY - rect.top) * (e.target.naturalHeight / rect.height));
            
            try {
                await fetch('/api/click', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ x, y })
                });
                await new Promise(r => setTimeout(r, 600));
                await refreshScreenshot();
            } catch (e) {
                console.error('Click failed:', e);
            }
        }

        document.addEventListener('keypress', async (e) => {
            if (e.target === urlInput) {
                if (e.key === 'Enter') navigateTo();
                return;
            }
        });

        setInterval(refreshScreenshot, 2000);
        setTimeout(refreshScreenshot, 500);
    </script>
</body>
</html>'''

def init_browser(wait=False):
    global driver
    try:
        with init_lock:
            if driver is not None:
                return True
            
            print("Initializing Chrome browser...", file=sys.stderr, flush=True)
            chrome_options = ChromeOptions()
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--window-size=1920,1080')
            chrome_options.add_argument('--disable-extensions')
            chrome_options.add_argument('--disable-plugins')
            
            driver = Chrome(options=chrome_options)
            driver.set_page_load_timeout(15)
            driver.get('https://google.com')
            init_complete.set()
            print("Chrome browser ready!", file=sys.stderr, flush=True)
            return True
    except Exception as e:
        print(f"Init error: {e}", file=sys.stderr, flush=True)
        return False

def wait_for_browser(timeout=30):
    if not init_complete.wait(timeout=timeout):
        if not driver:
            init_browser()
    return driver is not None

@app.route('/')
def index():
    return HTML_CONTENT, 200, {'Content-Type': 'text/html; charset=utf-8'}

@app.route('/api/screenshot')
def screenshot():
    global driver, last_screenshot, last_screenshot_time
    try:
        if last_screenshot and (time.time() - last_screenshot_time) < 1:
            return jsonify(last_screenshot)
        
        if not driver:
            if not init_browser():
                return jsonify({'error': 'Browser init failed'}), 500
        
        try:
            screenshot_b64 = driver.get_screenshot_as_base64()
            url = driver.current_url
            title = driver.title
            
            result = {'screenshot': screenshot_b64, 'url': url, 'title': title}
            last_screenshot = result
            last_screenshot_time = time.time()
            
            return jsonify(result)
        except Exception as e:
            driver = None
            init_complete.clear()
            if init_browser():
                screenshot_b64 = driver.get_screenshot_as_base64()
                result = {'screenshot': screenshot_b64, 'url': driver.current_url, 'title': driver.title}
                return jsonify(result)
            return jsonify({'error': str(e)}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/navigate', methods=['POST'])
def navigate():
    global driver
    try:
        if not driver and not init_browser():
            return jsonify({'error': 'Browser not ready'}), 500
        
        url = request.json.get('url', 'https://google.com')
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        try:
            driver.get(url)
            return jsonify({'status': 'ok', 'url': driver.current_url})
        except Exception as e:
            driver = None
            return jsonify({'error': str(e)}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/click', methods=['POST'])
def click():
    global driver
    try:
        if not driver:
            return jsonify({'error': 'Browser not ready'}), 500
        
        x = request.json.get('x', 0)
        y = request.json.get('y', 0)
        
        driver.execute_script(f"""
            try {{
                var element = document.elementFromPoint({x}, {y});
                if (element) element.click();
            }} catch(e) {{}}
        """)
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/type', methods=['POST'])
def type_text():
    global driver
    try:
        if not driver:
            return jsonify({'error': 'Browser not ready'}), 500
        
        text = request.json.get('text', '')
        driver.switch_to.active_element.send_keys(text)
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.after_request
def add_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = '*'
    response.headers['Connection'] = 'close'
    return response

if __name__ == '__main__':
    threading.Thread(target=init_browser, daemon=True).start()
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True, use_reloader=False)
