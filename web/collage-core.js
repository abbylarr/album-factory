/* Collage tree shared by the master editor and the layout editor: geometry and structural edits.
   Geometry mirrors collage_frames in album_factory/master_layout.py; tests/test_collage_parity.py keeps them equal.
   Edits change the layer in place and return the id of the cell to focus, or null when nothing changed. */
(function(root){
  const MAX_ROWS=8,MAX_CELLS=8,MAX_DEPTH=4,MAX_LEAVES=48,MAX_GAP=40;
  const CONTENT=['source','pick','cropX','cropY','cropZoom','dataUrl'];
  const PORTRAITS=['owner','lead','item'];

  /* Leaf rectangles and the gutters between them, local to the collage box (mm). */
  function layout(layer){
    const gapX=Number(layer.gapX??4),gapY=Number(layer.gapY??4),w=layer.box.w,h=layer.box.h,rows=layer.rows||[],frames=[],gutters=[];
    if(!rows.length||w<=0||h<=0)return {frames,gutters};
    const rowH=(h-gapY*(rows.length-1))/rows.length;
    const place=(cell,x,y,cw,ch,depth)=>{
      if(cw<0.2||ch<0.2)return;
      const kids=cell.cells||[];
      if(cell.split==='h'&&kids.length>=2){const gx=Math.min(gapX,cw*0.35),inner=(cw-gx*(kids.length-1))/kids.length;kids.forEach((child,i)=>{place(child,x+i*(inner+gx),y,inner,ch,depth+1);if(i<kids.length-1)gutters.push({axis:'x',x:x+(i+1)*inner+i*gx,y,w:gx,h:ch});});}
      else if(cell.split==='v'&&kids.length>=2){const gy=Math.min(gapY,ch*0.35),inner=(ch-gy*(kids.length-1))/kids.length;kids.forEach((child,i)=>{place(child,x,y+i*(inner+gy),cw,inner,depth+1);if(i<kids.length-1)gutters.push({axis:'y',x,y:y+(i+1)*inner+i*gy,w:cw,h:gy});});}
      else frames.push({cell,x,y,w:cw,h:ch,depth});
    };
    rows.forEach((row,ri)=>{
      const n=Math.max(row.length,1),cellW=(w-gapX*(n-1))/n,y=ri*(rowH+gapY);
      row.forEach((cell,i)=>{place(cell,i*(cellW+gapX),y,cellW,rowH,0);if(i<row.length-1)gutters.push({axis:'x',x:(i+1)*cellW+i*gapX,y,w:gapX,h:rowH});});
      if(ri<rows.length-1)gutters.push({axis:'y',x:0,y:y+rowH,w,h:gapY});
    });
    return {frames,gutters};
  }
  const frames=layer=>layout(layer).frames;

  /* Where a cell sits: its list, index, owner ({row} for a top-level cell or the split parent) and depth. */
  function locate(layer,id){
    if(!layer?.rows||!id)return null;
    const scan=(list,owner,depth)=>{for(let i=0;i<list.length;i++){const cell=list[i];if(cell.id===id)return {cell,list,index:i,owner,depth};if(cell.cells){const found=scan(cell.cells,cell,depth+1);if(found)return found;}}return null;};
    for(const row of layer.rows){const found=scan(row,{row},0);if(found)return found;}
    return null;
  }
  const leaves=layer=>{const out=[],walk=c=>c.split?c.cells.forEach(walk):out.push(c);(layer.rows||[]).forEach(row=>row.forEach(walk));return out;};
  const rowOf=(layer,id)=>{const has=list=>list.some(c=>c.id===id||(c.cells&&has(c.cells)));return layer.rows.find(row=>has(row))||null;};

  /* A new empty frame: any general photo, and with the hero when its neighbour asks for the hero. */
  const leaf=(uid,like)=>({id:uid(),source:'class',pick:{category:'any',...(like?.source==='class'&&like.pick?.who?{who:like.pick.who}:{})},cropX:50,cropY:50});
  const lastLeaf=cell=>cell?.split?lastLeaf(cell.cells.at(-1)):cell;
  function content(cell){const out={};for(const k of CONTENT)if(cell[k]!==undefined)out[k]=JSON.parse(JSON.stringify(cell[k]));return out;}

  /* Change what fills a leaf (a collage cell or a photo layer). An uploaded file is kept so switching back restores it;
     a new file or a new kind of content resets the crop. */
  function setSource(cell,source,extra={}){
    if(!cell||cell.split)return false;
    const was=kind(cell.source||'class');
    cell.source=source;
    if(source==='class')cell.pick=extra.pick||cell.pick||{category:'any'};else delete cell.pick;
    if(extra.dataUrl)cell.dataUrl=extra.dataUrl;
    if(extra.dataUrl||was!==kind(source)){cell.cropX=50;cell.cropY=50;delete cell.cropZoom;}
    return true;
  }
  const kind=source=>source==='custom'?'custom':PORTRAITS.includes(source)?'portrait':'class';

  /* What the UI may offer for a focused cell. */
  function can(layer,id){
    const loc=locate(layer,id),count=leaves(layer).length,row=loc&&rowOf(layer,id);
    return {
      split:!!loc&&!loc.cell.split&&loc.depth<MAX_DEPTH&&count<MAX_LEAVES,
      remove:!!loc&&count>1,
      removeRow:!!row&&layer.rows.length>1,
      addRow:layer.rows.length<MAX_ROWS&&count+Math.max(...layer.rows.map(r=>r.length))<=MAX_LEAVES,
      addColumn:layer.rows.some(r=>r.length<MAX_CELLS)&&count+layer.rows.filter(r=>r.length<MAX_CELLS).length<=MAX_LEAVES,
    };
  }

  /* Split a leaf into two: the old photo stays in the first half, the second half is new. */
  function split(layer,id,dir,uid){
    const loc=locate(layer,id);
    if(!can(layer,id).split||!['h','v'].includes(dir))return null;
    const keep={id:uid(),...content(loc.cell)};
    for(const k of CONTENT)delete loc.cell[k];
    loc.cell.split=dir;loc.cell.cells=[keep,leaf(uid,keep)];
    return keep.id;
  }

  /* Remove a leaf; its neighbours share the space. A split left with one child collapses into it. */
  function remove(layer,id){
    const loc=locate(layer,id);
    if(!can(layer,id).remove)return null;
    loc.list.splice(loc.index,1);
    if(loc.owner.row){
      if(loc.list.length)return firstLeaf(loc.list[Math.min(loc.index,loc.list.length-1)]);
      const at=layer.rows.indexOf(loc.list);layer.rows.splice(at,1);
      return firstLeaf(layer.rows[Math.min(at,layer.rows.length-1)][0]);
    }
    if(loc.list.length===1){const only=loc.list[0];for(const k of Object.keys(loc.owner))delete loc.owner[k];Object.assign(loc.owner,only);return firstLeaf(loc.owner);}
    return firstLeaf(loc.list[Math.min(loc.index,loc.list.length-1)]);
  }
  const firstLeaf=cell=>cell?(cell.split?firstLeaf(cell.cells[0]):cell.id):null;

  function removeRow(layer,id){
    const row=rowOf(layer,id);
    if(!can(layer,id).removeRow)return null;
    const at=layer.rows.indexOf(row);layer.rows.splice(at,1);
    return firstLeaf(layer.rows[Math.min(at,layer.rows.length-1)][0]);
  }

  /* A new row below the rest with as many frames as the widest row. */
  function addRow(layer,uid){
    if(!layer.rows.length||layer.rows.length>=MAX_ROWS)return null;
    const n=Math.max(...layer.rows.map(r=>r.length));
    if(leaves(layer).length+n>MAX_LEAVES)return null;
    const like=lastLeaf(layer.rows.at(-1).at(-1)),row=Array.from({length:n},()=>leaf(uid,like));layer.rows.push(row);
    return row[0].id;
  }

  /* One more frame at the end of every row that has room. */
  function addColumn(layer,uid){
    const open=layer.rows.filter(r=>r.length<MAX_CELLS);
    if(!open.length||leaves(layer).length+open.length>MAX_LEAVES)return null;
    let first=null;open.forEach(row=>{const cell=leaf(uid,lastLeaf(row.at(-1)));row.push(cell);first=first||cell.id;});
    return first;
  }

  /* Fresh ids for a pasted or duplicated collage. */
  function reidentify(layer,uid){const walk=c=>{c.id=uid();(c.cells||[]).forEach(walk);};(layer.rows||[]).forEach(row=>row.forEach(walk));}

  /* One gap value in both directions unless the designer unlinked them. */
  const gapsLinked=layer=>layer.gapLinked??(Number(layer.gapX??4)===Number(layer.gapY??4));

  /* Largest gap (mm) that still leaves every frame at least 6 mm. */
  function maxGap(layer,axis){
    let limit=MAX_GAP;
    const cols=Math.max(1,...layer.rows.map(r=>r.length)),rows=layer.rows.length;
    if((axis==='x'||!axis)&&cols>1)limit=Math.min(limit,(layer.box.w-cols*6)/(cols-1));
    if((axis==='y'||!axis)&&rows>1)limit=Math.min(limit,(layer.box.h-rows*6)/(rows-1));
    return Math.max(0,limit);
  }

  root.CollageCore={layout,frames,locate,leaves,leaf,content,setSource,kind,can,split,remove,removeRow,addRow,addColumn,reidentify,gapsLinked,maxGap,PORTRAITS,MAX_GAP};
})(typeof window!=='undefined'?window:globalThis);
