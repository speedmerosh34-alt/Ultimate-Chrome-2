import nest_asyncio
nest_asyncio.apply()

from flask import Flask, jsonify, request
from pyppeteer import launch
import asyncio
import base64
import sys
import io
from PIL import Image
import threading

app = Flask(__name__)

browser = None
page = None
loop = None
lock = threading.Lock()
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
                img.src = 'data:image/jpeg;base64,' + data.screenshot;
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
                
                await new Promise(r => setTimeout(r, 800));
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
                await new Promise(r => setTimeout(r, 400));
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

        setInterval(refreshScreenshot, 1000);
        setTimeout(refreshScreenshot, 300);
    </script>
</body>
</html>'''

def get_event_loop():
    global loop
    with lock:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop

async def init_browser_async():
    global browser, page
    try:
        if browser is not None and page is not None:
            return True
        print("Initializing browser with pyppeteer...", file=sys.stderr, flush=True)
        browser = await launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu', '--single-process'], autoClose=False)
        page = await browser.newPage()
        await page.setViewport({'width': 1280, 'height': 720})
        await page.goto('https://google.com', {'waitUntil': 'load', 'timeout': 10000})
        print("Browser ready!", file=sys.stderr, flush=True)
        return True
    except Exception as e:
        print(f"Init error: {e}", file=sys.stderr, flush=True)
        browser = None
        page = None
        return False

def init_browser():
    loop = get_event_loop()
    return loop.run_until_complete(init_browser_async())

def compress_screenshot(screenshot_data, quality=75):
    try:
        img = Image.open(io.BytesIO(screenshot_data))
        buffer = io.BytesIO()
        img.save(buffer, format='JPEG', quality=quality, optimize=True)
        return base64.b64encode(buffer.getvalue()).decode('utf-8')
    except:
        return base64.b64encode(screenshot_data).decode('utf-8')

@app.route('/')
def index():
    return HTML_CONTENT, 200, {'Content-Type': 'text/html; charset=utf-8'}

@app.route('/api/screenshot')
def screenshot():
    global page, last_screenshot, last_screenshot_time
    try:
        import time
        now = time.time()
        if last_screenshot and (now - last_screenshot_time) < 0.5:
            return jsonify(last_screenshot)
        
        with lock:
            if not page:
                if not init_browser():
                    return jsonify({'error': 'Browser init failed'}), 500
            
            loop = get_event_loop()
            screenshot_data = loop.run_until_complete(page.screenshot({'type': 'png'}))
            screenshot_b64 = compress_screenshot(screenshot_data, quality=70)
            url = page.url
        
        result = {'screenshot': screenshot_b64, 'url': url, 'title': 'Browser'}
        last_screenshot = result
        last_screenshot_time = now
        return jsonify(result)
    except Exception as e:
        print(f"Screenshot error: {e}", file=sys.stderr, flush=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/navigate', methods=['POST'])
def navigate():
    global page
    try:
        with lock:
            if not page:
                if not init_browser():
                    return jsonify({'error': 'Browser not ready'}), 500
            
            url = request.json.get('url', 'https://google.com')
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url
            
            loop = get_event_loop()
            loop.run_until_complete(page.goto(url, {'waitUntil': 'load', 'timeout': 15000}))
            return jsonify({'status': 'ok', 'url': page.url})
    except Exception as e:
        print(f"Navigate error: {e}", file=sys.stderr, flush=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/click', methods=['POST'])
def click():
    global page
    try:
        with lock:
            if not page:
                return jsonify({'error': 'Browser not ready'}), 500
            
            x = request.json.get('x', 0)
            y = request.json.get('y', 0)
            
            loop = get_event_loop()
            loop.run_until_complete(page.click({'x': x, 'y': y}))
        return jsonify({'status': 'ok'})
    except Exception as e:
        print(f"Click error: {e}", file=sys.stderr, flush=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/type', methods=['POST'])
def type_text():
    global page
    try:
        with lock:
            if not page:
                return jsonify({'error': 'Browser not ready'}), 500
            
            text = request.json.get('text', '')
            loop = get_event_loop()
            loop.run_until_complete(page.type(text))
        return jsonify({'status': 'ok'})
    except Exception as e:
        print(f"Type error: {e}", file=sys.stderr, flush=True)
        return jsonify({'error': str(e)}), 500

@app.after_request
def add_headers(response):
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = '*'
    response.headers['Connection'] = 'close'
    return response

if __name__ == '__main__':
    init_browser()
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True, use_reloader=False)
