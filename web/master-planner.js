window.MasterPlanner=function(documentModel,view){
let planning=[];
  const TEACHERS = ['Елена Александровна Морозова','Андрей Сергеевич Волков','Ольга Викторовна Соколова','Ирина Павловна Белова','Михаил Юрьевич Орлов','Наталья Олеговна Миронова','Анна Игоревна Крылова','Сергей Петрович Зайцев','Мария Андреевна Лебедева','Дмитрий Алексеевич Попов'];
  const STUDENTS = ['Анна Соколова','Михаил Волков','София Миронова','Александр Орлов','Мария Белова','Иван Лебедев','Полина Крылова','Артём Зайцев','Дарья Попова','Даниил Морозов','Елизавета Иванова','Максим Петров'];
  const SUBJECTS = ['Классный руководитель','Математика','Русский язык','История','Физика','Биология','Литература','География','Английский язык','Информатика'];
  const getSection = key => documentModel.sections.find(section=>section.id===key);
  const getTemplatePage = pageId => documentModel.sections.flatMap(section=>section.spreads.flatMap(item=>item.pages)).find(item=>item.id===pageId);
  const getLayer = layerId => documentModel.sections.flatMap(section=>section.spreads.flatMap(item=>item.pages.flatMap(p=>p.layers))).find(item=>item.id===layerId);
  function people(source){const count=source==='teachers'?view.teachers:view.students,names=source==='teachers'?TEACHERS:STUDENTS;return Array.from({length:count},(_,i)=>({id:(source==='teachers'?'t':'s')+i,name:view.long&&i===1?'Александра Константиновна Рождественская-Воскресенская':names[i%names.length]+(i>=names.length?` ${Math.floor(i/names.length)+1}`:''),role:source==='teachers'?(i===0?SUBJECTS[0]:SUBJECTS[1+(i-1)%9]):'11 «А»',detail:source==='teachers'?(i===0?SUBJECTS[0]:SUBJECTS[1+(i-1)%9]):'Наши лучшие моменты впереди',missing:view.missing&&i===1}));}
  function templatePages(section){return section.spreads.flatMap(item=>item.pages);}
  function gridGeometry(count,settings){if(count<=0)return null;const {w,h}=settings.box,gap=Number(settings.gap)||0,photoNameGap=Number(settings.photoNameGap??3),nameDetailGap=Number(settings.nameDetailGap??2),nameH=settings.fontSize*.3528*(settings.lineHeight||1.25)*2,detailH=settings.showDetail?(settings.detailFontSize||9)*.3528*(settings.detailLineHeight||1.25)*2:0,captionH=photoNameGap+nameH+(settings.showDetail?nameDetailGap+detailH:0);let best=null;for(let cols=1;cols<=Math.min(6,count);cols++){const rows=Math.ceil(count/cols),slotW=(w-(cols-1)*gap)/cols,slotH=(h-(rows-1)*gap)/rows,photoW=Math.min(slotW,(slotH-captionH)*.75,Number(settings.photoWidth)||85);if(photoW<(Number(settings.minPhotoWidth)||5))continue;const cardH=photoW/.75+captionH,offsetX=(w-cols*photoW-(cols-1)*gap)/2,offsetY=(h-rows*cardH-(rows-1)*gap)/2,score=photoW*photoW*count-(cols*rows-count)*photoW*.01;if(!best||score>best.score)best={cols,rows,cellW:photoW,cellH:cardH,photoW,photoH:photoW/.75,nameH,detailH,photoNameGap,nameDetailGap,offsetX,offsetY,score};}return best;}
  function capacity(settings){let result=0;for(let n=1;n<=settings.max;n++)if(gridGeometry(n,settings))result=n;return result;}
  function distribute(count,max,preferred,min){if(count===0)return [];const slots=Math.max(Math.ceil(count/max),Math.min(preferred,Math.max(1,Math.floor(count/min)))),base=Math.floor(count/slots),extra=count%slots;return Array.from({length:slots},(_,i)=>base+(i<extra?1:0));}
  const measure=document.createElement('canvas').getContext('2d');
  function nameLines(name,width,fontSize,font,style){measure.font=`${style?.italic?'italic ':''}${style?.bold?'700 ':''}${fontSize*96/72}px "${font||'Arial'}"`;const widthPx=width*96/25.4,lines=[];let current='';for(const word of name.split(' ')){if(measure.measureText(word).width>widthPx)return null;const next=current?current+' '+word:word;if(measure.measureText(next).width>widthPx){lines.push(current);current=word}else current=next;}if(current)lines.push(current);return lines;}
  function planSection(section){const original=templatePages(section),issues=[];let generated=[];
    if(section.kind==='repeat'){
      const ids=documentModel.personalMode==='all'?people('students').map(person=>person.id):documentModel.personalMode==='owner'?[view.owner]:[];
      ids.forEach(personId=>original.forEach(template=>generated.push({templateId:template.id,personId,records:null,source:'repeat'})));
    }else{
      const gridTemplates=original.filter(p=>p.layers.some(item=>item.type==='grid'));
      if(!gridTemplates.length)generated=original.map(template=>({templateId:template.id,records:null,source:'fixed'}));
      else{
        const settings=gridTemplates[0].layers.find(item=>item.type==='grid'),source=settings.source,list=people(source).filter(person=>!(source==='teachers'&&settings.excludeLead&&original.some(p=>p.layers.some(item=>item.type==='photo'&&!item.hidden&&item.source==='lead'))&&person.id==='t0'));
        if(settings.min>settings.max)issues.push({severity:'error',text:'Минимум карточек больше максимума.'});
        if(settings.minFontSize>settings.fontSize)issues.push({severity:'error',text:'Минимальный кегль больше основного.'});
        const fixedCount=original.length-gridTemplates.length,preferred=Math.max(1,(section.target||section.spreads.length)*2-fixedCount),max=Math.min(...gridTemplates.map(p=>capacity(p.layers.find(l=>l.type==='grid')))),counts=max?distribute(list.length,max,preferred,settings.min):[];
        if(!max)issues.push({severity:'error',text:'Карточки не помещаются при заданной ширине фото и отступах.'});
        if(max&&max<settings.max)issues.push({severity:'warning',text:`По размерам фото на страницу помещается ${max} вместо максимума ${settings.max}.`});
        if(counts.some(n=>n<settings.min))issues.push({severity:settings.strictMin?'error':'warning',text:`Последняя страница содержит меньше ${settings.min} карточек.`});
        if(list.some(person=>person.missing))issues.push({severity:'error',text:'У участника отсутствует обязательный портрет.'});
        const layout=counts.length?gridGeometry(Math.max(...counts),settings):null;let actualFont=settings.fontSize;
        if(layout){const fits=size=>list.every(person=>{const lines=nameLines(person.name,layout.cellW*.97,size,settings.font,settings);return lines&&lines.length<=2;});while(actualFont>settings.minFontSize&&!fits(actualFont))actualFont=Math.max(settings.minFontSize,actualFont-.5);if(!fits(actualFont))issues.push({severity:'error',text:'Длинное имя не помещается при минимальном кегле.'});else if(actualFont<settings.fontSize)issues.push({severity:'warning',text:`Имена всего блока уменьшены до ${actualFont} pt.`});}
        let used=0,index=0,offset=0;
        for(const template of original){const hasGrid=template.layers.some(item=>item.type==='grid');if(!hasGrid){generated.push({templateId:template.id,records:null,source:'fixed'});continue;}if(used>=counts.length)continue;
          const records=list.slice(offset,offset+counts[used]);generated.push({templateId:template.id,records,source,actualFont,layoutCount:Math.max(...counts),part:used+1,parts:counts.length});offset+=counts[used];used++;index=generated.length;
        }
        const repeatTemplate=gridTemplates.at(-1);while(used<counts.length){const records=list.slice(offset,offset+counts[used]);generated.splice(index,0,{templateId:repeatTemplate.id,records,source,actualFont,layoutCount:Math.max(...counts),part:used+1,parts:counts.length});offset+=counts[used];used++;index++;}
        if(!counts.length&&gridTemplates.length){const template=gridTemplates[0];generated.push({templateId:template.id,records:[],source,actualFont:settings.fontSize,part:1,parts:1});}
      }
    }
    const checked=new Set();for(const generatedPage of generated){const template=getTemplatePage(generatedPage.templateId);for(const item of template?.layers||[]){const checkKey=item.id+(item.source==='item'?':'+generatedPage.personId:'');if(item.type!=='photo'||item.hidden||checked.has(checkKey))continue;checked.add(checkKey);if(item.source==='custom'&&!item.dataUrl)issues.push({severity:'error',text:`«${item.name}»: загруженная фотография не выбрана.`});if(['lead','owner','item'].includes(item.source)&&(!photoPerson(item.source,generatedPage.personId)||photoPerson(item.source,generatedPage.personId).missing))issues.push({severity:'error',text:`«${item.name}»: источник фотографии пуст.`});}}
    if(generated.length%2)generated.push({templateId:null,records:null,source:'padding'});
    return {sectionId:section.id,pages:generated,spreads:generated.length/2,issues};
  }
  function plan(){planning=documentModel.sections.map(planSection);return planning;}
  function sectionPlan(key){return planning.find(p=>p.sectionId===key);}
  function currentPagePlan(){return sectionPlan(view.section)?.pages[view.spread*2+view.side];}
  function currentTemplatePage(){return getTemplatePage(currentPagePlan()?.templateId);}
  function selectedLayer(){return currentTemplatePage()?.layers.find(item=>item.id===view.layer);}
  function photoPerson(source,personId){if(source==='lead')return people('teachers')[0];if(source==='owner')return [...people('students'),...people('teachers')].find(p=>p.id===view.owner);if(source==='item')return people('students').find(p=>p.id===personId);return null;}
  function placeholderSvg(person,group=false){const colors=['#a3aaa4','#b6aaa0','#a7a8b2','#b5ada0'],color=colors[Number(person?.id?.slice(1)||0)%4];let circles='';if(group){for(let i=0;i<12;i++){const x=13+i%6*15,y=31+Math.floor(i/6)*43;circles+=`<circle cx="${x}" cy="${y}" r="4" fill="#b6b3ad"/><rect x="${x-6}" y="${y+6}" width="12" height="17" rx="3" fill="#b9b7b1"/>`;}}else circles=`<ellipse cx="50" cy="112" rx="44" ry="42" fill="${color}"/><rect x="42" y="60" width="16" height="30" fill="#d4c2b5"/><ellipse cx="50" cy="45" rx="23" ry="30" fill="#d7c5b8"/><path d="M27 43 Q22 11 50 13 Q78 10 73 46 Q64 27 42 34 Z" fill="#80766e"/>`;
    return 'data:image/svg+xml;charset=utf-8,'+encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="100" height="133" viewBox="0 0 100 133"><rect width="100" height="133" fill="#e7e5e0"/>${circles}</svg>`);
  }
  function resolvedPhoto(item,generated){if(item.source==='custom')return item.dataUrl||null;if(item.source==='class')return placeholderSvg(null,true);const person=photoPerson(item.source,generated.personId);return person&&!person.missing?placeholderSvg(person):null;}
  function resolvedText(item,generated){if(item.binding==='static')return item.text;const person=photoPerson(item.binding.startsWith('item')?'item':item.binding.startsWith('lead')?'lead':'owner',generated.personId);if(item.binding.endsWith('.name'))return person?.name||'Нет данных';if(item.binding==='class')return '11 «А»';if(item.binding==='year')return '2026';return item.text;}

return {plan,people,gridGeometry,placeholderSvg,resolvedPhoto,resolvedText,getTemplatePage};
};
