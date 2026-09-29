/* Auto text: static text with data chips, stored as one string with {{field|mod}} tokens.
   Mirrors album_factory/auto_text.py; the server resolves the same tokens with real order data. */
(function(root){
  const GROUPS=[
    ['Люди',[['owner.name','Имя владельца'],['owner.quote','Цитата владельца'],['item.name','Имя героя разворота'],['item.quote','Цитата героя разворота'],['lead.name','Имя руководителя'],['lead.subject','Предмет руководителя']]],
    ['Класс',[['school','Школа'],['city','Город'],['class','Класс'],['year','Год выпуска']]],
    ['Съёмка разворота',[['shoot.title','Название съёмки'],['shoot.date','Дата съёмки']]]
  ];
  const FIELDS=Object.fromEntries(GROUPS.flatMap(([,rows])=>rows));
  const TOKEN=/\{\{([a-z.]+)((?:\|[a-z]+)*)\}\}/g;
  /* Chip settings: a form of the value and a letter case. The first entry of each list is the default. */
  const FORMS={
    name:[['','Полностью','Анна Петрова'],['first','Имя','Анна'],['last','Фамилия','Петрова'],['initials','Инициалы','Петрова А.']],
    school:[['','Полное название'],['short','Краткое название']],
    class:[['','Как в заказе'],['quotes','С кавычками','11 «Б»'],['bare','Без кавычек','11 Б'],['letter','Только буква','Б'],['number','Только цифра','11']]
  };
  const CASES=[['','Как есть','—'],['upper','Все прописные','AG'],['lower','Все строчные','ag'],['title','Каждое слово с заглавной','Ag']];
  const CASE_IDS=CASES.map(([id])=>id).filter(Boolean);
  const kind=field=>field.endsWith('.name')?'name':field;
  const mods=raw=>(raw||'').split('|').filter(Boolean);
  const fields=text=>new Set([...(text||'').matchAll(TOKEN)].map(m=>m[1]).filter(f=>f in FIELDS));
  const applyCase=(text,mode)=>{text=text??'';if(mode==='upper')return text.toLocaleUpperCase('ru');if(mode==='lower')return text.toLocaleLowerCase('ru');if(mode==='title')return text.toLocaleLowerCase('ru').replace(/(^|[\s\-«"'(])(\p{L})/gu,(all,before,letter)=>before+letter.toLocaleUpperCase('ru'));return text;};
  const classParts=value=>{const m=/^\s*(\d+)\s*[-–]?\s*[«"„“']?\s*(.*?)\s*[»"“”']?\s*$/.exec(value||'');return m?[m[1],m[2]]:['',(value||'').trim()];};
  /* raw is a string, a name {first,middle,last} or a school {full,short}. */
  function format(field,raw,list=[]){
    const group=kind(field),form=list.find(m=>(FORMS[group]||[]).some(([id])=>id&&id===m))||'',mode=list.find(m=>CASE_IDS.includes(m))||'';
    let value;
    if(group==='name'&&raw&&typeof raw==='object'){
      const {first='',middle='',last=''}=raw;
      value=form==='first'?first:form==='last'?last:form==='initials'?[...(last?[last]:[]),...[first,middle].filter(Boolean).map(p=>p[0]+'.')].join(' '):[first,middle,last].filter(Boolean).join(' ');
    }else if(group==='school'&&raw&&typeof raw==='object')value=(form==='short'?raw.short:'')||raw.full||'';
    else{
      value=raw==null?'':String(raw);
      if(group==='class'&&form){const [number,letter]=classParts(value);if(number)value={quotes:letter?`${number} «${letter}»`:number,bare:`${number} ${letter}`.trim(),letter,number}[form];}
    }
    return applyCase(value,mode);
  }
  /* value(field) returns the raw data for one chip; an empty value leaves nothing behind. */
  const resolve=(text,value)=>(text||'').replace(TOKEN,(all,field,raw)=>field in FIELDS?format(field,value(field),mods(raw)):all);
  /* Split into static text and chips for the chip editor. */
  const parts=text=>{const out=[];let last=0;for(const m of (text||'').matchAll(TOKEN)){if(!(m[1] in FIELDS))continue;if(m.index>last)out.push({text:text.slice(last,m.index)});out.push({field:m[1],mods:mods(m[2])});last=m.index+m[0].length;}if(last<(text||'').length)out.push({text:text.slice(last)});return out;};
  const token=(field,list=[])=>`{{${[field,...list.filter(Boolean)].join('|')}}}`;
  /* Short chip label: the field and its settings, e.g. «Класс · 11 Б · AG». */
  const label=(field,list=[])=>{const group=kind(field),form=(FORMS[group]||[]).find(([id])=>id&&list.includes(id)),mode=CASES.find(([id])=>id&&list.includes(id));return [FIELDS[field],form?(group==='class'?form[2]:form[1].toLocaleLowerCase('ru')):'',mode?mode[2]:''].filter(Boolean).join(' · ');};
  root.AutoText={GROUPS,FIELDS,FORMS,CASES,kind,fields,resolve,parts,token,label,format,applyCase,classParts};
})(typeof window!=='undefined'?window:globalThis);
