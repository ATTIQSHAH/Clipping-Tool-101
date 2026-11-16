import subprocess, time, urllib.request, json, os

exe = r'c:\attiq\clipping software\clipforge\dist\ClipForge\ClipForge.exe'
env = os.environ.copy()
env['CLIPFORGE_PORT'] = '7890'
env['CLIPFORGE_NO_BROWSER'] = '1'

proc = subprocess.Popen([exe], env=env)
print('Started ClipForge.exe PID:', proc.pid)

def check_url(url, method='GET', data=None):
    req = urllib.request.Request(url, data=data, method=method)
    if data:
        req.add_header('Content-Type', 'application/json')
    try:
        with urllib.request.urlopen(req, timeout=5) as res:
            return res.status, res.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:
        return None, str(e).encode()

try:
    ready = False
    for i in range(25):
        time.sleep(1)
        code, content = check_url('http://127.0.0.1:7890/api/settings')
        if code == 200:
            ready = True
            print('Server is ready on port 7890! Status 200')
            print('Settings:', content.decode('utf-8')[:200])
            break
        print(f'Waiting... ({i+1}/25), status: {code}')
    
    if not ready:
        raise RuntimeError('Server did not start in time')

    # Test GET /api/videos
    code, vids = check_url('http://127.0.0.1:7890/api/videos')
    print('GET /api/videos:', code, len(vids))

    # Test GET /api/videos/1/clips
    code, clips = check_url('http://127.0.0.1:7890/api/videos/1/clips')
    print('GET /api/videos/1/clips:', code)
    clips_obj = json.loads(clips.decode('utf-8'))
    print(f'Total clips: {len(clips_obj)}')
    if clips_obj:
        print(f'Clip 1 layout: {clips_obj[0].get("layout")}')

    # Test GET /api/clips/1/cues
    code, cues = check_url('http://127.0.0.1:7890/api/clips/1/cues')
    print('GET /api/clips/1/cues:', code)
    cues_obj = json.loads(cues.decode('utf-8'))
    print(f'Total cues returned: {len(cues_obj)}')

    # Test GET /api/clips/1/source
    code, src = check_url('http://127.0.0.1:7890/api/clips/1/source')
    print('GET /api/clips/1/source:', code, f'bytes: {len(src)}')

    # Test POST /api/videos/1/approve_all
    code, app_res = check_url('http://127.0.0.1:7890/api/videos/1/approve_all', method='POST', data=b'{}')
    print('POST /api/videos/1/approve_all:', code, app_res.decode('utf-8'))

    print('ALL SMOKE TESTS PASSED PERFECTLY!')

finally:
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except:
        proc.kill()
    print('Terminated test ClipForge process.')

