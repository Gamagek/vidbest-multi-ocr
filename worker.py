import argparse, base64, json, os, pathlib, re, subprocess, time, urllib.request, urllib.error
from urllib.parse import quote
ROOT=pathlib.Path('/data'); INPUT=ROOT/'input'; OUTPUT=ROOT/'output'
def run(cmd):
    return subprocess.run(cmd,check=True,capture_output=True,text=True,timeout=180).stdout

def gemini(frame):
    if os.getenv('ENABLE_GEMINI','false').lower()!='true': return {'status':'disabled'}
    key=os.getenv('GEMINI_API_KEY','')
    if not key: return {'status':'no_api_key'}
    preferred=[m.strip().removeprefix('models/') for m in os.getenv('GEMINI_MODELS','gemini-3.5-flash,gemini-3.8-flash').split(',') if m.strip()]
    payload={'contents':[{'parts':[{'text':'Describe only directly visible elements in this video frame. Transcribe all readable on-screen text exactly; distinguish uncertain text. Return concise factual observations, no invented context.'},{'inline_data':{'mime_type':'image/jpeg','data':base64.b64encode(frame.read_bytes()).decode()}}]}], 'generationConfig':{'temperature':0.1,'maxOutputTokens':500}}
    def request(url, data=None):
        req=urllib.request.Request(url,data=data,headers={'Content-Type':'application/json','x-goog-api-key':key},method='POST' if data else 'GET')
        with urllib.request.urlopen(req,timeout=50) as res: return json.load(res)
    try:
        available=set(); page='https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000'
        for _ in range(5):
            catalog=request(page)
            available.update(m['name'].removeprefix('models/') for m in catalog.get('models',[]) if 'generateContent' in m.get('supportedGenerationMethods',[]))
            token=catalog.get('nextPageToken')
            if not token: break
            page='https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000&pageToken='+quote(token)
    except Exception as e:
        return {'status':'discovery_error','message':str(e)}
    candidates=[m for m in preferred if m in available]
    if not candidates:
        return {'status':'models_unavailable','requested':preferred,'available_flash':[m for m in sorted(available) if 'flash' in m][:30]}
    errors=[]
    for model in candidates:
        url=f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'
        for attempt in range(2):
            try:
                obj=request(url,json.dumps(payload).encode())
                output=' '.join(p.get('text','') for c in obj.get('candidates',[]) for p in c.get('content',{}).get('parts',[]))
                if output.strip():return {'status':'ok','model':model,'text':output}
                errors.append({'model':model,'error':'empty_response'});break
            except urllib.error.HTTPError as e:
                errors.append({'model':model,'code':e.code,'message':e.read(300).decode(errors='replace')})
                if e.code in (429,500,502,503,504) and attempt==0:
                    time.sleep(3);continue
                break
            except Exception as e:
                errors.append({'model':model,'message':str(e)});break
    return {'status':'all_models_failed','errors':errors}

def vision(frame):
    """Optional OpenAI-compatible remote VLM; never sends frames unless enabled."""
    if os.getenv('ENABLE_VISION','false').lower()!='true':
        return {'status':'disabled'}
    endpoint=os.getenv('VISION_API_URL','').strip()
    model=os.getenv('VISION_MODEL','Qwen/Qwen3-VL-8B-Instruct').strip()
    if not endpoint.startswith('https://'):
        return {'status':'configuration_error','message':'VISION_API_URL must be HTTPS'}
    if not endpoint.endswith('/chat/completions'):
        return {'status':'configuration_error','message':'Expected an OpenAI-compatible /chat/completions URL'}
    if not model:
        return {'status':'configuration_error','message':'VISION_MODEL missing'}
    key=os.getenv('VISION_API_KEY','').strip()
    data=base64.b64encode(frame.read_bytes()).decode('ascii')
    prompt=('Describe only visible people, objects, actions and setting in this single frame. '
            'Transcribe readable text exactly. Mark uncertainty. Do not infer unseen events.')
    payload={'model':model,'temperature':0.1,'max_tokens':450,'messages':[{'role':'user','content':[
        {'type':'text','text':prompt},
        {'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+data}}
    ]}]}
    headers={'Content-Type':'application/json'}
    if key:headers['Authorization']='Bearer '+key
    try:
        req=urllib.request.Request(endpoint,data=json.dumps(payload).encode(),headers=headers,method='POST')
        with urllib.request.urlopen(req,timeout=65) as resp: result=json.load(resp)
        msg=result.get('choices',[{}])[0].get('message',{}).get('content','')
        if isinstance(msg,list):
            msg=' '.join(x.get('text','') for x in msg if isinstance(x,dict))
        return {'status':'ok','model':model,'text':str(msg)} if msg else {'status':'empty_response'}
    except urllib.error.HTTPError as e:
        return {'status':'http_error','code':e.code,'message':e.read(250).decode(errors='replace')}
    except Exception as e:
        return {'status':'request_error','message':str(e)[:250]}

def scene_times(video):
    """Detect likely shot boundaries; this does not identify semantic events."""
    threshold=max(0.1,min(0.8,float(os.getenv('SCENE_THRESHOLD','0.35'))))
    limit=max(1,min(24,int(os.getenv('MAX_SCENE_CUTS','12'))))
    cmd=['ffmpeg','-hide_banner','-nostdin','-threads','1','-i',str(video),
         '-vf',f"select=gt(scene\\,{threshold}),showinfo",'-an','-f','null','-']
    try:
        p=subprocess.run(cmd,capture_output=True,text=True,timeout=180)
        times=[float(x) for x in re.findall(r'pts_time:([0-9.]+)',p.stderr)]
        return sorted(set(round(t,2) for t in times))[:limit]
    except Exception:
        return []

def process(video):
    out=OUTPUT/video.stem; out.mkdir(parents=True,exist_ok=True)
    frames=out/'frames'; frames.mkdir(exist_ok=True)
    interval=max(1,int(os.getenv('FRAME_INTERVAL','5')))
    count=max(1,min(30,int(os.getenv('MAX_FRAMES','12'))))
    run(['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-threads','1','-y','-i',str(video),'-vf',f'fps=1/{interval},scale=480:-2','-frames:v',str(count),'-q:v','6',str(frames/'frame_%03d.jpg')])
    cuts=scene_times(video) if os.getenv('ENABLE_SCENE_DETECTION','true').lower()=='true' else []
    observations=[]
    for i,frame in enumerate(sorted(frames.glob('frame_*.jpg'))):
        try: local=run(['tesseract',str(frame),'stdout','-l',os.getenv('OCR_LANG','eng+sin')]).strip()
        except Exception as e: local=f'[tesseract error: {e}]'
        observations.append({'frame':frame.name,'approx_seconds':i*interval,'tesseract':local,'gemini':gemini(frame),'vision':vision(frame)})
        (out/'evidence.json').write_text(json.dumps({'source':video.name,'frames':observations,'scene_cut_seconds':cuts,'scene_cut_note':'Visual shot boundaries only, not semantic action recognition.','verified':False,'note':'Frame evidence only; not full video understanding or editorial approval.'},ensure_ascii=False,indent=2))
        time.sleep(1)
    (out/'done.flag').write_text('complete')
    print('Processed',video.name,flush=True)

def main(watch):
    INPUT.mkdir(parents=True,exist_ok=True); OUTPUT.mkdir(parents=True,exist_ok=True)
    while True:
        for video in sorted(INPUT.iterdir()):
            if video.suffix.lower() not in ('.mp4','.mov','.mkv','.webm'):continue
            if (OUTPUT/video.stem/'done.flag').exists():continue
            try:process(video)
            except Exception as e:print('ERROR',video.name,str(e),flush=True)
        if not watch:break
        time.sleep(60)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--watch',action='store_true');a=p.parse_args();main(a.watch)
