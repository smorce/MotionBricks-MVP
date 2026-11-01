import {defineConfig} from 'vite';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const webRoot = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(webRoot, '..');

const threeRoot = path.resolve(webRoot, 'node_modules/three');

export default defineConfig({
  resolve: {
    alias: [
      {find: 'three/addons', replacement: path.resolve(threeRoot, 'examples/jsm')},
      {find: 'three', replacement: threeRoot},
    ],
  },
  server: {
    host: '127.0.0.1',
    port: 5188,
    fs: {allow: [webRoot, repoRoot, threeRoot]},
  },
});
