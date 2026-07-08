import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pyngrok import ngrok
from app import app
from database import init_db


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception:
        return '127.0.0.1'


def start_cloudflare_tunnel(local_port):
    try:
        proc = subprocess.Popen(
            ['cloudflared', 'tunnel', '--url', f'http://localhost:{local_port}'],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError:
        return None, 'cloudflared binary not found. Install cloudflared and make sure it is on PATH.'
    except Exception as e:
        return None, str(e)

    url = {'value': None}

    def monitor_output():
        try:
            for line in proc.stdout:
                if not line:
                    continue
                stripped = line.strip()
                print(stripped)
                if 'https://' in stripped and 'trycloudflare.com' in stripped:
                    url['value'] = stripped
                    break
        except Exception:
            pass

    thread = threading.Thread(target=monitor_output, daemon=True)
    thread.start()

    timeout = 20
    for _ in range(timeout):
        time.sleep(0.5)
        if url['value']:
            return proc, url['value']
        if proc.poll() is not None:
            break

    if url['value']:
        return proc, url['value']

    proc.terminate()
    return None, 'Cloudflare tunnel did not start or did not return a URL in time.'


def start_ngrok_tunnel(port):
    try:
        public_url = ngrok.connect(port, bind_tls=True).public_url
        return public_url, None
    except Exception as e:
        return None, str(e)


def print_local_urls():
    local_ip = get_local_ip()
    network_url = f'http://{local_ip}:5000'
    print('\nLocal access URLs:')
    print(f'  Local:   http://127.0.0.1:5000')
    print(f'  Network: {network_url}')
    print('Make sure your phone is on the same Wi-Fi network as this computer.')
    return network_url


if __name__ == '__main__':
    init_db()
    print('Starting public Flask server on port 5000...')

    provider = 'ngrok'
    open_network = False

    args = [arg.lower() for arg in sys.argv[1:]]
    for arg in args:
        if arg == 'cloudflare':
            provider = 'cloudflare'
        elif arg == 'ngrok':
            provider = 'ngrok'
        elif arg in ('--open-network', '--open'):
            open_network = True

    network_url = print_local_urls()
    if open_network:
        print(f'Opening network URL in browser: {network_url}')
        try:
            webbrowser.open(network_url)
        except Exception as e:
            print(f'Failed to open browser: {e}')

    cloudflare_proc = None
    if provider in ('auto', 'ngrok'):
        public_url, error = start_ngrok_tunnel(5000)
        if public_url:
            print(f'\nPublic URL: {public_url}')
            print('Share this URL with students and open it on phones or PCs.')
        else:
            print('\nUnable to start ngrok tunnel:')
            print(error)
            print('Switching to Cloudflare Tunnel...')
            cloudflare_proc, cf_url = start_cloudflare_tunnel(5000)
            if cf_url:
                print(f'\nCloudflare URL: {cf_url}')
                print('Share this URL with students and open it on phones or PCs.')
            else:
                print('\nCloudflare fallback failed:')
                print(cf_url)
                print_local_urls()
    else:
        cloudflare_proc, cf_url = start_cloudflare_tunnel(5000)
        if cf_url:
            print(f'\nCloudflare URL: {cf_url}')
            print('Share this URL with students and open it on phones or PCs.')
        else:
            print('\nUnable to start Cloudflare tunnel:')
            print(cf_url)
            print_local_urls()

    app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=False)
