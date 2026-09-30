import {build} from 'esbuild';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
const dir=path.dirname(fileURLToPath(import.meta.url));
await build({entryPoints:[path.join(dir,'../autotrack_tiles.mjs')],nodePaths:[path.join(dir,'node_modules')],bundle:true,platform:'node',format:'esm',target:'node22',minify:true,legalComments:'inline',outfile:path.join(dir,'../../third_party/autotrack/tiles.mjs')});
