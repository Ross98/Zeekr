// Theme preference logic runs before body parsing; no vehicle API or DOM rebuild.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../zeekr_control/static/theme.js'), 'utf8');
function boot({saved=null, dark=false, blocked=false}={}) {
  const listeners={}, mediaListeners={}, dataset={}, style={}, controls=[{value:''}];
  const media={matches:dark, addEventListener:(name,fn)=>mediaListeners[name]=fn};
  const localStorage={getItem:()=>{if(blocked)throw Error('blocked');return saved;},setItem:(key,value)=>{if(blocked)throw Error('blocked');saved=value;}};
  const document={documentElement:{dataset,style},querySelectorAll:()=>controls,addEventListener:(name,fn)=>listeners[name]=fn};
  const window={matchMedia:()=>media,localStorage,addEventListener:(name,fn)=>listeners[name]=fn};
  vm.runInNewContext(source,{window,document});
  return {dataset,style,controls,media,change:value=>listeners.change({target:{matches:()=>true,value}}),system:value=>{media.matches=value;mediaListeners.change();},storage:(newValue,key='zeekr.theme',storageArea=localStorage)=>listeners.storage({key,newValue,storageArea}),saved:()=>saved};
}
let t=boot({dark:true});
assert.equal(t.dataset.theme,'dark','system theme applies before DOM ready');
assert.equal(t.style.colorScheme,'dark');
t.change('light');t.system(true);
assert.equal(t.dataset.theme,'light','explicit choice beats system');
assert.equal(t.saved(),'light');
t.change('system');assert.equal(t.dataset.theme,'dark');
t.system(false);assert.equal(t.dataset.theme,'light');
t.storage('dark');assert.equal(t.dataset.theme,'dark');assert.equal(t.controls[0].value,'dark');
t.storage('light','unrelated');assert.equal(t.dataset.theme,'dark');
t.storage('light','zeekr.theme',{});assert.equal(t.dataset.theme,'dark','ignore other storage areas');
t.storage(null);assert.equal(t.dataset.theme,'light','removal resets to system');
t.storage('dark');t.storage(null,null);assert.equal(t.dataset.theme,'light','clear resets to system');
assert.equal(boot({saved:'invalid',dark:true}).dataset.theme,'dark');
assert.equal(boot({saved:'light',dark:true}).dataset.theme,'light');
t=boot({blocked:true,dark:true});t.change('light');t.system(true);
assert.equal(t.dataset.theme,'light','storage failures retain session preference');
console.log('THEME_PASS');
