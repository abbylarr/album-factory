/* Auto text: static text with data chips, stored as one string with {{field}} tokens.
   Mirrors album_factory/auto_text.py; the server resolves the same tokens with real order data. */
(function(root){
  const GROUPS=[
    ['Люди',[['owner.name','Имя владельца'],['owner.quote','Цитата владельца'],['item.name','Имя героя разворота'],['item.quote','Цитата героя разворота'],['lead.name','Имя руководителя'],['lead.subject','Предмет руководителя']]],
    ['Класс',[['school','Школа'],['city','Город'],['class','Класс'],['year','Год выпуска']]],
    ['Съёмка разворота',[['shoot.title','Название съёмки'],['shoot.date','Дата съёмки']]]
  ];
  const FIELDS=Object.fromEntries(GROUPS.flatMap(([,rows])=>rows));
  const TOKEN=/\{\{([a-z.]+)\}\}/g;
  const fields=text=>new Set([...(text||'').matchAll(TOKEN)].map(m=>m[1]).filter(f=>f in FIELDS));
  /* value(field) returns the text for one chip; an empty value leaves nothing behind. */
  const resolve=(text,value)=>(text||'').replace(TOKEN,(all,field)=>field in FIELDS?String(value(field)??''):all);
  /* Split into static text and chips for the chip editor. */
  const parts=text=>{const out=[];let last=0;for(const m of (text||'').matchAll(TOKEN)){if(!(m[1] in FIELDS))continue;if(m.index>last)out.push({text:text.slice(last,m.index)});out.push({field:m[1]});last=m.index+m[0].length;}if(last<(text||'').length)out.push({text:text.slice(last)});return out;};
  root.AutoText={GROUPS,FIELDS,fields,resolve,parts,token:field=>`{{${field}}}`};
})(window);
