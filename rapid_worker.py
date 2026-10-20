import json, pathlib
from rapidocr import RapidOCR
root=pathlib.Path('/data/output')
engine=RapidOCR()
for evidence in root.glob('*/evidence.json'):
    obj=json.loads(evidence.read_text()); changed=False
    for frame in obj['frames']:
        if 'rapidocr' in frame:continue
        image=evidence.parent/'frames'/frame['frame']
        try:
            result=engine(str(image))
            lines=getattr(result,'txts',None)
            frame['rapidocr']={'status':'ok','text':list(lines) if lines is not None else []}
        except Exception as e:frame['rapidocr']={'status':'error','message':str(e)}
        changed=True
    if changed:evidence.write_text(json.dumps(obj,ensure_ascii=False,indent=2))
