(() => {
  "use strict";
  const KEY = "bluebot.kingdom-builder.v1";
  const initial = () => ({wood:80,gold:120,workers:2,defence:0,day:1,kills:0,keepLevel:1,buildings:{keep:1,house:0,mill:0,tower:0,farm:0},trees:[0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47],nextWaveAt:Date.now()+60000,version:1});
  let state;
  try { const saved = JSON.parse(localStorage.getItem(KEY) || "null"); state = saved && saved.version===1 ? {...initial(),...saved,buildings:{...initial().buildings,...saved.buildings}} : initial(); } catch (_) { state=initial(); }
  const $ = id => document.getElementById(id);
  const costs = {house:{wood:35,gold:20},mill:{wood:45,gold:30},tower:{wood:40,gold:45},farm:{wood:55,gold:25}};
  const names = {keep:"Keep",house:"Lodge",mill:"Lumber Mill",tower:"Guard Tower",farm:"Gold Mine"};
  const icons = {keep:"🏰",house:"🏡",mill:"🪓",tower:"🗼",farm:"⛏️"};
  const slots = {keep:24,house:16,mill:18,tower:30,farm:32};
  let lastTick = Date.now();
  function save(){ try{localStorage.setItem(KEY,JSON.stringify(state));}catch(_){} }
  function say(message){ $("game-message").textContent=message; }
  function spend(wood,gold){ if(state.wood<wood||state.gold<gold){say("Not enough resources yet. Chop trees or scout the forest first.");return false;}state.wood-=wood;state.gold-=gold;return true; }
  function renderMap(){
    const map=$("game-map");map.replaceChildren();
    for(let i=0;i<49;i++){
      const b=Object.keys(slots).find(k=>slots[k]===i && (k==="keep"||state.buildings[k]>0));
      const tile=document.createElement("button");tile.type="button";tile.className="tile";
      if(b){tile.classList.add(b==="keep"?"keep":"building");const s=document.createElement("span");s.className="sprite";s.textContent=icons[b];tile.append(s);const l=document.createElement("span");l.className="tile-label";l.textContent=names[b];tile.append(l);tile.setAttribute("aria-label",names[b]);}
      else if(state.trees.includes(i)){tile.classList.add("tree");const s=document.createElement("span");s.className="sprite";s.textContent="🌲";tile.append(s);tile.setAttribute("aria-label","Forest tree — tap to chop");tile.addEventListener("click",()=>chop(i));}
      else if(i===6||i===13||i===20||i===27||i===34||i===41){tile.classList.add("water");tile.innerHTML='<span class="sprite">〰️</span>';tile.disabled=true;tile.setAttribute("aria-label","River");}
      else {tile.classList.add("path");const s=document.createElement("span");s.className="sprite";s.textContent=(i===17||i===25||i===31)?"🪨":"·";tile.append(s);tile.setAttribute("aria-label","Cleared land");}
      map.append(tile);
    }
    if(state.waveActive){const tile=map.children[40];if(tile){tile.classList.add("monster");tile.querySelector(".sprite").textContent="👾";tile.setAttribute("aria-label","Monster attack");}}
  }
  function render(){
    $("wood").textContent=Math.floor(state.wood);$("gold").textContent=Math.floor(state.gold);$("workers").textContent=state.workers;$("defence").textContent=state.defence;
    $("day-label").textContent="DAY "+state.day;$("building-count").textContent=1+Object.values(state.buildings).reduce((n,v)=>n+v,0)-state.buildings.keep;
    $("kills").textContent=state.kills;$("keep-level").textContent=state.keepLevel;
    document.querySelectorAll("[data-build]").forEach(btn=>{const k=btn.dataset.build;const count=state.buildings[k]||0;btn.querySelector(".build-action").textContent=count?("Owned: "+count+" · Build another"):"Build · "+costs[k].wood+" wood, "+costs[k].gold+" gold";});
    renderMap();save();
  }
  function chop(index){
    if(!state.trees.includes(index)){say("That tree has already been cleared.");return;}
    state.trees=state.trees.filter(i=>i!==index);state.wood+=12;say("Tree felled. +12 wood. The forest is opening up for your kingdom.");render();
  }
  function build(kind){
    const c=costs[kind];if(!c||!spend(c.wood,c.gold))return;
    if(kind==="house")state.workers+=1;
    if(kind==="tower")state.defence+=3;
    state.buildings[kind]=(state.buildings[kind]||0)+1;
    if(state.buildings[kind]>1){state.wood+=Math.floor(c.wood*.18);}
    say(kind==="house"?"A new lodge is ready. One worker has joined your settlement.":kind==="tower"?"Guard Tower raised. Your defence is stronger.":kind==="mill"?"The Lumber Mill is operating. Workers will gather wood automatically.":"The Gold Mine is open. Gold will arrive over time.");
    render();
  }
  function wave(){
    state.waveActive=true;const strength=2+Math.floor(state.day/2);
    const power=state.defence+state.buildings.tower*2+state.keepLevel;
    if(power>=strength){state.kills+=strength;state.gold+=18+strength*3;say("Monster wave repelled! Your guards protected the realm. +"+(18+strength*3)+" gold.");}
    else{const loss=Math.min(state.gold,12+strength*4);state.gold-=loss;say("Monsters reached the outskirts. Defence is too low; you lost "+loss+" gold. Build towers and train guards.");}
    state.waveActive=false;state.day+=1;state.nextWaveAt=Date.now()+60000;render();
  }
  function tick(){
    const now=Date.now(),elapsed=Math.min(30,(now-lastTick)/1000);lastTick=now;
    if(state.buildings.mill)state.wood+=state.buildings.mill*state.workers*.18*elapsed;
    if(state.buildings.farm)state.gold+=state.buildings.farm*(.12+state.keepLevel*.025)*elapsed;
    const left=Math.max(0,Math.ceil((state.nextWaveAt-now)/1000));$("next-wave").textContent=left>0?"Nightfall in "+left+"s":"Monster wave!";
    if(now>=state.nextWaveAt)wave();else if(Math.floor(now/10000)!==Math.floor((now-elapsed*1000)/10000))save();
    $("wood").textContent=Math.floor(state.wood);$("gold").textContent=Math.floor(state.gold);
  }
  document.querySelectorAll("[data-build]").forEach(btn=>btn.addEventListener("click",()=>build(btn.dataset.build)));
  $("chop-tree").addEventListener("click",()=>{const i=state.trees[0];if(i===undefined){say("The nearby forest is cleared. Build a Lumber Mill for renewable wood.");return;}chop(i);});
  $("scout").addEventListener("click",()=>{const cache=18+Math.floor(Math.random()*24);state.gold+=cache;say("Your scout found an abandoned merchant cache. +"+cache+" gold.");render();});
  $("train-guard").addEventListener("click",()=>{if(spend(0,25)){state.defence+=2;say("Two guards have joined your watch. Defence +2.");render();}});
  $("upgrade-keep").addEventListener("click",()=>{if(spend(50*state.keepLevel,50*state.keepLevel)){state.keepLevel++;state.defence+=1;say("Keep upgraded to level "+state.keepLevel+". Your realm is more resilient.");render();}});
  $("reset-game").addEventListener("click",()=>$("confirm-modal").hidden=false);
  $("cancel-reset").addEventListener("click",()=>$("confirm-modal").hidden=true);
  $("confirm-reset").addEventListener("click",()=>{state=initial();lastTick=Date.now();$("confirm-modal").hidden=true;say("A fresh kingdom awaits. Begin gathering and building!");render();});
  if(window.Telegram&&window.Telegram.WebApp){try{window.Telegram.WebApp.ready();window.Telegram.WebApp.expand();}catch(_){}}
  render();setInterval(tick,1000);
})();