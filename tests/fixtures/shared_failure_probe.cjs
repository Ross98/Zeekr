const {fixture}=require('../ui_insight_helpers.cjs');
(async()=>{
 const f=await fixture({initialResearch:false});
 try{throw Error('DO_NOT_RECORD');}
 catch(error){await f.fail(error);throw error;}
 finally{await f.close();}
})().catch(()=>{process.exitCode=1;});
