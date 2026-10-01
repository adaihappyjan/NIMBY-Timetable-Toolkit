const test=require('node:test');
const assert=require('node:assert/strict');

test('tile frontier preserves deterministic nearest-first order across batches',async()=>{
  const {TileFrontier}=await import('../scripts/autotrack/frontier.mjs');
  const anchors=[[20,50],[110,90]];
  const score=p=>anchors.reduce((s,a)=>s+Math.hypot(p[0]-a[0],p[1]-a[1]),0);
  const compare=(a,b)=>score(a)-score(b)||a[0]-b[0]||a[1]-b[1];
  const tiles=Array.from({length:1500},(_,i)=>[(i*37)%251,(i*19)%211]);
  let heap=new TileFrontier(tiles.slice(0,500),anchors),expected=tiles.slice(0,500);
  for(let i=0;i<100;i++){
    expected.sort(compare);assert.deepEqual(heap.pop(),expected.shift());
    heap.push(tiles[500+i]);expected.push(tiles[500+i]);
  }
  // Decoder serializes the remaining frontier and restores it in the next batch.
  heap=new TileFrontier(heap.tiles(),anchors);
  for(const p of tiles.slice(600)){heap.push(p);expected.push(p);}
  expected.sort(compare);
  assert.equal(heap.length,expected.length);
  for(const p of expected)assert.deepEqual(heap.pop(),p);
  assert.equal(heap.pop(),undefined);assert.equal(heap.length,0);
});

test('tile frontier ties use x then y; empty and singleton are supported',async()=>{
  const {TileFrontier}=await import('../scripts/autotrack/frontier.mjs');
  const heap=new TileFrontier([],[[0,0],[2,2]]);
  for(const p of [[2,0],[0,2],[2,2],[0,0]])heap.push(p);
  assert.deepEqual(Array.from({length:4},()=>heap.pop()),[[0,0],[2,2],[0,2],[2,0]]);
  heap.push([5,7]);assert.deepEqual(heap.pop(),[5,7]);assert.deepEqual(heap.tiles(),[]);
});
