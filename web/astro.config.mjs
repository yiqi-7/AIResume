import { defineConfig } from 'astro/config';
import react from '@astrojs/react';
import tailwindcss from '@tailwindcss/vite';
import http from 'node:http';

// Astro 7's dev route stack runs ahead of Vite's normal proxy. Put only /api
// at the front; production is still static output behind nginx.
function localApiProxy() {
  return {
    name: 'airesume-local-api',
    apply: 'serve',
    configureServer(server) {
      return () => server.middlewares.stack.unshift({
        route: '',
        handle(req, res, next) {
          if (!req.url?.startsWith('/api/')) return next();
          const target = new URL(req.url, process.env.API_PROXY_TARGET || 'http://127.0.0.1:8010');
          const upstream = http.request(target, { method: req.method, headers: req.headers }, (reply) => {
            res.writeHead(reply.statusCode || 502, reply.headers);
            reply.pipe(res);
          });
          upstream.on('error', () => {
            if (!res.headersSent) res.writeHead(502, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({ code: 'API_OFFLINE', message: '后端服务未连接，请确认 API 已启动。' }));
          });
          req.pipe(upstream);
        },
      });
    },
  };
}

export default defineConfig({
  site: 'https://key123456.online',
  output: 'static',
  trailingSlash: 'always',
  devToolbar: { enabled: false },
  integrations: [react()],
  vite: {
    plugins: [tailwindcss(), localApiProxy()],
  },
});
