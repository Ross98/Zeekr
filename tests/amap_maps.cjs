const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const context={window:{},L:{CRS:{EPSG3857:{}},extend:Object.assign,Projection:{SphericalMercator:{project:p=>p,unproject:p=>p}},latLng:(lat,lng)=>({lat,lng})}};
vm.runInNewContext(fs.readFileSync('zeekr_control/static/amap-maps.js','utf8'),context);
const maps=context.window.AmapMaps;
for(const [lat,lng] of [[39.9,116.4],[31.2,121.5],[22.5,114.1],[0,0],[51,-1]]){
 const original={lat,lng},projected=maps.crs.project(original),restored=maps.crs.unproject(projected);
 assert.ok(Math.abs(restored.lat-lat)<1e-7);assert.ok(Math.abs(restored.lng-lng)<1e-7);
 if(lat===0||lat===51)assert.deepEqual(projected,original);
}
const beijing=maps.crs.project({lat:39.9,lng:116.4});
assert.ok(beijing.lng>116.406&&beijing.lng<116.407);assert.ok(beijing.lat>39.901&&beijing.lat<39.902);
console.log('Amap coordinate projection and inverse passed');
