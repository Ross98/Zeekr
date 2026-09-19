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
console.log('CHART_PASS');
