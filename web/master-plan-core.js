/* How blocks of a master layout unfold into spreads. Shared by the editor preview and, mirrored in
   album_factory/master_plan.py, by album generation; tests/test_master_plan_parity.py keeps them equal.

   A block is fixed (every spread once), a list (vignettes of students or teachers) or personal (its spreads repeat per person).
   Spreads of a list block have roles: intro and outro appear once, repeat spreads cycle while people remain,
   and the last spread replaces a repeat spread that the list would fill only partly.
   A list or personal block may be split into parts with other blocks between them: a part stops after `limit` spreads,
   and the block whose `continues` names it takes the people from where it stopped. */
(function(root){
  const ROLES=['intro','repeat','last','outro'];
  const PEOPLE=['all','others','owner','off'];
  const LIST_DEFAULT={source:'students',min:4,max:12,strictMin:false,excludeLead:false};
  const roleOf=spread=>ROLES.includes(spread?.role)?spread.role:'repeat';
  const hasGrid=page=>(page.layers||[]).some(l=>l.type==='grid');
  const gridPages=spread=>(spread.pages||[]).filter(hasGrid).length;

  /* Split n people into parts as evenly as possible; the first parts take the remainder. */
  function distribute(n,parts){if(parts<=0)return [];const base=Math.floor(n/parts),extra=n%parts;return Array.from({length:parts},(_,i)=>base+(i<extra?1:0));}

  /* Spreads of a list block and which part of the list each page shows.
     n — people in the list, cap — cards that fit the tightest vignette of the block.
     Result: {spreads:[{spread,role,pages:[{page,part}]}], counts:[cards per part], taken, issues:[codes]}.
     part is the index into counts, or null for a page without a vignette or a vignette left empty.
     taken — how many of the n people the block placed: fewer than n only when section.limit stops it; the pages are then
     filled as evenly as if the whole list ran on, and the rest is left to the block that continues the list. */
  function listPlan(section,n,cap){
    const list={...LIST_DEFAULT,...(section.list||{})},min=Math.max(1,Number(list.min)||1),spreads=section.spreads||[],issues=[];
    const once=spread=>({spread,take:gridPages(spread)});
    const pick=role=>spreads.filter(s=>roleOf(s)===role);
    const intro=pick('intro'),repeat=pick('repeat'),outro=pick('outro'),last=pick('last')[0]||null;
    if(!spreads.some(s=>gridPages(s)))return finish(spreads.map(s=>({spread:s,take:0})),[],['no-grid'],0);
    if(!cap)return finish([...intro,...repeat.slice(0,1),...outro].map(s=>({spread:s,take:0})),[],['no-fit'],0);
    const fixed=[...intro,...outro].reduce((sum,s)=>sum+gridPages(s),0),cycleHasGrid=repeat.some(s=>gridPages(s));
    /* Pages the designer aims for: the grid pages of a block with `target` spreads. */
    const target=Math.max(1,Math.round(Number(section.target)||spreads.length));
    let preferred=fixed;for(let i=0;i<target-intro.length-outro.length&&repeat.length;i++)preferred+=gridPages(repeat[i%repeat.length]);
    preferred=Math.max(1,preferred);
    let pages=n?Math.max(Math.ceil(n/cap),Math.min(preferred,Math.max(1,Math.floor(n/min)))):1;
    pages=Math.max(pages,fixed);
    const whole=pages,limit=partLimit(section);
    if(n&&limit&&cycleHasGrid){
      let room=fixed;for(let i=0;i<limit-intro.length-outro.length;i++)room+=gridPages(repeat[i%repeat.length]);
      pages=Math.min(pages,Math.max(room,fixed,1));
    }
    const cut=pages<whole;
    const middle=[];let rest=pages-fixed,turn=0;
    while(rest>0){
      if(!cycleHasGrid){
        const room=last?gridPages(last):0;
        if(last)middle.push(once(last));
        if(room<rest)issues.push('no-repeat');
        pages=fixed+room;
        break;
      }
      const spread=repeat[turn++%repeat.length],grids=gridPages(spread);
      if(!grids){middle.push({spread,take:0});continue;}
      if(rest>=grids){middle.push({spread,take:grids});rest-=grids;continue;}
      if(last&&gridPages(last)>=rest){middle.push(once(last));pages+=gridPages(last)-rest;}
      else{middle.push({spread,take:rest});issues.push('half');}
      break;
    }
    const counts=!n?[0]:cut?distribute(n,whole).slice(0,pages):distribute(n,Math.max(pages,1));
    if(n&&counts.some(c=>c<min))issues.push('below-min');
    if(n&&counts.some(c=>c>cap))issues.push('overflow');
    return finish([...intro.map(once),...middle,...outro.map(once)],counts,issues,counts.reduce((a,b)=>a+b,0));
  }
  function finish(sequence,counts,issues,taken){
    let part=0;
    const spreads=sequence.map(({spread,take})=>{let used=0;return {spread:spread.id,role:roleOf(spread),pages:spread.pages.map(page=>{if(!hasGrid(page)||used>=take||part>=counts.length)return {page:page.id,part:null};used++;return {page:page.id,part:part++};})};});
    return {spreads,counts,taken,issues};
  }

  const partLimit=section=>Math.max(0,Math.round(Number(section.limit))||0);
  /* How many of n people a part of a split personal block takes: whole people, as many as fit in its spreads. */
  function personalTake(section,n){const limit=partLimit(section),per=Math.max(1,(section.spreads||[]).length);return limit?Math.min(n,Math.max(1,Math.floor(limit/per))):n;}
  /* Only lists and personal blocks for many people can be split. */
  const splittable=s=>!s.cover&&(s.kind==='flow'||s.kind==='repeat'&&['all','others'].includes(s.people||'all'));
  /* Keep split blocks consistent: a continuation follows a block of the same kind and the same people, one continuation
     per block, and only a continued block keeps a limit. Returns true when the document changed. */
  function linkParts(doc){
    let changed=false;const sections=doc.sections||[],taken=new Set();
    for(const s of sections){
      if(!('continues' in s))continue;
      const from=sections.find(x=>x.id===s.continues);
      if(!splittable(s)||!from||from===s||from.kind!==s.kind||!splittable(from)||taken.has(from.id)){delete s.continues;changed=true;continue;}
      taken.add(from.id);
      if(s.kind==='flow'&&s.list?.source!==(from.list?.source||'students')){s.list={...(s.list||{}),source:from.list?.source||'students'};changed=true;}
      if(s.kind==='repeat'&&(s.people||'all')!==(from.people||'all')){s.people=from.people||'all';changed=true;}
    }
    for(const s of sections)if('limit' in s&&!taken.has(s.id)){delete s.limit;changed=true;}
    return changed;
  }

  /* Whose personal spreads a block shows in the album of `owner` (ids in list order). */
  function people(section,students,owner){
    const mode=PEOPLE.includes(section.people)?section.people:'all';
    if(mode==='off')return [];
    if(mode==='owner')return students.includes(owner)?[owner]:[];
    if(mode==='others')return students.filter(id=>id!==owner);
    return students.slice();
  }

  /* Documents saved before block rules (rulesVersion 1) kept list settings on the vignettes and one personal mode for the album.
     Returns true when the document changed. uid() gives ids for spreads added to keep old overflow behaviour. */
  function upgrade(doc,uid){
    if(doc.rulesVersion===2)return false;
    const mode=PEOPLE.includes(doc.personalMode)?doc.personalMode:'all';
    for(const section of doc.sections||[]){
      if(section.cover)continue;
      if(section.kind==='repeat'){section.people=mode;continue;}
      if(section.kind!=='flow')continue;
      const grids=(section.spreads||[]).flatMap(s=>s.pages.flatMap(p=>p.layers.filter(l=>l.type==='grid')));
      const first=grids[0]||{};
      section.list={source:first.source==='teachers'?'teachers':'students',min:Number(first.min)||LIST_DEFAULT.min,max:Number(first.max)||LIST_DEFAULT.max,strictMin:!!first.strictMin,excludeLead:!!first.excludeLead};
      if(section.list.min>section.list.max)section.list.min=section.list.max;
      for(const grid of grids){grid.source=section.list.source;delete grid.min;delete grid.max;delete grid.strictMin;delete grid.excludeLead;}
      /* Spreads made only of vignette pages repeat; the others keep their place before or after them. */
      const full=s=>s.pages.every(hasGrid);
      const firstFull=section.spreads.findIndex(full);
      section.spreads.forEach((spread,i)=>{spread.role=full(spread)?'repeat':firstFull<0||i<firstFull?'intro':'outro';});
      if(firstFull<0&&grids.length){
        /* The old layout repeated the last vignette page when the list overflowed; keep that as a repeat spread. */
        const source=section.spreads.flatMap(s=>s.pages).filter(hasGrid).at(-1);
        const copy=()=>{const page=JSON.parse(JSON.stringify(source));page.id=uid();page.layers.forEach(l=>{l.id=uid();});return page;};
        section.spreads.push({id:uid(),role:'repeat',pages:[copy(),copy()]});
      }
    }
    delete doc.personalMode;
    doc.rulesVersion=2;
    if(!['spreads','book'].includes(doc.layout))doc.layout='spreads';
    return true;
  }

  root.MasterPlan={ROLES,PEOPLE,LIST_DEFAULT,roleOf,hasGrid,gridPages,distribute,listPlan,personalTake,splittable,linkParts,people,upgrade};
})(typeof window!=='undefined'?window:globalThis);
