// Exercise actual chart geometry without mounting the dashboard or contacting APIs.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../zeekr_control/static/app.js'),'utf8');
const context={};vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('function chartGeometry('),source.indexOf('function chargingChart(')),context);
const points=[{time:100,power_kw:6,segment_id:0},{time:200,power_kw:7,segment_id:0},{time:300,power_kw:null,segment_id:0},{time:400,power_kw:8,segment_id:0},{time:500,power_kw:9,segment_id:1}];
let chart=context.chartGeometry(points,'power_kw');
assert.equal((chart.path.match(/M/g)||[]).length,3,'missing values and segment changes both break lines');
assert.equal(chart.dots.length,4,'singletons must remain visible');
assert.ok(chart.minY<=6&&chart.maxY>=9);
assert.equal(chart.x(100),64);assert.equal(chart.x(500),736);
assert.equal(chart.y(chart.minY),180);assert.equal(chart.y(chart.maxY),24);
chart=context.chartGeometry([{time:100,power_kw:6,segment_id:null}],'power_kw');
assert.match(chart.path,/^M/,'null segment cannot produce a leading L');
assert.ok(chart.minY<6&&chart.maxY>6,'constant data has a meaningful visible range');
assert.equal(context.chartGeometry([{time:100,power_kw:null}],'power_kw'),null);
chart=context.chartGeometry([
  {time:100,soc:20,segment_id:0},
  {time:200,soc:21,segment_id:0},
  {time:500,soc:30,segment_id:1},
],'soc',{minY:0,maxY:100,step:true});
assert.equal(chart.minY,0);assert.equal(chart.maxY,100);
assert.match(chart.path,/H.*V/,'SOC uses a step path instead of inventing a smooth slope');
assert.equal(chart.gaps.length,1,'segment changes expose one visible observation gap');
assert.equal(chart.dots[1].index,1,'geometry retains source indexes for a synchronized cursor');
const shared=[{time:100,soc:20,power_kw:null,segment_id:0},{time:200,soc:null,power_kw:0,segment_id:0},{time:300,soc:40,power_kw:10,segment_id:0}];
const bounds=context.chargingTimeBounds(shared);
const power=context.chartGeometry(shared,'power_kw',{...bounds,minY:0,maxY:11});
const soc=context.chartGeometry(shared,'soc',{...bounds,minY:0,maxY:100,step:true});
assert.equal(power.x(200),soc.x(200),'shared bounds prevent asymmetric missing data from shifting the time axis');
assert.equal(power.minX,100);assert.equal(power.maxX,300);assert.equal(power.dots[0].y,180,'zero power is valid');
assert.equal(context.chargingTimeBounds([{time:null}]).minX,undefined);
console.log('CHART_PASS');
