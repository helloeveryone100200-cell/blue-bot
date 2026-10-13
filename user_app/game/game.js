(() => {
  "use strict";
  const KEY = "bluebot.kingdom-builder.v1";
  const MAX_LEVEL = 5;
  const BUILDINGS = {
    keep: {name:"The Keep", category:"ROYAL STRUCTURE", art:"ROYAL STRONGHOLD", icon:"♜", tileIcon:"🏰", description:"The heart of your realm. Strengthen the Keep to improve your kingdom's resilience and defence.", base:{wood:50,gold:50}, effect:"DEFENCE", effectIcon:"⬟", effectValue:level=>level, next:level=>"+"+(level+1)+" Defence"},
    house: {name:"Woodcutter's Lodge", category:"SETTLEMENT", art:"SETTLER'S LODGE", icon:"⌂", tileIcon:"🏡", description:"A welcoming home for your workforce. Each upgrade brings another skilled worker to your settlement.", base:{wood:35,gold:20}, effect:"WORKERS", effectIcon:"♟", effectValue:level=>level, next:level=>"+"+(level+1)+" Worker"},
    mill: {name:"Lumber Mill", category:"RESOURCE PRODUCTION", art:"TIMBER WORKS", icon:"⚒", tileIcon:"🪓", description:"Turn the forest into a steady supply of timber. More advanced mills make every worker more productive.", base:{wood:45,gold:30}, effect:"WOOD / MIN", effectIcon:"▥", effectValue:level=>Math.round(level*2*10)/10, next:level=>"+"+((level+1)*2)+" Wood / min"},
    tower: {name:"Guard Tower", category:"DEFENSIVE STRUCTURE", art:"FRONTIER WATCH", icon:"♜", tileIcon:"🗼", description:"Watch over the frontier and repel monster attacks before they reach your settlement.", base:{wood:40,gold:45}, effect:"DEFENCE", effectIcon:"⬟", effectValue:level=>level*3, next:level=>"+"+((level+1)*3)+" Defence"},
    farm: {name:"Gold Mine", category:"RESOURCE PRODUCTION", art:"GOLDEN VEIN", icon:"✦", tileIcon:"⛏️", description:"Dig deeper into the hills and uncover precious gold to fund your kingdom's expansion.", base:{wood:55,gold:25}, effect:"GOLD / MIN", effectIcon:"✦", effectValue:level=>Math.round(level*1.5*10)/10, next:level=>"+"+((level+1)*1.5).toFixed(1)+" Gold / min"}
  };
  const SLOTS = {keep:24,house:16,mill:18,tower:30,farm:32};
  const initial = () => ({wood:80,gold:120,workers:2,defence:0,day:1,kills:0,keepLevel:1,buildings:{keep:1,house:0,mill:0,tower:0,farm:0},levels:{keep:1,house:0,mill:0,tower:0,farm:0},trees:Array.from({length:49},(_,i)=>i).filter(i=>![6,13,16,18,20,24,27,30,32,34,41].includes(i)),nextWaveAt:Date.now()+60000,version:1});
  const $ = id => document.getElementById(id);
  let state;
  try {
    const saved=JSON.parse(localStorage.getItem(KEY)||"null");
    state=saved&&saved.version===1?{...initial(),...saved,buildings:{...initial().buildings,...saved.buildings},levels:{...initial().levels,...saved.levels}}:initial();
    // Migrate saves created before per-building levels existed.
    for(const key of Object.keys(BUILDINGS)) {
      if(!Number.isFinite(state.levels[key])) state.levels[key]=state.buildings[key]>0?(key==="keep"?Math.max(1,state.keepLevel||1):1):0;
      if(state.buildings[key]>0&&state.levels[key]===0)state.levels[key]=1;
    }
    state.keepLevel=state.levels.keep||1;
    if(!Array.isArray(state.trees))state.trees=initial().trees;
    if(!Number.isFinite(state.nextWaveAt))state.nextWaveAt=Date.now()+60000;
  } catch (_) {state=initial();}
  let selected="keep",lastTick=Date.now();
  const map=$("game-map");
  const costFor=(key,level=state.levels[key]||0)=>({wood:Math.round(BUILDINGS[key].base.wood*(level?1+level*.78:1)),gold:Math.round(BUILDINGS[key].base.gold*(level?1+level*.78:1))});
  const owned=key=>(state.levels[key]||0)>0;
  const format=n=>Math.floor(n).toLocaleString("en-US");
  function save(){try{localStorage.setItem(KEY,JSON.stringify(state));}catch(_){}}
  function say(message){$("game-message").textContent=message;}
  function spend(wood,gold){if(state.wood<wood||state.gold<gold){say("Not enough resources. Gather more wood or scout the forest for gold.");return false;}state.wood-=wood;state.gold-=gold;return true;}
  function updateEffects(key,delta){
    if(key==="keep"){state.keepLevel=state.levels.keep;state.defence+=delta;}
    if(key==="house")state.workers+=delta;
    if(key==="tower")state.defence+=delta*3;
  }
  function selectBuilding(key){if(!BUILDINGS[key])return;selected=key;render();}

  function renderMap(){
    map.replaceChildren();
    for(let i=0;i<49;i++){
      const key=Object.keys(SLOTS).find(k=>SLOTS[k]===i&&owned(k));
      const tile=document.createElement("button");tile.type="button";tile.className="tile";
      if(key){
        tile.classList.add(key==="keep"?"keep":"building");if(selected===key)tile.classList.add("selected");
        const sprite=document.createElement("span");sprite.className="sprite";sprite.textContent=BUILDINGS[key].tileIcon;tile.append(sprite);
        const label=document.createElement("span");label.className="tile-label";label.textContent=key==="keep"?"Keep":BUILDINGS[key].name.replace("Woodcutter's ","");tile.append(label);
        tile.setAttribute("aria-label",BUILDINGS[key].name+", level "+state.levels[key]);tile.setAttribute("aria-pressed",String(selected===key));
        tile.addEventListener("click",()=>selectBuilding(key));
      }else if(state.trees.includes(i)){
        tile.classList.add("tree");const sprite=document.createElement("span");sprite.className="sprite";sprite.textContent="🌲";tile.append(sprite);tile.setAttribute("aria-label","Forest tree — tap to chop");
        tile.addEventListener("click",()=>chop(i));
      }else if([6,13,20,27,34,41].includes(i)){
        tile.classList.add("water");const sprite=document.createElement("span");sprite.className="sprite";sprite.textContent="〰";tile.append(sprite);tile.disabled=true;tile.setAttribute("aria-label","River");
      }else{
        tile.classList.add("path");const sprite=document.createElement("span");sprite.className="sprite";sprite.textContent=[17,25,31].includes(i)?"◆":"·";tile.append(sprite);tile.setAttribute("aria-label","Cleared land");
      }
      map.append(tile);
    }
    if(state.waveActive){const tile=map.children[40];if(tile){tile.classList.add("monster");tile.querySelector(".sprite").textContent="👾";tile.setAttribute("aria-label","Monster attack");}}
  }
  function renderDetail(){
    const data=BUILDINGS[selected],level=state.levels[selected]||0,isOwned=level>0,isMax=level>=MAX_LEVEL,cost=costFor(selected,level);
    $("detail-art").className="detail-art art-"+selected;
    $("detail-art").querySelector(".art-sigil").textContent=data.icon;
    $("detail-level").textContent=isOwned?"LV. "+level:"NOT BUILT";
    $("detail-art-caption").textContent=data.art;
    $("detail-category").textContent=data.category;
    $("detail-name").textContent=data.name;
    $("detail-state").textContent=isOwned?(isMax?"MAX LEVEL":"OWNED"):"NOT BUILT";
    $("detail-state").classList.toggle("not-owned",!isOwned);
    $("detail-description").textContent=data.description;
    let effect;
    if(selected==="keep")effect="+"+level+" DEFENCE";
    else if(selected==="house")effect="+"+level+" WORKER"+(level===1?"":"S");
    else if(selected==="mill")effect="+"+(level*state.workers*.18*60).toFixed(1)+" WOOD / MIN";
    else if(selected==="farm")effect="+"+(level*(.12+(state.keepLevel||1)*.025)*60).toFixed(1)+" GOLD / MIN";
    else effect="+"+(level*3)+" DEFENCE";
    $("detail-production").textContent=isOwned?effect:"UNLOCK TO ACTIVATE";
    $("detail-production-icon").textContent=data.effectIcon;
    $("upgrade-level-text").textContent=isMax?"MAXIMUM LEVEL":("LEVEL "+(isOwned?level:0)+" / "+MAX_LEVEL);
    $("upgrade-progress").style.width=(level/MAX_LEVEL*100)+"%";
    $("next-level-benefit").textContent=isMax?"All upgrades complete":data.next(level);
    $("next-level-tag").textContent=isMax?"MAX":"LV. "+(level+1);
    $("cost-heading").textContent=isOwned?"UPGRADE COST":"CONSTRUCTION COST";
    $("cost-note").textContent=isMax?"Maximum level reached":"Resources are spent instantly";
    $("detail-wood-cost").textContent=isMax?"—":format(cost.wood);
    $("detail-gold-cost").textContent=isMax?"—":format(cost.gold);
    $("wood-check").textContent=isMax?"✓":(state.wood>=cost.wood?"✓":"!");
    $("gold-check").textContent=isMax?"✓":(state.gold>=cost.gold?"✓":"!");
    $("wood-check").classList.toggle("insufficient",!isMax&&state.wood<cost.wood);
    $("gold-check").classList.toggle("insufficient",!isMax&&state.gold<cost.gold);
    $("primary-action-icon").textContent=isOwned?"⬆":"＋";
    $("primary-action-label").textContent=isMax?"MAXIMUM LEVEL":(isOwned?"UPGRADE BUILDING":"CONSTRUCT BUILDING");
    $("primary-building-action").disabled=isMax||state.wood<cost.wood||state.gold<cost.gold;
    $("primary-building-action").setAttribute("aria-label",isOwned?"Upgrade "+data.name:"Build "+data.name);
    $("collect-production").disabled=!((state.levels.mill||0)>0||(state.levels.farm||0)>0);
  }
  function render(){
    $("wood").textContent=format(state.wood);$("gold").textContent=format(state.gold);
    $("workers").textContent=format(state.workers);$("defence").textContent=format(state.defence);
    $("day-label").textContent="DAY "+state.day;$("keep-level").textContent=state.keepLevel;
    $("realm-progress").style.width=Math.min(100,state.keepLevel/MAX_LEVEL*100)+"%";
    $("building-count").textContent=Object.values(state.levels).filter(v=>v>0).length;
    $("kills").textContent=format(state.kills);$("summary-workers").textContent=format(state.workers);
    $("keep-cost").textContent=format(costFor("keep",state.levels.keep).wood)+" wood · "+format(costFor("keep",state.levels.keep).gold)+" gold";
    $("wood-rate").textContent="+"+((state.levels.mill||0)*state.workers*.18*60).toFixed(1)+" / min";
    $("gold-rate").textContent="+"+((state.levels.farm||0)*(.12+state.keepLevel*.025)*60).toFixed(1)+" / min";
    renderMap();renderDetail();save();
  }
  function chop(index){
    if(!state.trees.includes(index)){say("That tree has already been cleared.");return;}
    state.trees=state.trees.filter(i=>i!==index);state.wood+=12;say("Tree felled. +12 wood. Your territory is opening up for new structures.");render();
  }
  function buildOrUpgrade(key){
    const level=state.levels[key]||0;
    if(level>=MAX_LEVEL){say(BUILDINGS[key].name+" has reached its maximum level.");return;}
    const cost=costFor(key,level);
    if(!spend(cost.wood,cost.gold)){renderDetail();return;}
    state.levels[key]=level+1;state.buildings[key]=1;
    updateEffects(key,1);
    if(key==="keep")state.keepLevel=state.levels.keep;
    say(level===0?BUILDINGS[key].name+" constructed. Your kingdom has grown stronger.":"Upgrade complete! "+BUILDINGS[key].name+" is now level "+state.levels[key]+".");
    render();
  }
  function wave(){
    state.waveActive=true;
    const strength=2+Math.floor(state.day/2);
    const power=state.defence+(state.levels.tower||0)*2+state.keepLevel;
    if(power>=strength){state.kills+=strength;state.gold+=18+strength*3;say("Monster wave repelled! Your guards held the frontier. +"+(18+strength*3)+" gold.");}
    else{const loss=Math.min(state.gold,12+strength*4);state.gold-=loss;say("Monsters reached the outskirts. You lost "+loss+" gold. Upgrade your Keep or build a Guard Tower.");}
    state.waveActive=false;state.day+=1;state.nextWaveAt=Date.now()+60000;render();
  }
  function tick(){
    const now=Date.now(),elapsed=Math.min(30,(now-lastTick)/1000);lastTick=now;
    if(state.levels.mill)state.wood+=state.levels.mill*state.workers*.18*elapsed;
    if(state.levels.farm)state.gold+=state.levels.farm*(.12+state.keepLevel*.025)*elapsed;
    const left=Math.max(0,Math.ceil((state.nextWaveAt-now)/1000));
    $("next-wave").textContent=left>0?"NIGHTFALL IN "+left+"S":"MONSTER WAVE!";
    if(now>=state.nextWaveAt)wave();
    $("wood").textContent=format(state.wood);$("gold").textContent=format(state.gold);
    $("wood-rate").textContent="+"+((state.levels.mill||0)*state.workers*.18*60).toFixed(1)+" / min";
    $("gold-rate").textContent="+"+((state.levels.farm||0)*(.12+state.keepLevel*.025)*60).toFixed(1)+" / min";
    renderDetail();
    if(Math.floor(now/10000)!==Math.floor((now-elapsed*1000)/10000))save();
  }

  document.querySelectorAll("[data-build]").forEach(btn=>btn.addEventListener("click",()=>selectBuilding(btn.dataset.build)));
  $("primary-building-action").addEventListener("click",()=>buildOrUpgrade(selected));
  $("chop-tree").addEventListener("click",()=>{const i=state.trees[0];if(i===undefined){say("The nearby forest is cleared. Upgrade your Lumber Mill for renewable wood.");return;}chop(i);});
  $("scout").addEventListener("click",()=>{const cache=18+Math.floor(Math.random()*24);state.gold+=cache;say("Your scout found an abandoned merchant cache. +"+cache+" gold.");render();});
  $("train-guard").addEventListener("click",()=>{if(spend(0,25)){state.defence+=2;say("Two guards have joined your watch. Defence +2.");render();}});
  $("upgrade-keep").addEventListener("click",()=>{selectBuilding("keep");buildOrUpgrade("keep");});
  $("collect-production").addEventListener("click",()=>{
    let wood=0,gold=0;
    if(state.levels.mill){wood=state.levels.mill*5;state.wood+=wood;}
    if(state.levels.farm){gold=state.levels.farm*5;state.gold+=gold;}
    if(!wood&&!gold){say("Build a Lumber Mill or Gold Mine first to collect production bonuses.");return;}
    say("Production collected: +"+wood+" wood and +"+gold+" gold.");render();
  });
  $("reset-game").addEventListener("click",()=>{$("confirm-modal").hidden=false;});
  $("cancel-reset").addEventListener("click",()=>{$("confirm-modal").hidden=true;});
  $("confirm-reset").addEventListener("click",()=>{state=initial();selected="keep";lastTick=Date.now();$("confirm-modal").hidden=true;say("A fresh kingdom awaits. Gather resources and shape your realm.");render();});
  if(window.Telegram&&window.Telegram.WebApp){try{window.Telegram.WebApp.ready();window.Telegram.WebApp.expand();}catch(_){}}
  render();setInterval(tick,1000);
})();