"""Compile editable millimetre master documents into the existing layout format."""
from copy import deepcopy
import math
from .layout_engine import canonical_hash


def geometry(count, layer):
    best = None
    for cols in range(1, min(6, count) + 1):
        rows = math.ceil(count / cols)
        cw = (layer['box']['w'] - (cols-1)*layer['gap']) / cols
        ch = (layer['box']['h'] - (rows-1)*layer['gap']) / rows
        pw = min(cw*.86, (ch-layer['fontSize']*.3528*2.5-7)*.75, 85)
        if pw < layer['minPhotoWidth']:
            continue
        score = pw*pw*count - (cols*rows-count)*pw*.01
        if best is None or score > best[0]:
            best = (score, cols, cw, ch, pw)
    return best


def pages_for(section, master, snapshot, owner, issue):
    pages = [p for s in section['spreads'] for p in s['pages']]
    if section['kind'] == 'repeat':
        records = snapshot['students'] if master['personalMode'] == 'all' else [owner] if master['personalMode'] == 'owner' else []
        return [(p, person, None, 0) for person in records for p in pages]
    grids = [p for p in pages if any(l['type']=='grid' for l in p['layers'])]
    if not grids:
        return [(p, None, None, 0) for p in pages]
    settings = next(l for l in grids[0]['layers'] if l['type']=='grid')
    records = snapshot[settings['source']][:]
    if settings['source']=='teachers' and settings.get('excludeLead') and any(l['type']=='photo' and not l.get('hidden') and l['source']=='lead' for p in pages for l in p['layers']):
        records = records[1:]
    # Every page template must accommodate every balanced part.
    all_settings = [l for p in grids for l in p['layers'] if l['type']=='grid']
    capacity = min(max((n for n in range(1, int(l['max'])+1) if geometry(n,l)), default=0) for l in all_settings)
    if not capacity:
        issue('error', section['id'], 'Виньетки не помещаются в область. Увеличьте область или уменьшите фото.')
        return [(p,None,[],0) for p in pages]
    preferred = max(1,int(section.get('target', len(section['spreads'])))*2-(len(pages)-len(grids)))
    n = len(records)
    slots = max(math.ceil(n/capacity), min(preferred,max(1,n//int(settings['min'])))) if n else 1
    counts = [n//slots+(i<n%slots) for i in range(slots)]
    if n and min(counts)<settings['min']:
        issue('error' if settings.get('strictMin') else 'warning',section['id'],'Карточек на странице меньше заданного минимума')
    chunks, offset = [], 0
    for count in counts:
        chunks.append(records[offset:offset+count]); offset += count
    result, used, insert_at = [], 0, 0
    for p in pages:
        if p not in grids:
            result.append((p,None,None,0))
        elif used < slots:
            result.append((p,None,chunks[used],max(counts))); used += 1; insert_at = len(result)
    while used < slots:
        result.insert(insert_at,(grids[-1],None,chunks[used],max(counts))); used += 1; insert_at += 1
    return result


def generate(edition, snapshot, measurer, overrides=()):
    master = edition['master']
    issues, variants, groups, plans = [], [], {}, []
    seen = set()
    def issue(level, key, message):
        if (level,key,message) not in seen:
            seen.add((level,key,message)); issues.append({'level':level,'code':'master','key':key,'message':message})
    students = snapshot['students']
    owners = students or [{'id':'class','first_name':'Общий','last_name':'альбом'}]
    selections = {(s['owner'],s['role']):s['photo'] for s in snapshot['selections']}
    general = snapshot.get('general_photos', [])
    def name(person):
        return ' '.join(str(person.get(k,'')) for k in ('first_name','last_name')).strip() if person else ''
    def photo_for(person):
        if not person:
            return None
        return selections.get(('student:'+person['id'],'main_portrait')) or selections.get(('teacher:'+person['id'],'main_portrait'))
    def crop(photo, b, x=50, y=50):
        meta = snapshot['photos'][photo]; w,h=meta['width'],meta['height']; ratio=b[2]/b[3]
        cw,ch = (h*ratio,h) if w/h>ratio else (w,w/ratio)
        return [(w-cw)*x/100,(h-ch)*y/100,cw,ch]
    applied, conflicts = [], []
    overrides_by_key = {o['key']:o for o in overrides}
    found = set()
    for owner in owners:
        owner_key = 'student:'+owner['id']; group = {}; sequence=[]; general_index=0
        for section in master['sections']:
            pages = pages_for(section,master,snapshot,owner,issue)
            if len(pages)%2:
                pages.append((None,None,None,0))
            if len(pages)>2000:
                raise ValueError('Раздел превышает 1000 разворотов')
            if owner is owners[0]:
                plans.append({'section':section['id'],'spreads':len(pages)//2})
            for index in range(0,len(pages),2):
                spread_key=f'{section["id"]}[{owner_key}]:{index//2}'
                sequence.append(spread_key); elements=[]; appearance={}
                def add(e):
                    e.update(appearance)
                    e.setdefault('hidden',False); e['base']=canonical_hash(e)
                    override=overrides_by_key.get(e['key'])
                    if override:
                        found.add(e['key'])
                        if override.get('base')==e['base'] and override['type']==e['type']:
                            if e['type']=='text': e['text']=override['value']
                            elif override['value'] in snapshot['photos']:
                                e['photo']=override['value']; e['crop']=crop(e['photo'],e['box'])
                            applied.append(e['key'])
                        else:
                            conflicts.append({'key':e['key'],'reason':'Исходный элемент изменился'})
                    if e['type']=='photo' and not e['photo']:
                        issue('error',e['key'],'Не выбрано обязательное фото')
                    if e['type']=='text' and measurer.height(e['text'],e['font'],e['size'],e['leading'],e['box'][2]) > e['box'][3]+.1:
                        issue('error',e['key'],'Текст выходит за границы рамки')
                    elements.append(e)
                for side,(page, item, records, layout_count) in enumerate(pages[index:index+2]):
                    if page is None: continue
                    appearance={}
                    prefix=f'{spread_key}/{side}'
                    add({'key':prefix+'/background','type':'rect','box':[side*210,0,210,280],'fill':page['background']})
                    lead = snapshot['teachers'][0] if snapshot['teachers'] else None
                    for layer in page['layers']:
                        if layer.get('hidden'): continue
                        b=layer['box']; bounds=[b['x']+side*210,b['y'],b['w'],b['h']]; key=prefix+'/'+layer['id']
                        common={'key':key,'box':bounds,'opacity':layer.get('opacity',100)}
                        appearance={'angle':layer.get('angle',0),'rotation_center':[bounds[0]+bounds[2]/2,bounds[1]+bounds[3]/2], 'radius':layer.get('radius',0),'stroke':layer.get('stroke','#333333'),'strokeWidth':layer.get('strokeWidth',0)}
                        font={'Georgia':'display','Arial':'main','Times New Roman':'times'}.get(layer.get('font'),'main')
                        def text_element(key, bounds, value, size):
                            return {'key':key,'type':'text','box':bounds,'text':value,'font':font,'size':size,'leading':size*1.25,'align':layer.get('align','center'),'valign':'top','color':layer['color'],'opacity':layer.get('opacity',100)}
                        def photo_element(key,bounds,photo):
                            return {'key':key,'type':'photo','box':bounds,'photo':photo,'crop':crop(photo,bounds,layer.get('cropX',50),layer.get('cropY',50)) if photo else None,'mask':'rect','required':True,'opacity':layer.get('opacity',100)}
                        if layer['type']=='text':
                            binding=layer.get('binding','static')
                            value={'owner.name':name(owner),'item.name':name(item),'lead.name':name(lead),'class':snapshot['order']['class_name'],'year':snapshot['order']['year']}.get(binding,layer['text'])
                            add({**text_element(key,bounds,value,layer['fontSize']),'valign':'middle'})
                        elif layer['type']=='photo':
                            source=layer['source']
                            if source=='class':
                                photo=general[general_index%len(general)] if general else None; general_index+=1
                            elif source=='custom': photo=snapshot.get('master_assets',{}).get(layer['id'])
                            else: photo=photo_for({'owner':owner,'item':item,'lead':lead}.get(source))
                            add(photo_element(key,bounds,photo))
                        elif layer['type']=='grid':
                            if not records: continue
                            geo=geometry(layout_count,layer)
                            if not geo:
                                issue('error',key,'Виньетки не помещаются'); continue
                            _,cols,cw,ch,pw=geo
                            size=layer['fontSize']
                            # Shared reduction for the complete source, not individual cards.
                            all_people=snapshot[layer['source']]
                            while size>layer['minFontSize'] and any(measurer.height(name(p),font,size,size*1.25,cw*.97)>size*.3528*2.5+.1 for p in all_people): size=max(layer['minFontSize'],size-.5)
                            for i,person in enumerate(records):
                                x=bounds[0]+(i%cols)*(cw+layer['gap']); y=bounds[1]+(i//cols)*(ch+layer['gap'])
                                pk=key+'/card['+('student:' if layer['source']=='students' else 'teacher:')+person['id']+']'
                                add(photo_element(pk+'/photo',[x+(cw-pw)/2,y,pw,pw/.75],photo_for(person)))
                                add(text_element(pk+'/name',[x,y+pw/.75+3,cw,ch-pw/.75-3],name(person),size))
                        else:
                            add({**common,'type':layer['type'],'fill':layer['fill']})
                group[spread_key]={'key':spread_key,'section':section['id'],'elements':elements}
        groups[owner_key]=group
        variants.append({'owner':owner_key,'name':name(owner),'kind':'student','sequence':sequence})
    for key in overrides_by_key.keys()-found:
        conflicts.append({'key':key,'reason':'Элемент отсутствует в новой генерации'})
    count=len(variants[0]['sequence'])
    document={'schema_version':1,'master_template':True,'edition':{'id':edition['id'],'version':edition['version']},'input_hash':canonical_hash(snapshot),'spread_count':count,'page_count':count*2,'spread_size_mm':[420,280],'cover_size_mm':[420,280],'covers':{},'shared_spreads':{},'variant_spreads':groups,'variants':variants,'plan':plans,'issues':issues,'overrides':{'applied':applied,'conflicts':conflicts}}
    document['revision']=canonical_hash(document)
    return document
