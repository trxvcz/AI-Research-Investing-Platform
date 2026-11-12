import { defineConfig } from 'vite';
export default defineConfig({base:'/panel/',server:{host:'127.0.0.1',proxy:{'/v1':'http://127.0.0.1:8081'}}});
