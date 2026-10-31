import fs from 'node:fs';
import path from 'node:path';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// In development the approved versions are served from ../approved (or APPROVED_DIR), the same
// path nginx exposes in the container, so the app code is identical in both.
function approvedVersions() {
  const root = path.resolve(process.env.APPROVED_DIR ?? path.join(__dirname, '..', 'approved'));
  return {
    name: 'approved-versions',
    configureServer(server) {
      server.middlewares.use('/approved', (req, res, next) => {
        const target = path.resolve(root, '.' + decodeURIComponent(req.url.split('?')[0]));
        if (!target.startsWith(root)) return next();
        fs.stat(target, (err, stat) => {
          if (err || !stat.isFile()) {
            res.statusCode = 404;
            return res.end();
          }
          res.setHeader('Cache-Control', 'no-store');
          fs.createReadStream(target).pipe(res);
        });
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), approvedVersions()],
  optimizeDeps: {
    include: ['plotly.js-dist-min'],
  },
});
