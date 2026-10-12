import { readdir, readFile } from 'node:fs/promises'
import { dirname, join, resolve, sep } from 'node:path'
import { createRequire } from 'node:module'
import type { Plugin } from 'vite'

const root = dirname(createRequire(import.meta.url).resolve('pdfjs-dist/package.json'))
const folders = ['cmaps', 'standard_fonts', 'wasm']

export function pdfAssets(): Plugin {
  return {
    name: 'offline-pdf-assets',
    configureServer(server) {
      server.middlewares.use('/pdf-assets', async (request, response, next) => {
        const name = decodeURIComponent((request.url ?? '').split('?')[0]).replace(/^\//, '')
        const relative = name === 'pdf.worker.min.mjs' ? 'build/pdf.worker.min.mjs' : name
        const target = resolve(root, relative)
        if (!target.startsWith(root + sep) || !(relative.startsWith('build/pdf.worker.min.mjs')
          || folders.some(folder => relative.startsWith(`${folder}/`)))) { next(); return }
        try {
          const data = await readFile(target)
          response.setHeader('Content-Type', target.endsWith('.mjs') || target.endsWith('.js')
            ? 'application/javascript' : target.endsWith('.wasm') ? 'application/wasm' : 'application/octet-stream')
          response.end(data)
        } catch { next() }
      })
    },
    async generateBundle() {
      this.emitFile({ type: 'asset', fileName: 'pdf-assets/pdf.worker.min.mjs',
        source: await readFile(join(root, 'build/pdf.worker.min.mjs')) })
      for (const folder of folders) {
        for (const entry of await readdir(join(root, folder), { withFileTypes: true })) {
          if (entry.isFile()) this.emitFile({ type: 'asset', fileName: `pdf-assets/${folder}/${entry.name}`,
            source: await readFile(join(root, folder, entry.name)) })
        }
      }
    },
  }
}
