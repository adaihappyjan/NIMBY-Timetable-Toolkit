// Deterministic min-heap. Scores are computed once, not on every tile visit.
export class TileFrontier {
  constructor(tiles, anchors) { this.heap=[];this.anchors=anchors;for(const tile of tiles)this.push(tile); }
  before(a,b) { return a.score-b.score||a.tile[0]-b.tile[0]||a.tile[1]-b.tile[1]; }
  push(tile) {
    const entry={tile,score:this.anchors.reduce((s,a)=>s+Math.hypot(tile[0]-a[0],tile[1]-a[1]),0)};
    const h=this.heap;let i=h.length;h.push(entry);
    while(i>0){const p=(i-1)>>1;if(this.before(h[p],entry)<=0)break;h[i]=h[p];i=p;}h[i]=entry;
  }
  pop() {
    const h=this.heap;if(!h.length)return undefined;
    const result=h[0],last=h.pop();
    if(h.length){let i=0;while(2*i+1<h.length){let child=2*i+1;if(child+1<h.length&&this.before(h[child+1],h[child])<0)child++;
      if(this.before(last,h[child])<=0)break;h[i]=h[child];i=child;}h[i]=last;}
    return result.tile;
  }
  get length(){return this.heap.length;}
  tiles(){return this.heap.map(e=>e.tile);}
}
