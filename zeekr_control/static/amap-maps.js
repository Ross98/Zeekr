/* Leaflet layers retain WGS84 coordinates; only the basemap projection uses GCJ02.
   Inverse projection keeps map clicks and draggable commute points in WGS84. */
(() => {
  const pi=Math.PI, a=6378245, ee=0.006693421622965943;
  function forward(p) {
    const {lat,lng}=p;
    if(lng<72.004||lng>137.8347||lat<0.8293||lat>55.8271)return L.latLng(lat,lng);
    const x=lng-105,y=lat-35;
    let dlat=-100+2*x+3*y+0.2*y*y+0.1*x*y+0.2*Math.sqrt(Math.abs(x));
    let dlng=300+x+2*y+0.1*x*x+0.1*x*y+0.1*Math.sqrt(Math.abs(x));
    const wave=(20*Math.sin(6*x*pi)+20*Math.sin(2*x*pi))*2/3;
    dlat+=wave+(20*Math.sin(y*pi)+40*Math.sin(y*pi/3))*2/3+(160*Math.sin(y*pi/12)+320*Math.sin(y*pi/30))*2/3;
    dlng+=wave+(20*Math.sin(x*pi)+40*Math.sin(x*pi/3))*2/3+(150*Math.sin(x*pi/12)+300*Math.sin(x*pi/30))*2/3;
    const rad=lat*pi/180,magic=1-ee*Math.sin(rad)**2,sqrt=Math.sqrt(magic);
    return L.latLng(lat+dlat*180/((a*(1-ee)/(magic*sqrt))*pi),lng+dlng*180/((a/sqrt)*Math.cos(rad)*pi));
  }
  function inverse(p) {
    let result=L.latLng(p.lat,p.lng);
    for(let i=0;i<8;i++) {
      const projected=forward(result),dlat=projected.lat-p.lat,dlng=projected.lng-p.lng;
      result=L.latLng(result.lat-dlat,result.lng-dlng);
      if(Math.max(Math.abs(dlat),Math.abs(dlng))<1e-10)break;
    }
    return result;
  }
  const projection=L.Projection.SphericalMercator;
  const crs=L.extend({},L.CRS.EPSG3857,{
    project:p=>projection.project(forward(p)),
    unproject:p=>inverse(projection.unproject(p)),
    latLngToPoint(p,zoom){return this.transformation._transform(this.project(p),this.scale(zoom));},
    pointToLatLng(p,zoom){return this.unproject(this.transformation.untransform(p,this.scale(zoom)));}
  });
  function createMap(element,options={}) {
    return L.map(element,{...options,crs});
  }
  function addTiles(map) {
    return L.tileLayer('https://wprd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=7&x={x}&y={y}&z={z}',{
      subdomains:'1234',minZoom:2,maxZoom:18,attribution:'© <a href="https://www.amap.com/" target="_blank" rel="noopener">高德地图</a>'
    }).on('tileerror',()=>{
      const container=map.getContainer();
      let note=container.parentElement.querySelector('.amap-load-error');
      if(!note){note=document.createElement('p');note.className='amap-load-error subtle';container.after(note);}
      note.textContent='部分高德底图未加载，可稍后重试。';
    }).addTo(map);
  }
  window.AmapMaps={createMap,addTiles,crs};
})();
